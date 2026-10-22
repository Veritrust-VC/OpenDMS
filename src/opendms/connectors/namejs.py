"""Namejs DVS connector — REST API v3.11.1, real implementation.

Talks to the Namejs document management system (RIX Flow) directly over its
published REST API. No MCP layer in between: OpenDMS is the API client.

AUTHENTICATION. Namejs issues tokens from its own STS (OpenID Connect,
`<host>/STS/connect/token`). The driver uses the OAuth2 client-credentials
grant by default, or the password grant for installations that only issue
user accounts. Tokens are cached per (token URL, client) until shortly before
expiry, so a poll loop does not fetch a new token on every call.

ENDPOINTS. Paths follow the vendor spec archived in PPPA-LV/Namejs-MCP
(Namejs-API/openapi.json, endpoint-inventory.md). All are relative to the API
base, which includes the `/API` segment, e.g. https://dvs.example.lv/API.

STATUS FEED. Namejs has no webhooks. Status changes are pulled: subscribe once
(POST documentStatusNotifications), poll (GET), then acknowledge the ids that
were processed (PATCH). An event that is not acknowledged is delivered again,
so acknowledging only after processing gives at-least-once delivery.

RESPONSES. Lifecycle, subscribe and acknowledge endpoints answer 204 No
Content; file downloads return bytes. Neither is JSON, and the helper below
handles both rather than assuming a JSON body.

THE DRIVER DOES NOT CREATE OPENDMS DOCUMENTS. Like the mailbox connector, it
moves data in and out of Namejs and hands it back. Turning a Namejs document
into an OpenDMS document is the intake service's job.
"""

from __future__ import annotations

import base64
import binascii
import time
from typing import Any

import httpx

from opendms.connectors.base import Field, Operation, Result, missing_fields

KIND = "namejs"
DISPLAY_NAME = "Namejs"
IMPLEMENTED = True
SUMMARY = "Reads, registers and tracks documents in a Namejs DVS through its REST API."

CONFIG_FIELDS = (
    Field("base_url", "API address", placeholder="https://dvs.example.lv/API",
          help="Namejs API base including /API, without a trailing slash."),
    Field("token_url", "Token address", required=False,
          placeholder="https://dvs.example.lv/STS/connect/token",
          help="Leave blank to derive it from the API address (…/API → …/STS/connect/token)."),
    Field("client_id", "Client ID", help="Integration client issued by the Namejs administrator."),
    Field("grant_type", "Grant type", required=False, kind="select",
          choices=("client_credentials", "password"),
          help="Defaults to client_credentials."),
    Field("username", "User name", required=False,
          help="Only for the password grant."),
    Field("scope", "Scope", required=False, placeholder="namejs.api"),
    Field("verify_tls", "Verify TLS certificate", required=False, kind="bool",
          help="On by default. Turn off only for a lab host with a self-signed certificate."),
)

SECRET_FIELDS = (
    Field("client_secret", "Client secret", kind="password", required=False,
          help="Required for client_credentials. Stored encrypted."),
    Field("password", "Password", kind="password", required=False,
          help="Only for the password grant. Stored encrypted."),
)

OPERATIONS = (
    Operation("search_documents", "connector/namejs.search-documents",
              "Search the Namejs register by name, registration number, status or folder.",
              direction="inbound"),
    Operation("get_document", "connector/namejs.get-document",
              "Read one document card.", direction="inbound"),
    Operation("list_files", "connector/namejs.list-files",
              "List the files of a document.", direction="inbound"),
    Operation("download_file", "connector/namejs.download-file",
              "Download the current version of a document file (base64).", direction="inbound"),
    Operation("flow_statuses", "connector/namejs.flow-statuses",
              "Read the flow-status vocabulary.", direction="inbound"),
    Operation("create_document", "connector/namejs.create-document",
              "Create a document card in a Namejs folder."),
    Operation("register_document", "connector/namejs.register-document",
              "Register a document; Namejs assigns the registration number."),
    Operation("attach_file", "connector/namejs.attach-file",
              "Upload a file to a document."),
    Operation("set_attribute", "connector/namejs.set-attribute",
              "Write a custom attribute value on a document (e.g. DID or VC URL)."),
    Operation("start_task_flow", "connector/namejs.start-task-flow",
              "Start a Namejs task flow for a document."),
    Operation("subscribe_status", "connector/namejs.subscribe-status",
              "Subscribe to document status changes.", direction="inbound"),
    Operation("poll_status", "connector/namejs.poll-status",
              "Fetch pending status-change events.", direction="inbound"),
    Operation("ack_status", "connector/namejs.ack-status",
              "Acknowledge processed status-change events.", direction="inbound"),
)

SPEC: tuple[str, ...] = ()

_TIMEOUT = 30.0
_TOKENS: dict[tuple[str, str, str], tuple[str, float]] = {}


# ── connection helpers ───────────────────────────────────────────────────────

def _base(config: dict) -> str:
    return str(config.get("base_url") or "").strip().rstrip("/")


def _token_url(config: dict) -> str:
    explicit = str(config.get("token_url") or "").strip()
    if explicit:
        return explicit
    base = _base(config)
    if base.lower().endswith("/api"):
        return base[:-4] + "/STS/connect/token"
    return base + "/STS/connect/token"


def _grant(config: dict) -> str:
    return str(config.get("grant_type") or "client_credentials").strip() or "client_credentials"


def _verify(config: dict) -> bool:
    v = config.get("verify_tls")
    if v is None or v == "":
        return True
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "off")
    return bool(v)


def _preflight(config: dict, secret: dict) -> Result | None:
    missing = missing_fields(CONFIG_FIELDS, config)
    if _grant(config) == "password":
        if not str(config.get("username") or "").strip():
            missing.append("username")
        if not str(secret.get("password") or "").strip():
            missing.append("password")
    elif not str(secret.get("client_secret") or "").strip():
        missing.append("client_secret")
    if missing:
        return Result.fail("connection incomplete", missing=missing)
    return None


def _client(config: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, verify=_verify(config))


async def _token(c: httpx.AsyncClient, config: dict, secret: dict, *, fresh: bool = False) -> str:
    """Bearer token from the Namejs STS, cached until 30 s before expiry."""
    url = _token_url(config)
    grant = _grant(config)
    who = str(config.get("username") if grant == "password" else config.get("client_id"))
    key = (url, str(config.get("client_id")), who)
    cached = _TOKENS.get(key)
    if cached and not fresh and cached[1] > time.time() + 30:
        return cached[0]

    form = {"grant_type": grant, "client_id": str(config.get("client_id") or "")}
    if secret.get("client_secret"):
        form["client_secret"] = str(secret["client_secret"])
    if grant == "password":
        form["username"] = str(config.get("username") or "")
        form["password"] = str(secret.get("password") or "")
    if config.get("scope"):
        form["scope"] = str(config["scope"])

    r = await c.post(url, data=form, headers={"Accept": "application/json"})
    if r.status_code >= 300:
        raise _AuthError(f"token request rejected ({r.status_code}): {r.text[:200]}")
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise _AuthError("token response has no access_token")
    _TOKENS[key] = (token, time.time() + float(data.get("expires_in") or 300))
    return token


class _AuthError(Exception):
    pass


async def _call(
    config: dict, secret: dict, method: str, path: str, *,
    params: dict | None = None, json: Any = None, files: Any = None,
) -> tuple[int, Any, httpx.Headers]:
    """One authenticated API call. Retries once with a fresh token on 401.

    Returns (status, body, headers) where body is parsed JSON, raw bytes for a
    non-JSON response, or None for 204 / an empty body.
    """
    url = _base(config) + path
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    async with _client(config) as c:
        for attempt in (0, 1):
            token = await _token(c, config, secret, fresh=attempt == 1)
            r = await c.request(method, url, params=query, json=json, files=files,
                                headers={"Authorization": f"Bearer {token}",
                                         "Accept": "application/json"})
            if r.status_code != 401:
                break
    if r.status_code == 204 or not r.content:
        return r.status_code, None, r.headers
    if "json" in r.headers.get("content-type", ""):
        return r.status_code, r.json(), r.headers
    return r.status_code, r.content, r.headers


def _err(status: int, body: Any) -> str:
    if isinstance(body, dict):
        detail = body.get("detail") or body.get("title") or ""
        errors = body.get("errors")
        if errors:
            detail = f"{detail} {errors}".strip()
        return f"namejs {status}: {detail}"[:300]
    if isinstance(body, bytes):
        return f"namejs {status}: {body[:200].decode('utf-8', 'replace')}"
    return f"namejs {status}"


async def _guarded(fn, config: dict, secret: dict, inputs: dict) -> Result:
    bad = _preflight(config, secret)
    if bad:
        return bad
    try:
        return await fn(config, secret, inputs)
    except _AuthError as exc:
        return Result.fail(str(exc))
    except httpx.HTTPError as exc:
        return Result.fail(f"{type(exc).__name__}: {exc}")


def _int(inputs: dict, key: str) -> int | None:
    v = inputs.get(key)
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ── test ─────────────────────────────────────────────────────────────────────

async def test(config: dict, secret: dict) -> Result:
    """Verify the token grant and that the document register is readable."""
    async def _t(config, secret, _inputs):
        s1, statuses, _ = await _call(config, secret, "GET", "/api/flowStatuses")
        if s1 >= 300:
            return Result.fail(f"authenticated, but {_err(s1, statuses)}")
        s2, docs, _ = await _call(config, secret, "GET", "/api/documents", params={"Limit": 1})
        if s2 >= 300:
            return Result.fail(f"authenticated, but document register not readable — {_err(s2, docs)}")
        n = len(statuses) if isinstance(statuses, list) else 0
        return Result.good(
            detail=f"token issued to {config.get('client_id')}; register readable; {n} flow statuses",
            flow_statuses=n,
        )
    return await _guarded(_t, config, secret, {})


# ── operations ───────────────────────────────────────────────────────────────

_SEARCH_KEYS = {
    "name": "Name", "registration_no": "RegistrationNo", "status": "Status",
    "folder_id": "FolderId", "document_type_id": "DocumentTypeId",
    "external_id": "ExternalId", "file_content": "FileContent",
    "registration_date_from": "RegistrationDateFrom", "registration_date_to": "RegistrationDateTo",
    "created_from": "CreatedFrom", "created_to": "CreatedTo",
    "modified_from": "ModifiedFrom", "modified_to": "ModifiedTo",
    "offset": "Offset", "limit": "Limit",
}


async def _search_documents(config, secret, inputs):
    params = {api: inputs[k] for k, api in _SEARCH_KEYS.items() if inputs.get(k) not in (None, "")}
    params.setdefault("Limit", 20)
    s, body, _ = await _call(config, secret, "GET", "/api/documents", params=params)
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(count=len(body or []), documents=body or [])


async def _get_document(config, secret, inputs):
    doc_id = _int(inputs, "document_id")
    if doc_id is None:
        return Result.fail("document_id is required")
    s, body, _ = await _call(config, secret, "GET", f"/api/documents/{doc_id}")
    if s == 404:
        return Result.fail(f"document {doc_id} not found in Namejs")
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(document=body)


async def _list_files(config, secret, inputs):
    doc_id = _int(inputs, "document_id")
    if doc_id is None:
        return Result.fail("document_id is required")
    s, body, _ = await _call(config, secret, "GET", f"/api/documents/{doc_id}/files")
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(files=body or [])


async def _download_file(config, secret, inputs):
    doc_id, file_id = _int(inputs, "document_id"), _int(inputs, "file_id")
    if doc_id is None or file_id is None:
        return Result.fail("document_id and file_id are required")
    s, body, headers = await _call(config, secret, "GET", f"/api/documents/{doc_id}/files/{file_id}")
    if s >= 300:
        return Result.fail(_err(s, body))
    raw = body if isinstance(body, bytes) else (b"" if body is None else str(body).encode())
    return Result.good(
        file_id=file_id, size=len(raw),
        content_type=headers.get("content-type", "application/octet-stream"),
        content_b64=base64.b64encode(raw).decode(),
    )


async def _flow_statuses(config, secret, inputs):
    params = {"resolution": "true"} if inputs.get("resolution") else None
    s, body, _ = await _call(config, secret, "GET", "/api/flowStatuses", params=params)
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(flow_statuses=body or [])


async def _create_document(config, secret, inputs):
    name = str(inputs.get("name") or "").strip()
    if not name:
        return Result.fail("name is required")
    payload: dict[str, Any] = {
        "name": name,
        "sourceMedia": inputs.get("source_media") or "E",
        "description": inputs.get("description"),
        "externalId": inputs.get("external_id"),
        "correspondentNo": inputs.get("correspondent_no"),
        "correspondentDate": inputs.get("correspondent_date"),
    }
    for key, api in (("folder_id", "folderId"), ("type_id", "typeId"), ("department_id", "departmentId")):
        v = _int(inputs, key)
        if v is not None:
            payload[api] = v
    emp = _int(inputs, "responsible_employee_id")
    if emp is not None:
        payload["responsibleEmployee"] = {"employeeId": emp}
    payload = {k: v for k, v in payload.items() if v is not None}
    s, body, _ = await _call(config, secret, "POST", "/api/documents", json=payload,
                             params={"isIntegration": "true"})
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(created=True, document_id=(body or {}).get("id"),
                       status=(body or {}).get("status"))


async def _register_document(config, secret, inputs):
    doc_id = _int(inputs, "document_id")
    if doc_id is None:
        return Result.fail("document_id is required")
    s, body, _ = await _call(config, secret, "PUT", f"/api/documents/{doc_id}/register")
    if s >= 300:
        return Result.fail(_err(s, body))
    # Namejs owns the registration sequence; read the number back rather than guess it.
    s2, doc, _ = await _call(config, secret, "GET", f"/api/documents/{doc_id}")
    if s2 >= 300:
        return Result.good(registered=True, document_id=doc_id)
    return Result.good(registered=True, document_id=doc_id,
                       registration_no=doc.get("registrationNo"),
                       registration_date=doc.get("registrationDate"),
                       status=doc.get("status"))


async def _attach_file(config, secret, inputs):
    doc_id = _int(inputs, "document_id")
    name = str(inputs.get("file_name") or "").strip()
    if doc_id is None or not name or not inputs.get("content_b64"):
        return Result.fail("document_id, file_name and content_b64 are required")
    try:
        raw = base64.b64decode(inputs["content_b64"], validate=True)
    except (binascii.Error, ValueError):
        return Result.fail("content_b64 is not valid base64")
    mime = inputs.get("content_type") or "application/octet-stream"
    s, body, _ = await _call(config, secret, "POST", f"/api/documents/{doc_id}/files",
                             files={"file": (name, raw, mime)})
    if s >= 300:
        return Result.fail(_err(s, body))
    body = body or {}
    return Result.good(attached=True, document_id=doc_id, file_id=body.get("documentFileId"),
                       version=body.get("version"), sha256=body.get("sha256"))


async def _set_attribute(config, secret, inputs):
    doc_id, attr_id = _int(inputs, "document_id"), _int(inputs, "attribute_id")
    if doc_id is None or attr_id is None:
        return Result.fail("document_id and attribute_id are required")
    value: dict[str, Any] = {"attributeId": attr_id}
    for key, api in (("text_value", "textValue"), ("number_value", "numberValue"),
                     ("date_value", "dateValue"), ("bool_value", "boolValue")):
        if inputs.get(key) not in (None, ""):
            value[api] = inputs[key]
    if len(value) == 1:
        return Result.fail("one of text_value, number_value, date_value, bool_value is required")
    s, body, _ = await _call(config, secret, "POST", f"/api/documents/{doc_id}/caseattributevalues",
                             json=[value])
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(written=True, document_id=doc_id, attribute_id=attr_id)


async def _start_task_flow(config, secret, inputs):
    doc_id = _int(inputs, "document_id")
    if doc_id is None:
        return Result.fail("document_id is required")
    flow_id = _int(inputs, "task_flow_id")
    if flow_id is None:
        # No flow named: use the first one Namejs offers for this document.
        s, flows, _ = await _call(config, secret, "GET", f"/api/documents/{doc_id}/taskFlows")
        if s >= 300:
            return Result.fail(_err(s, flows))
        if not flows:
            return Result.fail(f"Namejs offers no task flow for document {doc_id}")
        flow_id = flows[0].get("id")
    s, body, _ = await _call(config, secret, "POST",
                             f"/api/documents/{doc_id}/taskFlows/{flow_id}/start")
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(started=True, document_id=doc_id, task_flow_id=flow_id)


async def _subscribe_status(config, secret, inputs):
    payload: dict[str, Any] = {
        "documentId": _int(inputs, "document_id") or 0,
        "isForDelete": bool(inputs.get("include_deletions", True)),
    }
    if inputs.get("statuses"):
        st = inputs["statuses"]
        payload["statuses"] = [x.strip() for x in st.split(",")] if isinstance(st, str) else list(st)
    if _int(inputs, "days") is not None:
        payload["days"] = _int(inputs, "days")
    s, body, _ = await _call(config, secret, "POST", "/api/documentStatusNotifications", json=payload)
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(subscribed=True, document_id=payload["documentId"] or None)


async def _poll_status(config, secret, inputs):
    limit = _int(inputs, "limit") or 100
    s, body, _ = await _call(config, secret, "GET", "/api/documentStatusNotifications",
                             params={"limit": limit})
    if s >= 300:
        return Result.fail(_err(s, body))
    body = body or {}
    events = body.get("items") or []
    acked = False
    if inputs.get("ack") and events:
        sa, ab, _ = await _call(config, secret, "PATCH", "/api/documentStatusNotifications",
                                json=[e["id"] for e in events])
        if sa >= 300:
            return Result.fail(f"events fetched but not acknowledged — {_err(sa, ab)}",
                               events=events)
        acked = True
    return Result.good(count=len(events), has_more=bool(body.get("hasMoreResults")),
                       acknowledged=acked, events=events)


async def _ack_status(config, secret, inputs):
    ids = inputs.get("event_ids") or []
    if isinstance(ids, str):
        ids = [x for x in ids.replace(" ", "").split(",") if x]
    try:
        ids = [int(x) for x in ids]
    except (TypeError, ValueError):
        return Result.fail("event_ids must be integers")
    if not ids:
        return Result.fail("event_ids is required")
    s, body, _ = await _call(config, secret, "PATCH", "/api/documentStatusNotifications", json=ids)
    if s >= 300:
        return Result.fail(_err(s, body))
    return Result.good(acknowledged=len(ids))


_OPS = {
    "search_documents": _search_documents,
    "get_document": _get_document,
    "list_files": _list_files,
    "download_file": _download_file,
    "flow_statuses": _flow_statuses,
    "create_document": _create_document,
    "register_document": _register_document,
    "attach_file": _attach_file,
    "set_attribute": _set_attribute,
    "start_task_flow": _start_task_flow,
    "subscribe_status": _subscribe_status,
    "poll_status": _poll_status,
    "ack_status": _ack_status,
}


async def invoke(operation: str, config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    fn = _OPS.get(operation)
    if fn is None:
        return Result.fail(f"unknown namejs operation '{operation}'", available=sorted(_OPS))
    return await _guarded(fn, config, secret, inputs or {})
