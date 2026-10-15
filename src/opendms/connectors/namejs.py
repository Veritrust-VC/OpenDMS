"""Namejs DVS connector — REST API v3.11.1 (RIX Flow), real implementation.

Follows the Namejs-MCP adapter (src/namejs/client.js in the Namejs-MCP repo):
OAuth2 token from the Namejs STS, then typed calls under the /API base path. The
endpoint paths and permission codes come from that repo's Namejs-API/openapi.json
and endpoint-inventory.md; see the table in OPERATIONS.

Connection settings, as the Namejs installation is usually given to us:

    base_url   https://dvs.iestade.lv   or   https://10.20.30.40   (address or IP)
    api_path   /API                     (Namejs default)
    token_url  <base_url>/STS/connect/token   unless set explicitly

Two grants are supported, both offered by the Namejs STS:
  - client_credentials — an integration account (client id + secret); preferred;
  - password           — a named Namejs user (client id + user name + password),
                         for installations that issue no integration client.

Responses are JSON even when Namejs labels them text/plain, so bodies are parsed
regardless of content type. Failures never raise (see connectors/base.py).
"""

from __future__ import annotations

import base64
import time
from typing import Any, Optional

import httpx

from opendms.connectors.base import Field, Operation, Result, missing_fields

KIND = "namejs"
DISPLAY_NAME = "Namejs"
IMPLEMENTED = True
SUMMARY = "Namejs DVS (RIX Flow) REST API — documents, tasks, statuses, nomenclature."

CONFIG_FIELDS = (
    Field("base_url", "Namejs adrese (URL vai IP)", placeholder="https://dvs.iestade.lv",
          help="Namejs servera adrese bez /API, piem. https://dvs.iestade.lv vai https://10.20.30.40."),
    Field("api_path", "API ceļš", required=False, placeholder="/API",
          help="Noklusējums /API."),
    Field("token_url", "Žetona adrese (STS)", required=False,
          placeholder="https://dvs.iestade.lv/STS/connect/token",
          help="Tukšs = <adrese>/STS/connect/token."),
    Field("grant_type", "Pieteikšanās veids", required=False, kind="select",
          choices=("client_credentials", "password"),
          help="client_credentials — integrācijas konts (ieteicams); password — Namejs lietotājs."),
    Field("client_id", "Klienta ID (client_id)"),
    Field("username", "Lietotājvārds", required=False,
          help="Tikai pieteikšanās veidam password."),
    Field("scope", "Scope", required=False, placeholder="namejs.api",
          help="Ja Namejs STS to prasa."),
    Field("verify_tls", "Pārbaudīt TLS sertifikātu", required=False, kind="bool",
          help="Izslēgt tikai, ja Namejs pieejams pēc IP ar iekšējās CA vai paša parakstītu sertifikātu."),
)

SECRET_FIELDS = (
    Field("client_secret", "Klienta noslēpums (client_secret)", kind="password", required=False,
          help="Integrācijas konta noslēpums. Glabājas šifrēts, netiek atgriezts."),
    Field("password", "Parole", kind="password", required=False,
          help="Tikai pieteikšanās veidam password. Glabājas šifrēts."),
)

# name, capability, summary, direction — paths and Namejs permission codes in _OPS below.
OPERATIONS = (
    Operation("search_documents", "connector/namejs.search-documents",
              "Atlasīt dokumentus (GET /api/documents, PP.MKL.03).", direction="inbound"),
    Operation("get_document", "connector/namejs.get-document",
              "Dokumenta kartīte (GET /api/documents/{id}, PP.DPV.APS.03).", direction="inbound"),
    Operation("list_document_files", "connector/namejs.list-document-files",
              "Dokumenta datņu saraksts (GET /api/documents/{id}/files, PP.DPV.DTN.32).", direction="inbound"),
    Operation("get_document_file", "connector/namejs.get-document-file",
              "Datnes aktuālā versija (GET …/files/{fileId}, PP.DPV.DTN.34).", direction="inbound"),
    Operation("get_flow_statuses", "connector/namejs.get-flow-statuses",
              "Dokumentu aprites statusi (GET /api/flowStatuses, PP.ADM.KLA.40).", direction="inbound"),
    Operation("list_tasks", "connector/namejs.list-tasks",
              "Uzdevumi (GET /api/tasks, PP.MKL.04).", direction="inbound"),
    Operation("list_nomenclature_cases", "connector/namejs.list-nomenclature-cases",
              "Lietu nomenklatūra (GET /api/nomenclatureCases, PP.KLS.LNV.26).", direction="inbound"),
    Operation("list_document_types", "connector/namejs.list-document-types",
              "Dokumentu veidi (GET /api/documentTypes, PP.KLS.DVV.19).", direction="inbound"),
    Operation("list_folders", "connector/namejs.list-folders",
              "Dokumentu mapes (GET /api/folders, PP.KLS.DMV.29).", direction="inbound"),
    Operation("register_document", "connector/namejs.register-document",
              "Reģistrēt dokumentu (PUT /api/documents/{id}/register, PP.DPV.APS.08)."),
    Operation("write_attribute", "connector/namejs.write-attribute",
              "Saglabāt brīvo atribūtu (POST /api/customDocumentAttributes, PP.DPV.DKK.BAV.04)."),
    Operation("subscribe_status_notifications", "connector/namejs.subscribe-status",
              "Abonēt statusa maiņas (POST /api/documentStatusNotifications, PP.INT.APS.12)."),
    Operation("poll_status_notifications", "connector/namejs.poll-status",
              "Izgūt un apstiprināt statusa maiņas (GET+PATCH /api/documentStatusNotifications, "
              "PP.INT.APS.13/14).", direction="inbound"),
)

SPEC: tuple[str, ...] = ()

_TIMEOUT = 30.0
_MAX_FILE = 15 * 1024 * 1024
_tokens: dict[tuple, tuple[str, float]] = {}   # (token_url, client_id, username) -> (token, expiry)


# ───────────────────────── connection plumbing ─────────────────────────

def _base(config: dict) -> str:
    base = (config.get("base_url") or "").strip().rstrip("/")
    if base and "://" not in base:
        base = "https://" + base           # a bare host or IP
    path = (config.get("api_path") or "/API").strip()
    if not path.startswith("/"):
        path = "/" + path
    if base.lower().endswith(path.lower()):   # someone pasted …/API as the address
        base = base[: -len(path)]
    return base + path.rstrip("/")


def _token_url(config: dict) -> str:
    explicit = (config.get("token_url") or "").strip()
    if explicit:
        return explicit
    root = _base(config)
    path = (config.get("api_path") or "/API").strip().rstrip("/") or "/API"
    if not path.startswith("/"):
        path = "/" + path
    root = root[: -len(path)] if root.endswith(path) else root
    return root + "/STS/connect/token"


def _verify(config: dict) -> bool:
    v = config.get("verify_tls")
    if v is None or v == "":
        return True
    if isinstance(v, str):
        return v.strip().lower() not in ("false", "0", "no", "nē")
    return bool(v)


def _grant(config: dict) -> str:
    return (config.get("grant_type") or "client_credentials").strip()


def _preflight(config: dict, secret: dict) -> Optional[Result]:
    missing = missing_fields(CONFIG_FIELDS, config)
    if _grant(config) == "password":
        missing += [k for k in ("username",) if not str(config.get(k) or "").strip()]
        missing += [k for k in ("password",) if not str(secret.get(k) or "").strip()]
    else:
        missing += [k for k in ("client_secret",) if not str(secret.get(k) or "").strip()]
    if missing:
        return Result.fail("connection incomplete", missing=missing)
    if _grant(config) not in ("client_credentials", "password"):
        return Result.fail(f"unknown grant_type '{_grant(config)}'")
    return None


async def _token(c: httpx.AsyncClient, config: dict, secret: dict) -> str:
    url = _token_url(config)
    key = (url, config.get("client_id"), config.get("username") if _grant(config) == "password" else None)
    hit = _tokens.get(key)
    if hit and time.time() < hit[1] - 30:
        return hit[0]
    form = {"grant_type": _grant(config), "client_id": config["client_id"]}
    if secret.get("client_secret"):
        form["client_secret"] = secret["client_secret"]
    if _grant(config) == "password":
        form["username"] = config["username"]
        form["password"] = secret["password"]
    if (config.get("scope") or "").strip():
        form["scope"] = config["scope"].strip()
    r = await c.post(url, data=form, headers={"Accept": "application/json"})
    if r.status_code >= 400:
        detail = ""
        try:
            j = r.json()
            detail = j.get("error_description") or j.get("error") or ""
        except Exception:
            detail = r.text[:200]
        raise _NamejsError(f"pieteikšanās Namejs STS neizdevās (HTTP {r.status_code}){': ' + detail if detail else ''}",
                           status=r.status_code, auth=True)
    j = r.json()
    tok = j.get("access_token")
    if not tok:
        raise _NamejsError("Namejs STS neatgrieza access_token", auth=True)
    _tokens[key] = (tok, time.time() + float(j.get("expires_in") or 300))
    return tok


class _NamejsError(Exception):
    def __init__(self, msg: str, status: int = 0, auth: bool = False):
        super().__init__(msg)
        self.status, self.auth = status, auth


def _clean(query: Optional[dict]) -> dict:
    return {k: v for k, v in (query or {}).items() if v is not None and v != ""}


async def _call(config: dict, secret: dict, method: str, path: str, *, query: Optional[dict] = None,
                body: Any = None, raw: bool = False) -> Any:
    async with httpx.AsyncClient(timeout=_TIMEOUT, verify=_verify(config)) as c:
        tok = await _token(c, config, secret)
        r = await c.request(method, _base(config) + path, params=_clean(query),
                            json=body if body is not None else None,
                            headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
        if r.status_code == 401:     # token revoked or expired early — once more with a fresh one
            _tokens.clear()
            tok = await _token(c, config, secret)
            r = await c.request(method, _base(config) + path, params=_clean(query),
                                json=body if body is not None else None,
                                headers={"Authorization": f"Bearer {tok}", "Accept": "application/json"})
    if r.status_code >= 400:
        raise _NamejsError(f"Namejs {method} {path} → HTTP {r.status_code}: {r.text[:300]}", status=r.status_code)
    if raw:
        return r
    if r.status_code == 204 or not r.content:
        return None
    try:
        return r.json()
    except ValueError:
        return r.text


async def _guard(coro) -> Result:
    try:
        return await coro
    except _NamejsError as e:
        return Result.fail(str(e), http_status=e.status or None)
    except httpx.HTTPError as e:
        return Result.fail(f"Namejs nav sasniedzams: {type(e).__name__}: {e}")


# ───────────────────────── test ─────────────────────────

async def test(config: dict, secret: dict) -> Result:
    """Token from the STS, then the user profile and the status vocabulary."""
    bad = _preflight(config, secret)
    if bad:
        return bad

    async def run() -> Result:
        me = await _call(config, secret, "GET", "/api/users/myProfile")
        statuses = await _call(config, secret, "GET", "/api/flowStatuses")
        who = None
        if isinstance(me, dict):
            who = me.get("userName") or me.get("login") or me.get("name") or \
                " ".join(x for x in (me.get("firstName"), me.get("lastName")) if x) or None
        n = len(statuses) if isinstance(statuses, list) else None
        return Result.good(detail=f"pieteicies Namejs{(' kā ' + who) if who else ''}; "
                                  f"{_base(config)}; aprites statusi: {n if n is not None else '?'}",
                           account=who, api=_base(config), flow_statuses=n)

    return await _guard(run())


# ───────────────────────── operations ─────────────────────────

_DOC_FILTERS = ("Name", "RegistrationNo", "Status", "FolderId", "DocumentTypeId", "DocumentCaseId",
                "RegistrationDateFrom", "RegistrationDateTo", "DueDateFrom", "DueDateUntil",
                "NomenclatureCaseIndex", "ResponsibleEmployeeId", "DepartmentId", "ModifiedFrom",
                "ModifiedTo", "CreatedFrom", "CreatedTo", "ExternalId", "Offset", "Limit")
_TASK_FILTERS = ("Number", "TaskType", "Status", "AssignerId", "ExecutorId", "ExecutorGroupId",
                 "DocumentId", "ApproverId", "Offset", "Limit")


def _pick(inputs: dict, keys: tuple[str, ...]) -> dict:
    """Accept both Namejs spelling (RegistrationNo) and snake_case (registration_no)."""
    out = {}
    low = {k.lower().replace("_", ""): v for k, v in inputs.items()}
    for k in keys:
        v = inputs.get(k, low.get(k.lower()))
        if v is not None and v != "":
            out[k] = v
    return out


def _need(inputs: dict, *keys: str) -> Optional[Result]:
    miss = [k for k in keys if inputs.get(k) in (None, "")]
    return Result.fail(f"{', '.join(miss)} is required") if miss else None


async def _search_documents(config, secret, inputs, ctx):
    q = _pick(inputs, _DOC_FILTERS)
    q.setdefault("Limit", 50)
    rows = await _call(config, secret, "GET", "/api/documents", query=q)
    return Result.good(documents=rows or [], count=len(rows or []))


async def _get_document(config, secret, inputs, ctx):
    bad = _need(inputs, "document_id")
    if bad:
        return bad
    return Result.good(document=await _call(config, secret, "GET", f"/api/documents/{int(inputs['document_id'])}"))


async def _list_document_files(config, secret, inputs, ctx):
    bad = _need(inputs, "document_id")
    if bad:
        return bad
    files = await _call(config, secret, "GET", f"/api/documents/{int(inputs['document_id'])}/files")
    return Result.good(files=files or [])


async def _get_document_file(config, secret, inputs, ctx):
    bad = _need(inputs, "document_id", "file_id")
    if bad:
        return bad
    r = await _call(config, secret, "GET",
                    f"/api/documents/{int(inputs['document_id'])}/files/{int(inputs['file_id'])}", raw=True)
    if len(r.content) > _MAX_FILE:
        return Result.fail(f"datne lielāka par {_MAX_FILE // (1024 * 1024)} MB", size=len(r.content))
    name = None
    cd = r.headers.get("content-disposition", "")
    if "filename" in cd:
        name = cd.split("filename", 1)[1].lstrip("*=").strip().strip('"').split("''")[-1]
    return Result.good(file_name=name, content_type=r.headers.get("content-type"), size=len(r.content),
                       content_base64=base64.b64encode(r.content).decode())


async def _get_flow_statuses(config, secret, inputs, ctx):
    rows = await _call(config, secret, "GET", "/api/flowStatuses", query=_pick(inputs, ("resolution",)))
    return Result.good(statuses=rows or [])


async def _list_tasks(config, secret, inputs, ctx):
    q = _pick(inputs, _TASK_FILTERS)
    q.setdefault("Limit", 50)
    rows = await _call(config, secret, "GET", "/api/tasks", query=q)
    return Result.good(tasks=rows or [], count=len(rows or []))


async def _list_nomenclature_cases(config, secret, inputs, ctx):
    rows = await _call(config, secret, "GET", "/api/nomenclatureCases",
                       query=_pick(inputs, ("parentId", "date", "year", "fullIndex")))
    return Result.good(cases=rows or [], count=len(rows or []))


async def _list_document_types(config, secret, inputs, ctx):
    rows = await _call(config, secret, "GET", "/api/documentTypes",
                       query=_pick(inputs, ("parentId", "date", "code")))
    return Result.good(document_types=rows or [], count=len(rows or []))


async def _list_folders(config, secret, inputs, ctx):
    rows = await _call(config, secret, "GET", "/api/folders", query=_pick(inputs, ("folderGroupId", "date")))
    return Result.good(folders=rows or [], count=len(rows or []))


async def _register_document(config, secret, inputs, ctx):
    bad = _need(inputs, "document_id")
    if bad:
        return bad
    await _call(config, secret, "PUT", f"/api/documents/{int(inputs['document_id'])}/register")
    return Result.good(registered=True, document_id=int(inputs["document_id"]))


async def _write_attribute(config, secret, inputs, ctx):
    body = inputs.get("attribute") or {k: v for k, v in inputs.items() if k not in ("operation",)}
    if not body:
        return Result.fail("attribute body is required (CustomDocumentAttributeModel)")
    saved = await _call(config, secret, "POST", "/api/customDocumentAttributes", body=body)
    return Result.good(attribute=saved)


async def _subscribe(config, secret, inputs, ctx):
    body = {k: inputs[k] for k in ("documentId", "days", "statuses", "isForDelete") if k in inputs}
    await _call(config, secret, "POST", "/api/documentStatusNotifications", body=body)
    return Result.good(subscribed=True)


async def _poll(config, secret, inputs, ctx):
    page = await _call(config, secret, "GET", "/api/documentStatusNotifications",
                       query={"limit": inputs.get("limit") or 100})
    items = (page or {}).get("items") if isinstance(page, dict) else (page or [])
    items = items or []
    ids = [e.get("id") for e in items if isinstance(e, dict) and e.get("id") is not None]
    if ids and inputs.get("ack", True):
        await _call(config, secret, "PATCH", "/api/documentStatusNotifications", body=ids)
    return Result.good(events=items, count=len(items), acknowledged=bool(ids and inputs.get("ack", True)))


_OPS = {
    "search_documents": _search_documents,
    "get_document": _get_document,
    "list_document_files": _list_document_files,
    "get_document_file": _get_document_file,
    "get_flow_statuses": _get_flow_statuses,
    "list_tasks": _list_tasks,
    "list_nomenclature_cases": _list_nomenclature_cases,
    "list_document_types": _list_document_types,
    "list_folders": _list_folders,
    "register_document": _register_document,
    "write_attribute": _write_attribute,
    "subscribe_status_notifications": _subscribe,
    "poll_status_notifications": _poll,
}


async def invoke(operation: str, config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    fn = _OPS.get(operation)
    if fn is None:
        return Result.fail(f"unknown namejs operation '{operation}'", available=sorted(_OPS))
    bad = _preflight(config, secret)
    if bad:
        return bad
    return await _guard(fn(config, secret, inputs or {}, ctx or {}))
