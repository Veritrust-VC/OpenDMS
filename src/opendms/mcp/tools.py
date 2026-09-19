"""Tools this node exposes to other agents over MCP.

WHAT IS DELIBERATELY NOT HERE: approve and reject.

An external caller must not be able to approve an irreversible action. If it
could, the oversight gate built into the planner would be bypassable by anyone
who can reach this endpoint, and "a human approved it" would stop being true.
Approval stays in the authenticated GUI, tied to a named person. An MCP client
can start work and watch it; only a human can let it out of the boundary.

The read/write split is enforced the same way it is for the planner: a tool
declares its class, and start_agent_run defaults to a read-only capability
allowlist so a remote caller cannot reach the connectors indirectly by asking
the planner to do it.
"""

from __future__ import annotations

import json
from typing import Any

from opendms.database import get_pool

READ = "read"
WRITE = "write"

# Capabilities a remotely-started run may choose from unless a wider scope is
# explicitly granted. Everything here is read-only; nothing leaves the boundary.
_REMOTE_DEFAULT_SCOPE = [
    "document/fetch",
    "ai/extract",
    "connector/email.fetch",
    "connector/sap.lookup-partner",
    "connector/sap.lookup-contract",
    "connector/medus.fetch-nomenclature",
]


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "identify",
        "class": READ,
        "description": "Who this node is, what it may be trusted for, and what it is not. "
                       "Returns the node's DID, its role in the AI LV Exchange, and its "
                       "agent classification.",
        "inputSchema": _schema({}),
    },
    {
        "name": "capability_catalogue",
        "class": READ,
        "description": "The capabilities this node's planner can invoke, each with its "
                       "reversibility class and whether it is implemented.",
        "inputSchema": _schema({}),
    },
    {
        "name": "document_search",
        "class": READ,
        "description": "Search registered documents by title, registration number or status.",
        "inputSchema": _schema({
            "query": {"type": "string", "description": "Free text matched against title and registration number."},
            "status": {"type": "string", "description": "Optional lifecycle status filter."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
        }),
    },
    {
        "name": "document_get",
        "class": READ,
        "description": "One document's registry record, including its lifecycle status and DID.",
        "inputSchema": _schema({"document_id": {"type": "integer"}}, ["document_id"]),
    },
    {
        "name": "classify_document",
        "class": READ,
        "description": "Propose a classification for a document title or summary. Returns a "
                       "PROPOSAL with a confidence value — it is not applied to any record.",
        "inputSchema": _schema({
            "title": {"type": "string"},
            "content_summary": {"type": "string", "default": ""},
        }, ["title"]),
    },
    {
        "name": "start_agent_run",
        "class": WRITE,
        "description": "Ask this node's planner to pursue a goal. Runs with a read-only "
                       "capability scope by default; any irreversible action the planner "
                       "chooses will park for human approval and will NOT execute.",
        "inputSchema": _schema({
            "goal": {"type": "string"},
            "document_id": {"type": "integer"},
            "max_steps": {"type": "integer", "minimum": 1, "maximum": 12, "default": 6},
        }, ["goal"]),
    },
    {
        "name": "agent_run_status",
        "class": READ,
        "description": "Status and full decision log of a run, including the reasoning "
                       "recorded for each step and any action awaiting human approval.",
        "inputSchema": _schema({"run_id": {"type": "integer"}}, ["run_id"]),
    },
]

TOOL_INDEX = {t["name"]: t for t in TOOLS}


def public_tools() -> list[dict[str, Any]]:
    """MCP tools/list payload — the internal 'class' key is not part of the spec."""
    return [{k: v for k, v in t.items() if k != "class"} for t in TOOLS]


# ── implementations ───────────────────────────────────────────

async def _identify(args: dict, ctx: dict) -> dict:
    from opendms.config import get_settings
    from opendms.agent import tools as broker

    s = get_settings()
    cat = broker.catalogue()
    return {
        "node": s.brand_name,
        "software": "OpenDMS",
        "purpose": "Document management and lietvedība process execution for the "
                   "Latvian public sector, executed as Process-as-Code.",
        "organisation_did": ctx.get("org_did"),
        "agent": {
            "has_planner": True,
            "decision_basis": "model inference over a declared tool catalogue",
            "planning_scope": "plans its own action sequence at runtime",
            "oversight": "irreversible actions require named human approval before execution",
            "revocation": "per-connection enable flag; takes effect on the next call",
        },
        "not_this_node": [
            "Not the authoritative document register — the system of record remains "
            "the organisation's own DVS.",
            "Does not issue registration numbers with legal effect.",
            "Does not approve its own irreversible actions, and neither can you.",
        ],
        "capability_count": len(cat),
    }


async def _capability_catalogue(args: dict, ctx: dict) -> dict:
    from opendms.agent import tools as broker
    return {"capabilities": broker.catalogue()}


async def _document_search(args: dict, ctx: dict) -> dict:
    q = (args.get("query") or "").strip()
    status = args.get("status")
    limit = min(int(args.get("limit") or 10), 50)
    pool = await get_pool()
    sql = """SELECT id, registration_number, title, status, doc_did, created_at
               FROM documents WHERE 1=1"""
    params: list[Any] = []
    if q:
        params.append(f"%{q}%")
        sql += f" AND (title ILIKE ${len(params)} OR registration_number ILIKE ${len(params)})"
    if status:
        params.append(status)
        sql += f" AND status = ${len(params)}"
    params.append(limit)
    sql += f" ORDER BY id DESC LIMIT ${len(params)}"
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {"count": len(rows), "documents": [dict(r) for r in rows]}


async def _document_get(args: dict, ctx: dict) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, registration_number, title, status, doc_did, content_summary,
                      semantic_summary, file_name, mime_type, file_size, created_at, updated_at
                 FROM documents WHERE id = $1""",
            int(args["document_id"]))
    if row is None:
        return {"error": "document not found", "document_id": args["document_id"]}
    return dict(row)


async def _classify_document(args: dict, ctx: dict) -> dict:
    from opendms import ai
    if not ai.is_configured():
        return {"error": "no model configured on this node"}
    result = await ai.suggest_classification(args["title"], args.get("content_summary") or "")
    if not result:
        return {"error": "classification unavailable"}
    # Framed as a proposal on purpose: a caller must not mistake this for a
    # decision that has been recorded anywhere.
    return {"proposal": result, "applied": False,
            "note": "Proposal only. Nothing was written to any register."}


async def _start_agent_run(args: dict, ctx: dict) -> dict:
    from opendms import ai
    from opendms.agent import memory, planner

    if not ai.is_configured():
        return {"error": "no model configured on this node"}
    run = await memory.create_run(
        args["goal"],
        document_id=args.get("document_id"),
        max_steps=min(int(args.get("max_steps") or 6), 12),
        allowed_capabilities=_REMOTE_DEFAULT_SCOPE,
        model_ref=ai._cfg().get("model"),
    )
    run = await planner.run_agent(run["id"])
    return {
        "run_id": run["id"],
        "run_uuid": run["run_uuid"],
        "status": run["status"],
        "steps_used": run["steps_used"],
        "scope": _REMOTE_DEFAULT_SCOPE,
        "note": "Started with a read-only capability scope. Any irreversible action "
                "parks for human approval in this node's own interface.",
    }


async def _agent_run_status(args: dict, ctx: dict) -> dict:
    from opendms.agent import memory

    run = await memory.get_run(int(args["run_id"]))
    if run is None:
        return {"error": "run not found"}
    steps = await memory.steps(run["id"])
    def _j(v):
        return json.loads(v) if isinstance(v, str) else v
    return {
        "run_id": run["id"], "goal": run["goal"], "status": run["status"],
        "steps_used": run["steps_used"], "max_steps": run["max_steps"],
        "halt_reason": run["halt_reason"], "outcome": _j(run["outcome"]),
        "scratchpad": _j(run["scratchpad"]),
        "steps": [{
            "seq": s["seq"], "phase": s["phase"], "thought": s["thought"],
            "capability": s["action_capability"], "observation": _j(s["observation"]),
            "guardrail": s["guardrail_verdict"], "guardrail_reason": s["guardrail_reason"],
        } for s in steps],
    }


HANDLERS = {
    "identify": _identify,
    "capability_catalogue": _capability_catalogue,
    "document_search": _document_search,
    "document_get": _document_get,
    "classify_document": _classify_document,
    "start_agent_run": _start_agent_run,
    "agent_run_status": _agent_run_status,
}
