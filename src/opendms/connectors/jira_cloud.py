"""Jira Cloud connector — REST v3, real implementation.

Ported from the OpenITSM KISC handler (src/openitsm/uapf/handlers/jira.py) with
two changes. First, credentials come from the encrypted secret store instead of
connections.config, so the token is never returned by a read endpoint. Second,
the payloads talk about documents rather than incidents, because in OpenDMS the
thing that spawns a Jira task is a registered document being routed to a unit.

Descriptions are Atlassian Document Format. Jira Cloud rejects a plain string on
v3 (it is accepted on v2, which is what makes this a common first-attempt 400),
so the ADF wrapper below is not optional.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from opendms.connectors.base import Field, Operation, Result, missing_fields

KIND = "jira_cloud"
DISPLAY_NAME = "Jira Cloud"
IMPLEMENTED = True
SUMMARY = "Creates and transitions Jira issues for documents routed to a unit."

CONFIG_FIELDS = (
    Field("base_url", "Base URL", placeholder="https://example.atlassian.net",
          help="Site URL without a trailing path."),
    Field("email", "Account e-mail", help="The Atlassian account the API token belongs to."),
    Field("project_key", "Project key", placeholder="RS",
          help="Default project for created issues; a process step can override it."),
    Field("issue_type", "Issue type", required=False, placeholder="Task",
          help="Defaults to Task."),
)

SECRET_FIELDS = (
    Field("api_token", "API token", kind="password",
          help="Created at id.atlassian.com → Security → API tokens. Stored encrypted."),
)

OPERATIONS = (
    Operation("create_issue", "connector/jira.create-issue",
              "Create a Jira issue for a document."),
    Operation("transition", "connector/jira.transition",
              "Move a Jira issue to another status."),
    Operation("comment", "connector/jira.comment",
              "Add a comment to a Jira issue."),
)

SPEC: tuple[str, ...] = ()

_TIMEOUT = 20.0


def _auth(email: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()


def _headers(config: dict, secret: dict) -> dict[str, str]:
    return {
        "Authorization": _auth(config.get("email", ""), secret.get("api_token", "")),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _adf(text: str) -> dict[str, Any]:
    """Wrap plain text as an Atlassian Document Format paragraph block."""
    paragraphs = [p for p in (text or "").split("\n") if p.strip()] or [""]
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": p}]}
            for p in paragraphs
        ],
    }


def _preflight(config: dict, secret: dict) -> Result | None:
    missing = missing_fields(CONFIG_FIELDS, config) + missing_fields(SECRET_FIELDS, secret)
    if missing:
        return Result.fail("connection incomplete", missing=missing)
    return None


async def test(config: dict, secret: dict) -> Result:
    """Verify credentials and that the configured project is reachable."""
    bad = _preflight(config, secret)
    if bad:
        return bad
    base = config["base_url"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            me = await c.get(f"{base}/rest/api/3/myself", headers=_headers(config, secret))
            if me.status_code == 401:
                return Result.fail("authentication rejected — check e-mail and API token")
            if me.status_code >= 300:
                return Result.fail(f"jira {me.status_code}: {me.text[:200]}")
            proj = await c.get(
                f"{base}/rest/api/3/project/{config['project_key']}",
                headers=_headers(config, secret),
            )
    except Exception as exc:
        return Result.fail(f"{type(exc).__name__}: {exc}")

    account = me.json().get("displayName")
    if proj.status_code >= 300:
        return Result.fail(
            f"authenticated as {account}, but project {config['project_key']} is not "
            f"readable (jira {proj.status_code})"
        )
    return Result.good(
        detail=f"authenticated as {account}; project {proj.json().get('name')} reachable",
        account=account,
        project=proj.json().get("name"),
    )


async def _create_issue(config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    bad = _preflight(config, secret)
    if bad:
        return bad
    base = config["base_url"].rstrip("/")
    project = inputs.get("project_key") or config.get("project_key")
    doc_id = inputs.get("document_id")
    reg_no = inputs.get("registration_number") or (f"doc {doc_id}" if doc_id else "document")
    summary = inputs.get("summary") or f"[OpenDMS] {reg_no}"
    body = inputs.get("description") or "\n".join(
        p for p in [
            f"Registration number: {reg_no}" if reg_no else "",
            f"Title: {inputs['title']}" if inputs.get("title") else "",
            f"Unit: {inputs['unit']}" if inputs.get("unit") else "",
            f"Deadline: {inputs['due_date']}" if inputs.get("due_date") else "",
            f"Document DID: {inputs['doc_did']}" if inputs.get("doc_did") else "",
            f"Raised by UAPF package {ctx.get('package_id')}" if ctx.get("package_id") else "",
        ] if p
    )
    fields: dict[str, Any] = {
        "project": {"key": project},
        "issuetype": {"name": inputs.get("issue_type") or config.get("issue_type") or "Task"},
        "summary": summary[:250],
        "description": _adf(body),
    }
    if inputs.get("due_date"):
        fields["duedate"] = inputs["due_date"]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(f"{base}/rest/api/3/issue", json={"fields": fields},
                             headers=_headers(config, secret))
    except Exception as exc:
        return Result.fail(f"{type(exc).__name__}: {exc}")
    if r.status_code >= 300:
        return Result.fail(f"jira {r.status_code}: {r.text[:300]}")
    data = r.json()
    return Result.good(
        created=True, jira_key=data.get("key"), jira_id=data.get("id"),
        url=f"{base}/browse/{data.get('key')}",
    )


async def _transition(config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    bad = _preflight(config, secret)
    if bad:
        return bad
    key = inputs.get("jira_key")
    if not key:
        return Result.fail("jira_key is required")
    want = (inputs.get("transition") or inputs.get("to_status") or "").strip().lower()
    base = config["base_url"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            tr = await c.get(f"{base}/rest/api/3/issue/{key}/transitions",
                             headers=_headers(config, secret))
            if tr.status_code >= 300:
                return Result.fail(f"jira {tr.status_code}: {tr.text[:200]}")
            options = tr.json().get("transitions", [])
            if not options:
                return Result.fail(f"{key} has no available transitions")
            chosen = None
            if want:
                for o in options:
                    if want in (o.get("name", "").lower(), o.get("to", {}).get("name", "").lower()):
                        chosen = o
                        break
                if chosen is None:
                    names = [o.get("name") for o in options]
                    return Result.fail(f"no transition matching '{want}'", available=names)
            else:
                chosen = options[0]
            rr = await c.post(f"{base}/rest/api/3/issue/{key}/transitions",
                              json={"transition": {"id": chosen["id"]}},
                              headers=_headers(config, secret))
    except Exception as exc:
        return Result.fail(f"{type(exc).__name__}: {exc}")
    if rr.status_code >= 300:
        return Result.fail(f"jira {rr.status_code}: {rr.text[:200]}")
    return Result.good(transitioned=True, jira_key=key, transition=chosen.get("name"))


async def _comment(config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    bad = _preflight(config, secret)
    if bad:
        return bad
    key, body = inputs.get("jira_key"), inputs.get("body")
    if not (key and body):
        return Result.fail("jira_key and body are required")
    base = config["base_url"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
            r = await c.post(f"{base}/rest/api/3/issue/{key}/comment",
                             json={"body": _adf(body)}, headers=_headers(config, secret))
    except Exception as exc:
        return Result.fail(f"{type(exc).__name__}: {exc}")
    if r.status_code >= 300:
        return Result.fail(f"jira {r.status_code}: {r.text[:200]}")
    return Result.good(commented=True, jira_key=key, comment_id=r.json().get("id"))


_OPS = {"create_issue": _create_issue, "transition": _transition, "comment": _comment}


async def invoke(operation: str, config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    fn = _OPS.get(operation)
    if fn is None:
        return Result.fail(f"unknown jira_cloud operation '{operation}'",
                           available=sorted(_OPS))
    return await fn(config, secret, inputs, ctx)
