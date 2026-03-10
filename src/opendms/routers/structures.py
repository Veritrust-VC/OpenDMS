"""Organization, Register, and Classification management."""

import json
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user, require_role
from opendms import sdk_client
from opendms.audit import log_integration_event, summarize_payload

# ═══════════════════════════════════
# Organizations
# ═══════════════════════════════════

org_router = APIRouter(prefix="/api/organizations", tags=["Organizations"])


class OrgCreate(BaseModel):
    name: str
    code: str
    description: Optional[str] = None


@org_router.get("")
async def list_orgs(user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM organizations ORDER BY name")
    return [dict(r) for r in rows]


@org_router.post("", status_code=201)
async def create_org(req: OrgCreate, user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO organizations (name, code, description) VALUES ($1, $2, $3) RETURNING *",
            req.name, req.code, req.description)
    return dict(row)


@org_router.post("/{org_id}/register-did")
async def register_org_did(org_id: int, user=Depends(require_role("superadmin", "admin"))):
    """Register organization DID via VeriDocs SDK sidecar."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT * FROM organizations WHERE id = $1", org_id)
    if not org: raise HTTPException(404, "Organization not found")

    org_data = dict(org)
    trace_id = str(uuid.uuid4())
    actor = {"id": user.get("id"), "email": user.get("email"), "role": user.get("role")}
    await log_integration_event(
        trace_id=trace_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        actor_role=user.get("role"),
        organization_id=org_data.get("id"),
        organization_code=org_data.get("code"),
        organization_did=org_data.get("org_did"),
        entity_type="organization",
        entity_id=str(org_id),
        action="opendms.org.register_did.requested",
        target_system="sdk",
        request_method="POST",
        request_path="/api/setup/org",
        request_payload_summary=summarize_payload({"orgCode": org_data["code"], "orgName": org_data["name"]}),
    )

    result = await sdk_client.setup_org(org_data["code"], org_data["name"], org_data.get("description") or "", trace_id=trace_id, actor=actor)
    if not result:
        await log_integration_event(
            trace_id=trace_id,
            actor_user_id=user.get("id"),
            actor_email=user.get("email"),
            actor_role=user.get("role"),
            organization_id=org_data.get("id"),
            organization_code=org_data.get("code"),
            organization_did=org_data.get("org_did"),
            entity_type="organization",
            entity_id=str(org_id),
            action="opendms.org.register_did.completed",
            target_system="sdk",
            request_method="POST",
            request_path="/api/setup/org",
            response_status=502,
            response_summary="SDK setup failed",
            success=False,
            error_message="SDK setup failed",
        )
        raise HTTPException(502, "SDK setup failed")

    trace_id = result.get("trace_id") or trace_id
    setup_status = await sdk_client.setup_status(trace_id=trace_id, actor=actor)
    did = result.get("did")
    did_created = bool(did)
    registry_connected = bool(setup_status.get("registry_connected"))
    registry_authenticated = bool(setup_status.get("registry_authenticated"))
    org_registered_in_registry = bool(setup_status.get("org_registered_in_registry"))
    org_verified_in_registry = bool(setup_status.get("org_verified_in_registry"))
    org_did_configured = bool(setup_status.get("org_did_configured"))
    sdk_org_did = setup_status.get("org_did")
    registry_auth_error = setup_status.get("registry_auth_error")
    is_ready = all([
        registry_connected,
        registry_authenticated,
        org_registered_in_registry,
        org_verified_in_registry,
        org_did_configured,
    ])

    async with pool.acquire() as conn:
        await conn.execute("UPDATE organizations SET org_did = COALESCE($1, org_did) WHERE id = $2", did, org_id)

    await log_integration_event(
        trace_id=trace_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        actor_role=user.get("role"),
        organization_id=org_data.get("id"),
        organization_code=org_data.get("code"),
        organization_did=did or org_data.get("org_did"),
        entity_type="organization",
        entity_id=str(org_id),
        entity_did=did,
        action="opendms.org.register_did.completed",
        target_system="sdk",
        request_method="POST",
        request_path="/api/setup/org",
        response_status=result.get("_meta", {}).get("status_code", 200),
        response_summary=summarize_payload({"sdk_response": result, "sdk_setup": setup_status}),
        success=is_ready,
        error_message=registry_auth_error if not is_ready else None,
    )

    message = "Organization centrally registered and verified." if is_ready else "Organization DID exists locally, central registration is partial."
    return {
        "status": "ready" if is_ready else "partial",
        "trace_id": trace_id,
        "did": did,
        "did_created": did_created,
        "registry_connected": registry_connected,
        "registry_authenticated": registry_authenticated,
        "org_registered_in_registry": org_registered_in_registry,
        "org_verified_in_registry": org_verified_in_registry,
        "org_did_configured": org_did_configured,
        "registry_auth_error": registry_auth_error,
        "sdk_org_did": sdk_org_did,
        "sdk_response": result,
        "sdk_setup_status": setup_status,
        "message": message,
    }


@org_router.get("/{org_id}/did-status")
async def org_did_status(org_id: int, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        org = await conn.fetchrow("SELECT * FROM organizations WHERE id = $1", org_id)
    if not org: raise HTTPException(404, "Organization not found")

    trace_id = str(uuid.uuid4())
    setup_status = await sdk_client.setup_status(trace_id=trace_id, actor=user)
    org_data = dict(org)
    local_did = org_data.get("org_did")
    sdk_org_did = setup_status.get("org_did")
    await log_integration_event(
        trace_id=trace_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        actor_role=user.get("role"),
        organization_id=org_data.get("id"),
        organization_code=org_data.get("code"),
        organization_did=local_did,
        entity_type="organization",
        entity_id=str(org_id),
        entity_did=local_did,
        action="opendms.org.did_status.checked",
        target_system="sdk",
        request_method="GET",
        request_path="/api/setup/status",
        response_status=setup_status.get("_meta", {}).get("status_code", 200),
        response_summary=summarize_payload(setup_status),
        success=bool(setup_status.get("registry_connected")),
    )
    return {
        "trace_id": setup_status.get("trace_id") or trace_id,
        "organization": {
            "id": org["id"],
            "name": org["name"],
            "code": org["code"],
            "org_did": local_did,
        },
        "sdk_setup_status": setup_status,
        "registry_connected": setup_status.get("registry_connected"),
        "registry_authenticated": setup_status.get("registry_authenticated"),
        "org_registered_in_registry": setup_status.get("org_registered_in_registry"),
        "org_verified_in_registry": setup_status.get("org_verified_in_registry"),
        "org_did_configured": setup_status.get("org_did_configured"),
        "registry_auth_error": setup_status.get("registry_auth_error"),
        "matches_local_org_did": bool(local_did and sdk_org_did and local_did == sdk_org_did),
    }


@org_router.get("/{org_id}")
async def get_org(org_id: int, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM organizations WHERE id = $1", org_id)
    if not row: raise HTTPException(404, "Not found")
    return dict(row)


# ═══════════════════════════════════
# Registers (hierarchical document classification structure)
# ═══════════════════════════════════

reg_router = APIRouter(prefix="/api/registers", tags=["Registers"])


class RegisterCreate(BaseModel):
    code: str
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    retention_years: int = 5
    access_level: str = "internal"
    sort_order: int = 0
    metadata: dict = {}


@reg_router.get("")
async def list_registers(flat: bool = False, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM registers WHERE is_active = TRUE ORDER BY sort_order, code")
    items = [dict(r) for r in rows]
    if flat:
        return items
    # Build tree
    return _build_tree(items)


@reg_router.post("", status_code=201)
async def create_register(req: RegisterCreate, user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO registers (code, name, parent_id, description, retention_years, access_level, sort_order, metadata)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *""",
            req.code, req.name, req.parent_id, req.description, req.retention_years,
            req.access_level, req.sort_order, json.dumps(req.metadata))
    return dict(row)


@reg_router.post("/import")
async def import_registers(file: UploadFile = File(...), user=Depends(require_role("superadmin", "admin"))):
    """Import register structure from JSON file."""
    data = json.loads(await file.read())
    items = data if isinstance(data, list) else data.get("registers", [])
    pool = await get_pool()
    imported = 0
    async with pool.acquire() as conn:
        for item in items:
            try:
                await conn.execute(
                    """INSERT INTO registers (code, name, parent_id, description, retention_years, sort_order, metadata)
                       VALUES ($1,$2,$3,$4,$5,$6,$7) ON CONFLICT (code) DO UPDATE
                       SET name=$2, description=$4, retention_years=$5, sort_order=$6""",
                    item["code"], item["name"], item.get("parent_id"),
                    item.get("description"), item.get("retention_years", 5),
                    item.get("sort_order", 0), json.dumps(item.get("metadata", {})))
                imported += 1
            except Exception as e:
                pass  # Skip duplicates
    return {"imported": imported, "total": len(items)}


@reg_router.get("/export")
async def export_registers(user=Depends(require_role("superadmin", "admin"))):
    """Export register structure as JSON."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, name, parent_id, description, retention_years, access_level, sort_order FROM registers WHERE is_active = TRUE ORDER BY sort_order, code")
    return {"registers": [dict(r) for r in rows]}


# ═══════════════════════════════════
# Classifications
# ═══════════════════════════════════

cls_router = APIRouter(prefix="/api/classifications", tags=["Classifications"])


class ClassificationCreate(BaseModel):
    code: str
    name: str
    parent_id: Optional[int] = None
    description: Optional[str] = None
    sort_order: int = 0
    metadata: dict = {}


@cls_router.get("")
async def list_classifications(flat: bool = False, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM classifications WHERE is_active = TRUE ORDER BY sort_order, code")
    items = [dict(r) for r in rows]
    return items if flat else _build_tree(items)


@cls_router.post("", status_code=201)
async def create_classification(req: ClassificationCreate, user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO classifications (code, name, parent_id, description, sort_order, metadata)
               VALUES ($1,$2,$3,$4,$5,$6) RETURNING *""",
            req.code, req.name, req.parent_id, req.description, req.sort_order, json.dumps(req.metadata))
    return dict(row)


@cls_router.post("/import")
async def import_classifications(file: UploadFile = File(...), user=Depends(require_role("superadmin", "admin"))):
    data = json.loads(await file.read())
    items = data if isinstance(data, list) else data.get("classifications", [])
    pool = await get_pool()
    imported = 0
    async with pool.acquire() as conn:
        for item in items:
            try:
                await conn.execute(
                    """INSERT INTO classifications (code, name, parent_id, description, sort_order, metadata)
                       VALUES ($1,$2,$3,$4,$5,$6) ON CONFLICT (code) DO UPDATE SET name=$2, description=$4, sort_order=$5""",
                    item["code"], item["name"], item.get("parent_id"),
                    item.get("description"), item.get("sort_order", 0), json.dumps(item.get("metadata", {})))
                imported += 1
            except Exception:
                pass
    return {"imported": imported, "total": len(items)}


@cls_router.get("/export")
async def export_classifications(user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT code, name, parent_id, description, sort_order FROM classifications WHERE is_active = TRUE ORDER BY sort_order, code")
    return {"classifications": [dict(r) for r in rows]}


# ── Tree builder ──
def _build_tree(items):
    by_id = {i["id"]: {**i, "children": []} for i in items}
    roots = []
    for i in items:
        node = by_id[i["id"]]
        pid = i.get("parent_id")
        if pid and pid in by_id:
            by_id[pid]["children"].append(node)
        else:
            roots.append(node)
    return roots
