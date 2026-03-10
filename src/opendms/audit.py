"""Audit logging helpers for OpenDMS integration actions."""

import json
from typing import Optional
from opendms.database import get_pool


async def log_integration_event(
    *,
    trace_id: Optional[str] = None,
    actor_user_id: Optional[int] = None,
    actor_email: Optional[str] = None,
    actor_role: Optional[str] = None,
    organization_id: Optional[int] = None,
    organization_code: Optional[str] = None,
    organization_did: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_did: Optional[str] = None,
    action: str,
    target_system: str,
    request_method: Optional[str] = None,
    request_path: Optional[str] = None,
    request_payload_summary: Optional[str] = None,
    response_status: Optional[int] = None,
    response_summary: Optional[str] = None,
    success: bool = False,
    error_message: Optional[str] = None,
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO integration_audit_log (
                trace_id, actor_user_id, actor_email, actor_role,
                organization_id, organization_code, organization_did,
                entity_type, entity_id, entity_did, action, target_system,
                request_method, request_path, request_payload_summary,
                response_status, response_summary, success, error_message
            ) VALUES (
                $1, $2, $3, $4,
                $5, $6, $7,
                $8, $9, $10, $11, $12,
                $13, $14, $15,
                $16, $17, $18, $19
            )
            """,
            trace_id, actor_user_id, actor_email, actor_role,
            organization_id, organization_code, organization_did,
            entity_type, entity_id, entity_did, action, target_system,
            request_method, request_path, request_payload_summary,
            response_status, response_summary, success, error_message,
        )


def summarize_payload(payload: Optional[dict]) -> Optional[str]:
    if payload is None:
        return None
    return json.dumps(payload, default=str)[:2000]
