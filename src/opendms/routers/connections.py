"""Connections API — configure and exercise external-system connectors.

Admin-only throughout. The one rule that shapes every endpoint here: a
credential goes in and never comes back out. Writes accept secret fields, reads
return only which keys are set. There is deliberately no "reveal" endpoint.
"""

from __future__ import annotations

import json
import secrets as pysecrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as PField

from opendms.connectors import describe_all, get_driver, KINDS
from opendms.connectors.runtime import run
from opendms.connectors.secrets import delete_secret, describe_secret, put_secret
from opendms.database import get_pool
from opendms.middleware.auth import require_role

router = APIRouter(prefix="/api/connections", tags=["Connections"])

_ADMIN = require_role("admin", "superadmin")


class ConnectionCreate(BaseModel):
    kind: str
    name: str
    description: Optional[str] = None
    org_id: Optional[int] = None
    config: dict[str, Any] = PField(default_factory=dict)
    secret: dict[str, Any] = PField(default_factory=dict)
    is_enabled: bool = True


class ConnectionUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    config: Optional[dict[str, Any]] = None
    secret: Optional[dict[str, Any]] = None
    is_enabled: Optional[bool] = None


class InvokeRequest(BaseModel):
    operation: str
    inputs: dict[str, Any] = PField(default_factory=dict)


def _config_of(row: dict) -> dict[str, Any]:
    cfg = row.get("config") or {}
    return json.loads(cfg) if isinstance(cfg, str) else dict(cfg)


async def _serialize(row: dict) -> dict[str, Any]:
    driver = get_driver(row["kind"])
    return {
        "id": row["id"],
        "kind": row["kind"],
        "display_name": driver.DISPLAY_NAME if driver else row["kind"],
        "implemented": bool(driver.IMPLEMENTED) if driver else False,
        "name": row["name"],
        "description": row["description"],
        "org_id": row["org_id"],
        "config": _config_of(row),
        "secret_keys_set": sorted(await describe_secret(row.get("secret_ref"))),
        "is_enabled": row["is_enabled"],
        "status": row["status"],
        "last_verified_at": row["last_verified_at"],
        "last_error": row["last_error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


async def _fetch(connection_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM connections WHERE id = $1", connection_id)
    if not row:
        raise HTTPException(404, "Connection not found")
    return dict(row)


@router.get("/drivers", summary="Catalogue of available connector drivers")
async def list_drivers(user=Depends(_ADMIN)):
    """Every driver, its fields, its operations, and — for the ones that are not
    implemented — exactly what we still need from the counterparty."""
    return {"drivers": describe_all()}


@router.get("", summary="List configured connections")
async def list_connections(kind: Optional[str] = None, user=Depends(_ADMIN)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if kind:
            rows = await conn.fetch(
                "SELECT * FROM connections WHERE kind = $1 ORDER BY kind, name", kind)
        else:
            rows = await conn.fetch("SELECT * FROM connections ORDER BY kind, name")
    return {"items": [await _serialize(dict(r)) for r in rows]}


@router.post("", status_code=201, summary="Create a connection")
async def create_connection(req: ConnectionCreate, user=Depends(_ADMIN)):
    if req.kind not in KINDS:
        raise HTTPException(400, f"Unknown connector kind '{req.kind}'. Known: {', '.join(KINDS)}")
    secret_ref = f"conn:{req.kind}:{pysecrets.token_hex(8)}"
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO connections
                     (kind, name, description, org_id, config, secret_ref, is_enabled, created_by)
                   VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)
                   RETURNING *""",
                req.kind, req.name, req.description, req.org_id,
                json.dumps(req.config), secret_ref, req.is_enabled, user["id"],
            )
        except Exception as exc:
            raise HTTPException(400, f"Unable to create connection: {exc}") from exc
    if req.secret:
        await put_secret(secret_ref, req.secret, user["id"])
    return await _serialize(dict(row))


@router.get("/{connection_id}", summary="One connection")
async def get_connection(connection_id: int, user=Depends(_ADMIN)):
    return await _serialize(await _fetch(connection_id))


@router.patch("/{connection_id}", summary="Update a connection")
async def update_connection(connection_id: int, req: ConnectionUpdate, user=Depends(_ADMIN)):
    row = await _fetch(connection_id)
    pool = await get_pool()

    sets, args = [], []
    for field, value in (("name", req.name), ("description", req.description),
                         ("is_enabled", req.is_enabled)):
        if value is not None:
            args.append(value)
            sets.append(f"{field} = ${len(args)}")
    if req.config is not None:
        # Merge rather than replace, so a GUI form that renders a subset of
        # fields cannot silently erase the ones it did not show.
        merged = {**_config_of(row), **req.config}
        args.append(json.dumps(merged))
        sets.append(f"config = ${len(args)}::jsonb")
    if sets:
        args.append(connection_id)
        async with pool.acquire() as conn:
            await conn.execute(
                f"UPDATE connections SET {', '.join(sets)} WHERE id = ${len(args)}", *args)

    if req.secret:
        # Blank values are dropped by put_secret, so leaving a password field
        # empty in the form keeps the stored one instead of wiping it.
        existing = row.get("secret_ref")
        if not existing:
            existing = f"conn:{row['kind']}:{pysecrets.token_hex(8)}"
            async with pool.acquire() as conn:
                await conn.execute("UPDATE connections SET secret_ref = $2 WHERE id = $1",
                                   connection_id, existing)
        from opendms.connectors.secrets import get_secret
        await put_secret(existing, {**await get_secret(existing), **req.secret}, user["id"])

    return await _serialize(await _fetch(connection_id))


@router.delete("/{connection_id}", summary="Delete a connection and its credentials")
async def delete_connection(connection_id: int, user=Depends(require_role("superadmin"))):
    row = await _fetch(connection_id)
    await delete_secret(row.get("secret_ref"))
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM connections WHERE id = $1", connection_id)
    return {"status": "deleted", "id": connection_id}


@router.post("/{connection_id}/test", summary="Test a connection against the live system")
async def test_connection(connection_id: int, user=Depends(_ADMIN)):
    from opendms.connectors.runtime import _set_health
    from opendms.connectors.secrets import get_secret

    row = await _fetch(connection_id)
    driver = get_driver(row["kind"])
    if driver is None:
        raise HTTPException(400, f"No driver for kind '{row['kind']}'")
    result = await driver.test(_config_of(row), await get_secret(row.get("secret_ref")))
    if not result.data.get("not_implemented"):
        await _set_health(connection_id, result.ok, result.reason)
    return {"connection_id": connection_id, **result.as_dict()}


@router.post("/{connection_id}/invoke", summary="Run one driver operation by hand")
async def invoke_connection(connection_id: int, req: InvokeRequest, user=Depends(_ADMIN)):
    """Manual trigger, for the GUI's per-connector action buttons and for
    verifying a connector before a process is pointed at it."""
    row = await _fetch(connection_id)
    result = await run(row["kind"], req.operation, req.inputs,
                       {"source": "manual"}, connection_id=connection_id, actor=user)
    return {"connection_id": connection_id, "operation": req.operation, **result.as_dict()}
