"""Organization DID/VC viewer endpoints — proxied through SDK sidecar."""

from fastapi import APIRouter, Depends, HTTPException
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user
from opendms import sdk_client

router = APIRouter(prefix="/api/organizations", tags=["Organization Tools"])


@router.get("/{org_id}/did-document")
async def get_org_did_document(org_id: int, user=Depends(get_current_user)):
    """Resolve and return the full DID document for an organization via SDK."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT id, name, code, org_did FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    if not org["org_did"]:
        raise HTTPException(404, "Organization has no DID assigned")

    result = await sdk_client.resolve_did(org["org_did"])
    if not result:
        raise HTTPException(502, "DID resolution failed — SDK unreachable or DID not found")

    return {
        "organization": {"id": org["id"], "name": org["name"], "code": org["code"], "org_did": org["org_did"]},
        "didDocument": result.get("didDocument"),
    }


@router.get("/{org_id}/registration-vc")
async def get_org_registration_vc(org_id: int, user=Depends(get_current_user)):
    """Retrieve the registration VC for an organization from SDK setup state."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT id, name, code, org_did FROM organizations WHERE id = $1", org_id)
    if not org:
        raise HTTPException(404, "Organization not found")
    if not org["org_did"]:
        raise HTTPException(404, "Organization has no DID assigned")

    # The SDK's /api/setup/status returns last_setup which contains the registry response
    # including the registration VC if one was issued during org setup
    setup = await sdk_client.setup_status(org_did=org["org_did"])
    last_setup = setup.get("last_setup") or {}
    registry_resp = last_setup.get("registry") or {}
    vc = registry_resp.get("registration_vc")

    # Also check if the VC is present in the setup status flag
    vc_present = setup.get("registration_vc_present", False)

    return {
        "organization": {"id": org["id"], "name": org["name"], "code": org["code"], "org_did": org["org_did"]},
        "registration_vc_present": vc_present,
        "registration_vc": vc,
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


@router.get("/{org_id}/managed-dids")
async def get_org_managed_dids(org_id: int, user=Depends(get_current_user)):
    """List all managed DIDs from the SDK for this organization context."""
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
