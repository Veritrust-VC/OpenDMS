"""HTTP client for VeriDocs SDK sidecar."""

import json
import logging
import uuid
from typing import Optional, Dict, Any
import httpx
from opendms.config import get_settings

logger = logging.getLogger(__name__)
_client: Optional[httpx.AsyncClient] = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        s = get_settings()
        headers = {}
        if s.sdk_api_key:
            headers["x-api-key"] = s.sdk_api_key
        _client = httpx.AsyncClient(base_url=s.sdk_url, timeout=30.0, headers=headers)
    return _client


def _build_headers(trace_id: Optional[str], actor: Optional[Dict[str, Any]]) -> Dict[str, str]:
    tid = trace_id or str(uuid.uuid4())
    headers = {"X-Trace-Id": tid}
    if actor:
        if actor.get("id") is not None:
            headers["X-Actor-User-Id"] = str(actor["id"])
        if actor.get("email"):
            headers["X-Actor-Email"] = actor["email"]
    return headers


async def _request(
    method: str,
    path: str,
    *,
    json_body: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    include_error_payload: bool = False,
) -> Optional[Dict[str, Any]]:
    headers = _build_headers(trace_id, actor)
    try:
        r = await _get_client().request(method, path, json=json_body, headers=headers)
        payload: Dict[str, Any] = {}
        if r.headers.get("content-type", "").lower().startswith("application/json"):
            payload = r.json()
        elif r.text:
            payload = {"response_text": r.text}
        payload.setdefault("trace_id", r.headers.get("X-Trace-Id") or headers["X-Trace-Id"])
        payload.setdefault("_meta", {
            "status_code": r.status_code,
            "method": method,
            "path": path,
        })
        if r.status_code in (200, 201):
            return payload
        if include_error_payload:
            return payload
        return None
    except Exception as e:
        logger.error("SDK request %s %s failed: %s", method, path, e)
        if include_error_payload:
            return {
                "error": "SDK request failed",
                "detail": str(e),
                "trace_id": headers["X-Trace-Id"],
                "_meta": {
                    "status_code": 502,
                    "method": method,
                    "path": path,
                },
            }
        return None


async def _request_multipart(
    path: str,
    *,
    files: Dict[str, Any],
    data: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    headers = _build_headers(trace_id, actor)
    try:
        r = await _get_client().post(path, files=files, data=data or {}, headers=headers)
        payload: Dict[str, Any] = {}
        if r.headers.get("content-type", "").lower().startswith("application/json"):
            payload = r.json()
        elif r.text:
            payload = {"response_text": r.text}
        payload.setdefault("trace_id", r.headers.get("X-Trace-Id") or headers["X-Trace-Id"])
        payload.setdefault("_meta", {
            "status_code": r.status_code,
            "method": "POST",
            "path": path,
        })
        if r.status_code in (200, 201):
            return payload
        return None
    except Exception as e:
        logger.error("SDK multipart request POST %s failed: %s", path, e)
        return None


async def close():
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def setup_org(
    org_code: str,
    org_name: str,
    org_description: str = "",
    trace_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    include_error_payload: bool = False,
) -> Optional[Dict]:
    return await _request("POST", "/api/setup/org", json_body={
        "orgCode": org_code,
        "orgName": org_name,
        "orgDescription": org_description,
    }, trace_id=trace_id, actor=actor, include_error_payload=include_error_payload)


# FIX: Added include_error_payload so create_document surfaces SDK errors
# instead of silently returning None
async def create_document(
    title: str,
    classification: str = "",
    reg_number: str = "",
    metadata: Dict = None,
    trace_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    include_error_payload: bool = False,
) -> Optional[Dict]:
    return await _request("POST", "/api/documents/create", json_body={
        "title": title, "classification": classification,
        "registrationNumber": reg_number, "metadata": metadata or {},
    }, trace_id=trace_id, actor=actor, include_error_payload=include_error_payload)


async def send_document(doc_did: str, recipient_did: str, method: str = "", trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request("POST", f"/api/documents/{doc_did}/send", json_body={"recipientDid": recipient_did, "deliveryMethod": method}, trace_id=trace_id, actor=actor)


async def receive_document(doc_did: str, sender_did: str, local_reg: str = "", trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request("POST", f"/api/documents/{doc_did}/receive", json_body={"senderDid": sender_did, "localRegistrationNumber": local_reg}, trace_id=trace_id, actor=actor)


async def assign_document(doc_did: str, assignee: str, department: str = "", trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request("POST", f"/api/documents/{doc_did}/assign", json_body={"assignee": assignee, "department": department}, trace_id=trace_id, actor=actor)


async def decide_document(doc_did: str, decision: str, resolution: str = "", trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request("POST", f"/api/documents/{doc_did}/decide", json_body={"decision": decision, "resolution": resolution}, trace_id=trace_id, actor=actor)


async def archive_document(doc_did: str, ref: str = "", trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request("POST", f"/api/documents/{doc_did}/archive", json_body={"archiveReference": ref}, trace_id=trace_id, actor=actor)


async def track_document(doc_did: str, trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request("GET", f"/api/documents/{doc_did}/track", trace_id=trace_id, actor=actor)


async def select_active_org(org_did: Optional[str], trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request(
        "POST",
        "/api/setup/select-org",
        json_body={"orgDid": org_did},
        trace_id=trace_id,
        actor=actor,
    )


async def health() -> Dict:
    result = await _request("GET", "/api/health")
    return result or {"status": "error"}


async def setup_status(
    trace_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
    org_did: Optional[str] = None,
) -> Dict:
    path = "/api/setup/status"
    if org_did:
        from urllib.parse import quote
        path += f"?orgDid={quote(org_did, safe='')}"
    result = await _request("GET", path, trace_id=trace_id, actor=actor)
    return result or {"status": "unavailable"}


async def get_audit_logs(limit: int = 50, offset: int = 0, trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    path = f"/api/audit/logs?limit={limit}&offset={offset}"
    return await _request("GET", path, trace_id=trace_id, actor=actor)


async def get_audit_log_by_id(log_id: int, trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict]:
    return await _request("GET", f"/api/audit/logs/{log_id}", trace_id=trace_id, actor=actor)


async def extract_summary(
    file_bytes: bytes,
    filename: str,
    metadata: Optional[Dict[str, Any]] = None,
    trace_id: Optional[str] = None,
    actor: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    return await _request_multipart(
        "/api/ai/extract-summary",
        files={"file": (filename, file_bytes, "application/octet-stream")},
        data={"metadata": (json.dumps(metadata or {}))},
        trace_id=trace_id,
        actor=actor,
    )


async def get_topic_trends(trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return await _request("GET", "/api/intelligence/topics", trace_id=trace_id, actor=actor)


async def get_similar_documents(doc_did: str, trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return await _request("GET", f"/api/intelligence/similar/{doc_did}", trace_id=trace_id, actor=actor)


async def get_warnings(trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return await _request("GET", "/api/intelligence/warnings", trace_id=trace_id, actor=actor)


async def generate_briefing(payload: Optional[Dict[str, Any]] = None, trace_id: Optional[str] = None, actor: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    return await _request("POST", "/api/intelligence/briefing", json_body=payload or {}, trace_id=trace_id, actor=actor)
