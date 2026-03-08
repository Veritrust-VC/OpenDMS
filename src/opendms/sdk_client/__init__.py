"""HTTP client for VeriDocs SDK sidecar."""

import logging
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


async def close():
    global _client
    if _client:
        await _client.aclose()
        _client = None


async def setup_org(org_code: str, org_name: str) -> Optional[Dict]:
    try:
        r = await _get_client().post("/api/setup/org", json={"orgCode": org_code, "orgName": org_name})
        return r.json() if r.status_code in (200, 201) else None
    except Exception as e:
        logger.error("SDK setup_org: %s", e)
        return None


async def create_document(title: str, classification: str = "", reg_number: str = "", metadata: Dict = None) -> Optional[Dict]:
    try:
        r = await _get_client().post("/api/documents/create", json={
            "title": title, "classification": classification,
            "registrationNumber": reg_number, "metadata": metadata or {},
        })
        return r.json() if r.status_code in (200, 201) else None
    except Exception as e:
        logger.error("SDK create_document: %s", e)
        return None


async def send_document(doc_did: str, recipient_did: str, method: str = "") -> Optional[Dict]:
    try:
        r = await _get_client().post(f"/api/documents/{doc_did}/send",
            json={"recipientDid": recipient_did, "deliveryMethod": method})
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error("SDK send: %s", e)
        return None


async def receive_document(doc_did: str, sender_did: str, local_reg: str = "") -> Optional[Dict]:
    try:
        r = await _get_client().post(f"/api/documents/{doc_did}/receive",
            json={"senderDid": sender_did, "localRegistrationNumber": local_reg})
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error("SDK receive: %s", e)
        return None


async def assign_document(doc_did: str, assignee: str, department: str = "") -> Optional[Dict]:
    try:
        r = await _get_client().post(f"/api/documents/{doc_did}/assign",
            json={"assignee": assignee, "department": department})
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error("SDK assign: %s", e)
        return None


async def decide_document(doc_did: str, decision: str, resolution: str = "") -> Optional[Dict]:
    try:
        r = await _get_client().post(f"/api/documents/{doc_did}/decide",
            json={"decision": decision, "resolution": resolution})
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error("SDK decide: %s", e)
        return None


async def archive_document(doc_did: str, ref: str = "") -> Optional[Dict]:
    try:
        r = await _get_client().post(f"/api/documents/{doc_did}/archive",
            json={"archiveReference": ref})
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error("SDK archive: %s", e)
        return None


async def track_document(doc_did: str) -> Optional[Dict]:
    try:
        r = await _get_client().get(f"/api/documents/{doc_did}/track")
        return r.json() if r.status_code == 200 else None
    except Exception as e:
        logger.error("SDK track: %s", e)
        return None


async def health() -> Dict:
    try:
        r = await _get_client().get("/api/health")
        return r.json() if r.status_code == 200 else {"status": "error"}
    except Exception as e:
        return {"status": "unavailable", "detail": str(e)}
