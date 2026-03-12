"""Archive export, system settings, and health endpoints."""

import json, os, io, zipfile
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user, require_role
from opendms.storage import get_storage
from opendms.config import get_settings
from opendms import sdk_client
from opendms.org_context import get_default_org

# ═══════════════════════════════════
# Archive
# ═══════════════════════════════════

archive_router = APIRouter(prefix="/api/archive", tags=["Archive"])


class ArchiveBatchCreate(BaseModel):
    name: str
    document_ids: list[int]
    export_format: str = "zip"


@archive_router.get("/batches")
async def list_batches(user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT ab.*, u.full_name as created_by_name FROM archive_batches ab
               LEFT JOIN users u ON ab.created_by = u.id ORDER BY ab.created_at DESC""")
    return [dict(r) for r in rows]


@archive_router.post("/batches", status_code=201)
async def create_batch(req: ArchiveBatchCreate, user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        batch = await conn.fetchrow(
            """INSERT INTO archive_batches (name, document_count, export_format, created_by)
               VALUES ($1, $2, $3, $4) RETURNING *""",
            req.name, len(req.document_ids), req.export_format, user["id"])
        for doc_id in req.document_ids:
            await conn.execute(
                "INSERT INTO archive_batch_documents (batch_id, document_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                batch["id"], doc_id)
    return dict(batch)


@archive_router.post("/batches/{batch_id}/export")
async def export_batch(batch_id: int, user=Depends(require_role("superadmin", "admin"))):
    """Export archive batch as ZIP with documents + metadata."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        batch = await conn.fetchrow("SELECT * FROM archive_batches WHERE id = $1", batch_id)
        if not batch: raise HTTPException(404, "Batch not found")

        await conn.execute("UPDATE archive_batches SET status = 'exporting' WHERE id = $1", batch_id)

        doc_ids = await conn.fetch(
            "SELECT document_id FROM archive_batch_documents WHERE batch_id = $1", batch_id)
        docs = []
        for row in doc_ids:
            doc = await conn.fetchrow(
                """SELECT d.*, o.name as org_name, r.name as register_name, c.name as classification_name
                   FROM documents d LEFT JOIN organizations o ON d.org_id = o.id
                   LEFT JOIN registers r ON d.register_id = r.id LEFT JOIN classifications c ON d.classification_id = c.id
                   WHERE d.id = $1""", row["document_id"])
            if doc:
                events = await conn.fetch(
                    "SELECT event_type, vc_submitted, details, created_at FROM document_events WHERE document_id = $1 ORDER BY created_at",
                    row["document_id"])
                docs.append({**dict(doc), "events": [dict(e) for e in events]})

    # Build ZIP
    buf = io.BytesIO()
    storage = get_storage()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # Manifest
        manifest = {
            "batch_id": batch_id, "batch_name": batch["name"],
            "exported_at": datetime.utcnow().isoformat(),
            "document_count": len(docs),
            "documents": [],
        }
        for doc in docs:
            meta = {k: (v.isoformat() if isinstance(v, datetime) else v)
                    for k, v in doc.items() if k not in ("events",)}
            meta["metadata"] = json.loads(meta["metadata"]) if isinstance(meta.get("metadata"), str) else meta.get("metadata", {})
            meta["events"] = doc["events"]
            manifest["documents"].append({"id": doc["id"], "title": doc["title"],
                "registration_number": doc["registration_number"], "doc_did": doc["doc_did"]})

            # Document metadata
            zf.writestr(f"documents/{doc['id']}/metadata.json", json.dumps(meta, indent=2, default=str))

            # Document file (if exists)
            if doc.get("storage_key"):
                try:
                    file_data = await storage.get(doc["storage_key"])
                    if file_data:
                        zf.writestr(f"documents/{doc['id']}/{doc['file_name'] or 'document.bin'}", file_data)
                except Exception:
                    pass

        zf.writestr("manifest.json", json.dumps(manifest, indent=2, default=str))

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE archive_batches SET status = 'completed', completed_at = NOW() WHERE id = $1", batch_id)

    from fastapi.responses import Response
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="archive-{batch_id}.zip"'})


# ═══════════════════════════════════
# Settings (superadmin)
# ═══════════════════════════════════

settings_router = APIRouter(prefix="/api/settings", tags=["Settings"])


@settings_router.get("")
async def get_settings_all(user=Depends(require_role("superadmin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM system_settings")
    result = {r["key"]: r["value"] for r in rows}
    # Merge with defaults
    s = get_settings()
    result.setdefault("brand_name", s.brand_name)
    result.setdefault("brand_logo_url", s.brand_logo_url)
    result.setdefault("brand_primary_color", s.brand_primary_color)
    result.setdefault("storage_backend", s.storage_backend)
    result.setdefault("sdk_enabled", str(s.sdk_enabled))
    result.setdefault("sdk_url", s.sdk_url)
    return result


class SettingUpdate(BaseModel):
    key: str
    value: str


@settings_router.put("")
async def update_setting(req: SettingUpdate, user=Depends(require_role("superadmin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO system_settings (key, value, updated_at) VALUES ($1, $2, NOW())
               ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()""",
            req.key, req.value)
    return {"key": req.key, "value": req.value}


@settings_router.get("/branding")
async def get_branding():
    """Public endpoint for frontend branding (no auth required)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM system_settings WHERE key LIKE 'brand_%'")
    result = {r["key"]: r["value"] for r in rows}
    s = get_settings()
    result.setdefault("brand_name", s.brand_name)
    result.setdefault("brand_logo_url", s.brand_logo_url)
    result.setdefault("brand_primary_color", s.brand_primary_color)
    return result


# ═══════════════════════════════════
# Health / Stats
# ═══════════════════════════════════

health_router = APIRouter(tags=["System"])


@health_router.get("/api/health")
async def health():
    s = get_settings()
    db_ok = False
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        pass

    sdk_status = await sdk_client.health() if s.sdk_enabled else {"status": "disabled"}
    default_org = await get_default_org()
    sdk_setup = await sdk_client.setup_status(
        org_did=default_org.get("org_did") if (s.sdk_enabled and default_org) else None
    ) if s.sdk_enabled else {
        "status": "disabled",
        "org_did": None,
        "org_did_configured": False,
        "registry_connected": False,
        "registry_auth_configured": False,
        "registry_authenticated": False,
        "registry_auth_error": None,
    }

    return {
        "status": "ok" if db_ok else "degraded",
        "version": s.app_version,
        "database": "connected" if db_ok else "error",
        "storage_backend": s.storage_backend,
        "sdk": sdk_status,
        "sdk_setup": sdk_setup,
    }


@health_router.get("/api/sdk/setup-status")
async def sdk_setup_status(user=Depends(get_current_user)):
    s = get_settings()
    if not s.sdk_enabled:
        return {
            "status": "disabled",
            "org_did": None,
            "org_did_configured": False,
            "registry_connected": False,
            "registry_auth_configured": False,
            "registry_authenticated": False,
            "registry_auth_error": None,
        }
    default_org = await get_default_org()
    sdk = await sdk_client.setup_status(
        org_did=default_org.get("org_did") if default_org else None
    )
    sdk["org_registration_vc"] = sdk.get("registration_vc_present", False)
    sdk["default_organization"] = default_org
    sdk["selected_organization"] = default_org
    return sdk


@health_router.get("/api/stats")
async def stats(user=Depends(get_current_user)):
    default_org = await get_default_org()
    default_org_id = default_org["id"] if default_org else None

    pool = await get_pool()
    async with pool.acquire() as conn:
        return {
            "users": await conn.fetchval("SELECT COUNT(*) FROM users"),
            "organizations": await conn.fetchval("SELECT COUNT(*) FROM organizations"),
            "documents": await conn.fetchval(
                "SELECT COUNT(*) FROM documents WHERE ($1::BIGINT IS NULL OR org_id = $1)",
                default_org_id,
            ),
            "events": await conn.fetchval(
                """SELECT COUNT(*)
                   FROM document_events e
                   JOIN documents d ON d.id = e.document_id
                   WHERE ($1::BIGINT IS NULL OR d.org_id = $1)""",
                default_org_id,
            ),
            "registers": await conn.fetchval("SELECT COUNT(*) FROM registers"),
            "classifications": await conn.fetchval("SELECT COUNT(*) FROM classifications"),
            "by_status": dict(await conn.fetch(
                "SELECT status, COUNT(*)::int as count FROM documents WHERE ($1::BIGINT IS NULL OR org_id = $1) GROUP BY status",
                default_org_id,
            )),
        }
