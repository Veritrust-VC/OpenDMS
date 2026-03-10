"""Audit log APIs for OpenDMS local and SDK-proxied logs."""

from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user
from opendms import sdk_client

router = APIRouter(prefix="/api/audit", tags=["Audit"])


@router.get("/logs")
async def get_local_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    success: Optional[bool] = None,
    trace_id: Optional[str] = None,
    organization_id: Optional[int] = None,
    user=Depends(get_current_user),
):
    pool = await get_pool()
    wheres = []
    params = []
    idx = 1
    for field, value in (("action", action), ("success", success), ("trace_id", trace_id), ("organization_id", organization_id)):
        if value is not None:
            wheres.append(f"{field} = ${idx}")
            params.append(value)
            idx += 1
    where = f"WHERE {' AND '.join(wheres)}" if wheres else ""
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM integration_audit_log {where}", *params)
        rows = await conn.fetch(
            f"""
            SELECT * FROM integration_audit_log
            {where}
            ORDER BY created_at DESC
            LIMIT ${idx} OFFSET ${idx+1}
            """,
            *params, limit, offset,
        )
    return {"items": [dict(r) for r in rows], "total": total, "limit": limit, "offset": offset}


@router.get("/logs/{log_id}")
async def get_local_log(log_id: int, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM integration_audit_log WHERE id = $1", log_id)
    if not row:
        raise HTTPException(404, "Audit log not found")
    return dict(row)


@router.get("/sdk-logs")
async def get_sdk_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user=Depends(get_current_user),
):
    logs = await sdk_client.get_audit_logs(limit=limit, offset=offset, actor=user)
    if logs is None:
        raise HTTPException(502, "SDK audit logs unavailable")
    return logs


@router.get("/sdk-logs/{log_id}")
async def get_sdk_log(log_id: int, user=Depends(get_current_user)):
    log = await sdk_client.get_audit_log_by_id(log_id, actor=user)
    if log is None:
        raise HTTPException(502, "SDK audit log unavailable")
    return log


@router.get("/summary")
async def get_audit_summary(user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval("SELECT COUNT(*) FROM integration_audit_log")
        failures = await conn.fetchval("SELECT COUNT(*) FROM integration_audit_log WHERE success = FALSE")
        auth_failures = await conn.fetchval("SELECT COUNT(*) FROM integration_audit_log WHERE error_message ILIKE '%auth%'")
        org_sync_failures = await conn.fetchval("SELECT COUNT(*) FROM integration_audit_log WHERE action LIKE 'opendms.org.%' AND success = FALSE")
        doc_sync_failures = await conn.fetchval("SELECT COUNT(*) FROM integration_audit_log WHERE action LIKE 'opendms.doc.%' AND success = FALSE")

    sdk_logs = await sdk_client.get_audit_logs(limit=1, offset=0, actor=user)
    sdk_total = 0
    if sdk_logs and isinstance(sdk_logs, dict):
        sdk_total = sdk_logs.get("total") or len(sdk_logs.get("items", []))

    return {
        "opendms_actions": total,
        "sdk_remote_sync_calls": sdk_total,
        "failures": failures,
        "auth_failures": auth_failures,
        "org_sync_failures": org_sync_failures,
        "doc_sync_failures": doc_sync_failures,
    }
