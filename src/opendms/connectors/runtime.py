"""Resolving a connection and running a driver operation.

Sits between the two callers — the REST API and the UAPF capability dispatcher —
so both take the same path: find the enabled connection for a kind, decrypt its
credentials, call the driver, write an audit row, and reflect the outcome back
onto the connection's health fields.

The health write-back is the part worth keeping. A connector that quietly fails
inside a background poll is exactly the silent-outage shape that has bitten this
box before, so every invocation updates status / last_verified_at / last_error,
and the GUI reads those rather than guessing from logs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from opendms.audit import log_integration_event
from opendms.connectors import capability_index, get_driver
from opendms.connectors.base import Result
from opendms.connectors.secrets import get_secret
from opendms.database import get_pool

logger = logging.getLogger(__name__)


async def load_connection(kind: str, *, connection_id: Optional[int] = None) -> Optional[dict]:
    """The enabled connection for a kind, or a specific one by id."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if connection_id is not None:
            row = await conn.fetchrow("SELECT * FROM connections WHERE id = $1", connection_id)
        else:
            row = await conn.fetchrow(
                """SELECT * FROM connections
                   WHERE kind = $1 AND is_enabled = TRUE
                   ORDER BY id LIMIT 1""",
                kind,
            )
    return dict(row) if row else None


async def _set_health(connection_id: int, ok: bool, reason: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE connections
               SET status = $2,
                   last_verified_at = CASE WHEN $3 THEN NOW() ELSE last_verified_at END,
                   last_error = $4
               WHERE id = $1""",
            connection_id,
            "active" if ok else "error",
            ok,
            None if ok else (reason or "")[:2000],
        )


def _config_of(row: dict) -> dict[str, Any]:
    import json

    cfg = row.get("config") or {}
    return json.loads(cfg) if isinstance(cfg, str) else dict(cfg)


async def run(
    kind: str,
    operation: str,
    inputs: dict[str, Any],
    ctx: Optional[dict[str, Any]] = None,
    *,
    connection_id: Optional[int] = None,
    actor: Optional[dict] = None,
) -> Result:
    """Run one driver operation, audited, with health write-back."""
    ctx = ctx or {}
    driver = get_driver(kind)
    if driver is None:
        return Result.fail(f"no driver registered for kind '{kind}'")

    row = await load_connection(kind, connection_id=connection_id)
    if row is None:
        return Result.fail(
            f"no enabled {kind} connection is configured",
            connection_missing=True,
        )

    config = _config_of(row)
    secret = await get_secret(row.get("secret_ref"))

    try:
        result = await driver.invoke(operation, config, secret, inputs, ctx)
    except Exception as exc:  # a driver bug, not a remote failure
        logger.exception("connector %s.%s raised", kind, operation)
        result = Result.fail(f"{type(exc).__name__}: {exc}")

    # Placeholder refusals are an expected state, not a broken connection, so
    # they must not mark a healthy connection as errored.
    if not result.data.get("not_implemented"):
        await _set_health(row["id"], result.ok, result.reason)

    await log_integration_event(
        trace_id=ctx.get("trace_id"),
        actor_user_id=(actor or {}).get("id"),
        actor_email=(actor or {}).get("email"),
        actor_role=(actor or {}).get("role"),
        organization_id=row.get("org_id"),
        entity_type="connection",
        entity_id=str(row["id"]),
        action=f"{kind}.{operation}",
        target_system=kind,
        request_payload_summary=_summarize(inputs),
        response_summary=(result.reason or "ok")[:2000],
        success=result.ok,
        error_message=None if result.ok else (result.reason or "")[:2000],
    )
    return result


async def run_capability(
    capability: str,
    inputs: dict[str, Any],
    ctx: Optional[dict[str, Any]] = None,
) -> Result:
    """Dispatch a UAPF capability ref (e.g. "connector/jira.create-issue")."""
    entry = capability_index().get(capability)
    if entry is None:
        return Result.fail(f"no connector implements capability '{capability}'")
    kind, operation = entry
    return await run(kind, operation, inputs, ctx)


def _summarize(inputs: dict[str, Any]) -> str:
    """Audit-safe rendering of the inputs.

    Attachment bytes are dropped rather than truncated — a base64 blob in an
    audit row is useless and enormous, and message bodies can carry personal
    data straight out of an incoming document into a table nobody expects to
    hold it.
    """
    import json

    redacted: dict[str, Any] = {}
    for k, v in (inputs or {}).items():
        if k in ("attachments", "content_b64", "body"):
            if isinstance(v, list):
                redacted[k] = f"<{len(v)} item(s) omitted>"
            else:
                redacted[k] = "<omitted>"
        else:
            redacted[k] = v
    return json.dumps(redacted, default=str)[:2000]
