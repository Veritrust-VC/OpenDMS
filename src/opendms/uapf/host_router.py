"""
UAPF-IP host router.

Implements the host side of UAPF-IP v0.1:
  - GET  /uapf/host/manifest                     — what this host offers
  - POST /uapf/host/capability/{namespace}/{op}  — dispatch to capability handler
  - POST /uapf/host/audit                        — receive audit events from runtime
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Header

from opendms.config import get_settings
from opendms.uapf.handlers import HANDLERS, ADVERTISED_CAPABILITIES

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/uapf/host", tags=["UAPF Host"])


@router.get("/manifest")
async def get_manifest():
    """
    Host manifest advertising the capabilities this OpenDMS instance offers
    to UAPF runtimes. Sent by the host (in start-session calls) and also
    discoverable by runtimes that probe before dispatch.
    """
    s = get_settings()
    return {
        "hostDid": s.opendms_host_did,
        "hostBaseUrl": s.opendms_host_base_url,
        "profiles": ["uapf-ip-orchestrated"],
        "capabilities": ADVERTISED_CAPABILITIES,
    }


@router.post("/capability/{namespace}/{operation}")
async def dispatch_capability(
    namespace: str,
    operation: str,
    request: Request,
    authorization: Optional[str] = Header(None),
):
    """
    Dispatch an incoming capability invocation to its registered handler.

    Body shape (from the runtime):
      {
        "sessionId": "sess_...",
        "stepId":    "ExtractFacets",
        "input":     {...},
        "guardrails": {...}    -- optional, policy snapshot
      }
    """
    s = get_settings()

    # Optional bearer-token authentication. If a token is configured,
    # require it on every capability call.
    if s.uapf_engine_auth_token:
        expected = f"Bearer {s.uapf_engine_auth_token}"
        if authorization != expected:
            raise HTTPException(401, "unauthorized")

    handler_key = f"{namespace}/{operation}"
    if handler_key not in HANDLERS:
        return _problem(
            status=422,
            type_="https://uapf.dev/errors/capability-not-available",
            title="Capability not available",
            detail=f"OpenDMS does not implement {namespace}.{operation}",
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    handler, _ref = HANDLERS[handler_key]

    ctx = {
        "session_id": body.get("sessionId"),
        "step_id": body.get("stepId"),
        "input": body.get("input"),
        "guardrails": body.get("guardrails"),
    }

    logger.info(
        "UAPF capability invoked: %s.%s session=%s step=%s",
        namespace, operation, ctx["session_id"], ctx["step_id"],
    )

    try:
        result = await handler(ctx)
    except (ValueError, LookupError) as e:
        return _problem(
            status=400,
            type_="https://uapf.dev/errors/invalid-input",
            title="Capability handler rejected input",
            detail=str(e),
        )
    except Exception as e:
        logger.exception("UAPF capability handler failed: %s.%s", namespace, operation)
        return _problem(
            status=500,
            type_="https://uapf.dev/errors/capability-execution-failed",
            title="Capability handler failed",
            detail=str(e),
        )

    # Handlers return {"output": ...} — return as-is for runtime to merge.
    if isinstance(result, dict) and "output" in result:
        return result
    return {"output": result}


@router.post("/audit")
async def receive_audit_event(request: Request):
    """
    Receive audit events emitted by the runtime. Stored in document_events
    (when documentId is present in the event data) for visibility alongside
    OpenDMS's own lifecycle events.
    """
    try:
        event = await request.json()
    except Exception:
        return {"acknowledged": False, "reason": "invalid_json"}

    document_id = None
    data = event.get("data") or {}
    if isinstance(data, dict):
        document_id = data.get("documentId") or data.get("document_id")

    if document_id:
        from opendms.database import get_pool
        try:
            pool = await get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO document_events (document_id, event_type, vc_submitted, details)
                       VALUES ($1, $2, FALSE, $3)""",
                    int(document_id),
                    f"UAPF/{event.get('type','unknown')}",
                    json.dumps(event),
                )
        except Exception as e:
            logger.warning("audit persist failed: %s", e)

    return {"acknowledged": True}


def _problem(status: int, type_: str, title: str, detail: str):
    """RFC 7807 Problem Details — what the UAPF-IP spec expects on errors."""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=status,
        content={"type": type_, "title": title, "status": status, "detail": detail},
    )
