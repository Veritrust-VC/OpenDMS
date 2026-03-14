"""Organization DID/VC viewer endpoints — proxied through SDK sidecar."""

from fastapi import APIRouter, Depends, HTTPException
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user
from opendms import sdk_client

router = APIRouter(prefix="/api/organizations", tags=["Organization Tools"])


@router.get("/{org_id}/did-document")
async def get_org_did_document(org_id: int, user=Depends(get_current_user)):
    """Resolve and return the full DID document for an organization.
    Uses the Registry API (via SDK) instead of Veramo's did:web resolver,
    which can't reach public domains from inside Docker containers."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT id, name, code, org_did FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    if not org["org_did"]:
        raise HTTPException(404, "Organization has no DID assigned")

    result = await sdk_client.resolve_org_from_registry(org["org_did"])
    if not result:
        raise HTTPException(502, "DID resolution failed — SDK unreachable")

    status_code = result.get("_meta", {}).get("status_code", 502)
    if status_code not in (200, 201):
        error = result.get("detail") or result.get("error") or f"HTTP {status_code}"
        raise HTTPException(502, f"Registry resolve failed: {error}")

    return {
        "organization": {"id": org["id"], "name": org["name"], "code": org["code"], "org_did": org["org_did"]},
        "didDocument": result.get("did_document") or result.get("didDocument"),
        "public_key": result.get("public_key_b64"),
        "registration_vc": result.get("registration_vc"),
        "name": result.get("name"),
    }


@router.get("/{org_id}/registration-vc")
async def get_org_registration_vc(org_id: int, user=Depends(get_current_user)):
    """Retrieve the registration VC for an organization."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT id, name, code, org_did FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    if not org["org_did"]:
        raise HTTPException(404, "Organization has no DID assigned")

    registry_result = await sdk_client.resolve_org_from_registry(org["org_did"])
    vc = None
    if registry_result:
        vc = registry_result.get("registration_vc")

    setup = await sdk_client.setup_status(org_did=org["org_did"])
    last_setup = setup.get("last_setup") or {}
    registry_resp = last_setup.get("registry") or {}
    vc_present = setup.get("registration_vc_present", False) or bool(vc)

    return {
        "organization": {"id": org["id"], "name": org["name"], "code": org["code"], "org_did": org["org_did"]},
        "registration_vc_present": vc_present,
        "registration_vc": vc,
        "registry_org_data": {
            "did_document": registry_result.get("did_document") if registry_result else None,
            "name": registry_result.get("name") if registry_result else None,
        } if registry_result else None,
        "last_setup": {
            "timestamp": last_setup.get("timestamp"),
            "lifecycle_ready": last_setup.get("lifecycle_ready"),
            "registry": {
                "connected": registry_resp.get("connected"),
                "authenticated": registry_resp.get("authenticated"),
                "registered": registry_resp.get("registered"),
                "verified": registry_resp.get("verified"),
                "error": registry_resp.get("error"),
            } if registry_resp else None,
        } if last_setup else None,
    }


@router.post("/{org_id}/recover-vc")
async def recover_org_vc(org_id: int, user=Depends(get_current_user)):
    """Try to recover the registration VC for an already-registered org."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT id, name, code, org_did FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    if not org["org_did"]:
        raise HTTPException(404, "Organization has no DID assigned")

    result = await sdk_client.re_register_org(org["org_did"], actor=user)
    if not result:
        raise HTTPException(502, "VC recovery failed — SDK unreachable")

    return {
        "organization": {"id": org["id"], "name": org["name"], "org_did": org["org_did"]},
        "registration_vc": result.get("registration_vc"),
        "registration_vc_source": result.get("registration_vc_source"),
        "message": result.get("message"),
        "resolved": result.get("resolved"),
    }


@router.get("/{org_id}/managed-dids")
async def get_org_managed_dids(org_id: int, user=Depends(get_current_user)):
    """List all managed DIDs from the SDK."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT id, name, code, org_did FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(404, "Organization not found")

    setup = await sdk_client.setup_status(org_did=org.get("org_did"))
    managed_dids = setup.get("managed_dids", [])

    return {
        "organization": {"id": org["id"], "name": org["name"], "org_did": org["org_did"]},
        "managed_dids": managed_dids,
    }
