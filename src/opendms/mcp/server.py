"""MCP endpoint — JSON-RPC 2.0 over POST /mcp (Streamable HTTP).

This is the node's agent-to-agent surface. Until now OpenDMS consumed MCP and
exposed none, which meant it could not participate in the AI LV Exchange as
anything other than a client.

WHY THIS BEFORE A CHAT UI. A conversational interface built directly against
the planner would be a second, bespoke path into the agent. Building the
machine surface first means the chat becomes a client of the same endpoint every
other caller uses — one authorisation model, one audit trail, one place where
the read/write split is enforced.

AUTHENTICATION, stated plainly: Bearer JWT (the same tokens the GUI uses), or a
single shared node token for machine callers that have no user identity. That
shared token is an interim: the other Cyberfort nodes use OAuth 2.1, and this
should too. Until it does, the node token grants READ TOOLS ONLY — a caller
with no user identity cannot start a run — so the weaker credential also carries
the weaker authority.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from opendms.config import get_settings
from opendms.mcp.tools import HANDLERS, TOOL_INDEX, WRITE, public_tools

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp", tags=["MCP"])

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "opendms", "version": "1.0.0"}

# JSON-RPC error codes
PARSE_ERROR, INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS, INTERNAL = (
    -32700, -32600, -32601, -32602, -32603)


def _err(rpc_id: Any, code: int, message: str, data: Any = None) -> dict:
    e: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        e["data"] = data
    return {"jsonrpc": "2.0", "id": rpc_id, "error": e}


def _ok(rpc_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "result": result}


async def _authenticate(authorization: Optional[str]) -> dict:
    """Return the caller's identity and how much it is trusted.

    Three outcomes: an authenticated user (full tool set), the shared node
    token (read tools only), or anonymous (rejected).
    """
    s = get_settings()
    if not authorization or not authorization.lower().startswith("bearer "):
        return {"ok": False, "reason": "missing bearer token"}
    token = authorization.split(" ", 1)[1].strip()

    node_token = (getattr(s, "mcp_node_token", "") or "").strip()
    if node_token and token == node_token:
        return {"ok": True, "principal": "node-token", "scope": "read", "user": None}

    try:
        from opendms.database import get_pool
        from opendms.middleware.auth import decode_token

        payload = decode_token(token)
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT id, email, role, org_id, is_active FROM users WHERE id = $1",
                int(payload["sub"]))
        if not user or not user["is_active"]:
            return {"ok": False, "reason": "user inactive or not found"}
        return {"ok": True, "principal": user["email"], "scope": "full", "user": dict(user)}
    except Exception as exc:
        return {"ok": False, "reason": f"invalid token: {type(exc).__name__}"}


async def _org_did() -> Optional[str]:
    try:
        from opendms.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT org_did FROM organizations WHERE org_did IS NOT NULL ORDER BY id LIMIT 1")
    except Exception:
        return None


async def _dispatch(body: dict, auth: dict) -> Optional[dict]:
    rpc_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}

    # Notifications carry no id and must not be answered.
    if rpc_id is None and method and method.startswith("notifications/"):
        return None

    if method == "initialize":
        return _ok(rpc_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "OpenDMS document management node. Call identify first to learn what this "
                "node is authoritative for. Classification results are proposals, never "
                "applied records. Irreversible actions always require human approval on "
                "this node and cannot be approved through this interface."
            ),
        })

    if method == "ping":
        return _ok(rpc_id, {})

    if method == "tools/list":
        return _ok(rpc_id, {"tools": public_tools()})

    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        spec = TOOL_INDEX.get(name)
        if spec is None:
            return _err(rpc_id, METHOD_NOT_FOUND, f"unknown tool '{name}'")

        # The weaker credential carries the weaker authority.
        if spec["class"] == WRITE and auth.get("scope") != "full":
            return _ok(rpc_id, {
                "content": [{"type": "text", "text": json.dumps({
                    "error": "this tool requires an authenticated user; the shared node "
                             "token grants read access only",
                }, ensure_ascii=False)}],
                "isError": True,
            })

        ctx = {"principal": auth.get("principal"), "org_did": await _org_did()}
        try:
            result = await HANDLERS[name](args, ctx)
        except KeyError as exc:
            return _err(rpc_id, INVALID_PARAMS, f"missing argument: {exc}")
        except Exception as exc:
            logger.exception("MCP tool %s failed", name)
            return _err(rpc_id, INTERNAL, f"{type(exc).__name__}: {exc}")

        return _ok(rpc_id, {
            "content": [{"type": "text",
                         "text": json.dumps(result, ensure_ascii=False, default=str)}],
            "isError": bool(isinstance(result, dict) and result.get("error")),
        })

    return _err(rpc_id, METHOD_NOT_FOUND, f"unknown method '{method}'")


@router.post("", summary="MCP endpoint (JSON-RPC 2.0)")
@router.post("/", include_in_schema=False)
async def mcp_endpoint(request: Request, authorization: Optional[str] = Header(default=None)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_err(None, PARSE_ERROR, "invalid JSON"), status_code=400)

    auth = await _authenticate(authorization)
    if not auth["ok"]:
        # 401 with WWW-Authenticate so an MCP client knows to present credentials.
        return JSONResponse(
            _err(body.get("id") if isinstance(body, dict) else None, INVALID_REQUEST,
                 f"unauthorised: {auth['reason']}"),
            status_code=401,
            headers={"WWW-Authenticate": 'Bearer realm="opendms-mcp"'},
        )

    # A batch is a JSON array; notifications inside it produce no response.
    if isinstance(body, list):
        out = [r for r in [await _dispatch(b, auth) for b in body] if r is not None]
        return JSONResponse(out) if out else JSONResponse(None, status_code=202)

    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return JSONResponse(_err(None, INVALID_REQUEST, "expected JSON-RPC 2.0"), status_code=400)

    response = await _dispatch(body, auth)
    if response is None:
        return JSONResponse(None, status_code=202)
    return JSONResponse(response)


@router.get("", summary="MCP server metadata")
async def mcp_metadata():
    """Unauthenticated discovery. Names the node and how to authenticate — no
    document data, no tool arguments, nothing that is not already public."""
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "serverInfo": SERVER_INFO,
        "transport": "streamable-http",
        "endpoint": "/mcp",
        "authentication": {
            "scheme": "Bearer",
            "accepts": ["opendms JWT (full access)", "shared node token (read only)"],
            "planned": "OAuth 2.1, to match the other AI LV Exchange nodes",
        },
        "tools": [t["name"] for t in public_tools()],
    }
