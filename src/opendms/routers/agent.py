"""Agent API — start runs, watch them, approve or reject parked actions.

The approval endpoints are the oversight surface. Until now OpenDMS had none:
guardrails arrived at the host router and were ignored, which was tolerable
while nothing could act and stopped being tolerable once connectors landed.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as PField

from opendms.middleware.auth import require_role
from opendms.database import get_pool

router = APIRouter(prefix="/api/agent", tags=["Agent"])

_USER = require_role("user", "admin", "superadmin")
_ADMIN = require_role("admin", "superadmin")


class RunCreate(BaseModel):
    goal: str
    document_id: Optional[int] = None
    org_id: Optional[int] = None
    max_steps: int = PField(default=12, ge=1, le=40)
    allowed_capabilities: list[str] = PField(default_factory=list)
    start: bool = True


class Decision(BaseModel):
    step_id: int
    reason: str = ""


class ChatMessage(BaseModel):
    message: str
    run_id: Optional[int] = None
    document_id: Optional[int] = None
    max_steps: int = PField(default=8, ge=1, le=40)


def _j(v: Any, d: Any):
    return d if v is None else (json.loads(v) if isinstance(v, str) else v)


async def _shape(run: dict) -> dict:
    from opendms.agent import guardrails, memory

    steps = await memory.steps(run["id"])
    pending = next(
        (s for s in steps
         if s["guardrail_verdict"] == "require_approval" and s["approved_at"] is None),
        None,
    )
    msgs = await memory.messages(run["id"])
    return {
        "id": run["id"],
        "run_uuid": run["run_uuid"],
        "messages": [
            {"id": m["id"], "role": m["role"], "content": m["content"],
             "pending": m["consumed_at"] is None, "created_at": m["created_at"]}
            for m in msgs
        ],
        "goal": run["goal"],
        "status": run["status"],
        "document_id": run["document_id"],
        "steps_used": run["steps_used"],
        "max_steps": run["max_steps"],
        "scratchpad": _j(run.get("scratchpad"), {}),
        "outcome": _j(run.get("outcome"), None),
        "halt_reason": run.get("halt_reason"),
        "policy": guardrails.summarize_policy(run),
        "awaiting_approval": None if pending is None else {
            "step_id": pending["id"],
            "seq": pending["seq"],
            "thought": pending["thought"],
            "capability": pending["action_capability"],
            "inputs": _j(pending.get("action_inputs"), {}),
            "reason": pending["guardrail_reason"],
        },
        "steps": [
            {
                "seq": s["seq"],
                "phase": s["phase"],
                "thought": s["thought"],
                "capability": s["action_capability"],
                "inputs": _j(s.get("action_inputs"), {}),
                "observation": _j(s.get("observation"), {}),
                "guardrail": s["guardrail_verdict"],
                "guardrail_reason": s["guardrail_reason"],
                "approved_by": s["approved_by"],
                "latency_ms": s["latency_ms"],
                "created_at": s["created_at"],
            }
            for s in steps
        ],
    }


@router.get("/tools", summary="Tool catalogue the planner may choose from")
async def list_tools(user=Depends(_USER)):
    from opendms.agent import tools

    cat = tools.catalogue()
    return {
        "tools": cat,
        "counts": {
            "read_only": sum(1 for t in cat if t["reversibility"] == "read_only"),
            "reversible": sum(1 for t in cat if t["reversibility"] == "reversible"),
            "irreversible": sum(1 for t in cat if t["reversibility"] == "irreversible"),
        },
    }


@router.post("/runs", status_code=201, summary="Start an agent run")
async def create_run(req: RunCreate, user=Depends(_ADMIN)):
    from opendms.agent import memory, planner
    from opendms import ai

    if not ai.is_configured():
        raise HTTPException(503, "No LLM configured - the planner cannot run")

    run = await memory.create_run(
        req.goal,
        document_id=req.document_id,
        org_id=req.org_id,
        max_steps=req.max_steps,
        allowed_capabilities=req.allowed_capabilities,
        model_ref=ai._cfg().get("model"),
        created_by=user["id"],
    )
    if req.start:
        run = await planner.run_agent(run["id"])
    return await _shape(run)


@router.get("/runs", summary="List agent runs")
async def list_runs(limit: int = 25, user=Depends(_USER)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, run_uuid, goal, status, steps_used, max_steps,
                      halt_reason, created_at, completed_at
                 FROM agent_runs ORDER BY id DESC LIMIT $1""",
            min(limit, 100),
        )
    return {"items": [dict(r) for r in rows]}


@router.get("/runs/{run_id}", summary="One run with its full decision log")
async def get_run(run_id: int, user=Depends(_USER)):
    from opendms.agent import memory

    run = await memory.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    return await _shape(run)


@router.post("/runs/{run_id}/resume", summary="Continue a run")
async def resume_run(run_id: int, user=Depends(_ADMIN)):
    from opendms.agent import memory, planner

    run = await memory.get_run(run_id)
    if run is None:
        raise HTTPException(404, "Run not found")
    if run["status"] == "awaiting_approval":
        raise HTTPException(409, "Run is awaiting approval - approve or reject the step first")
    return await _shape(await planner.run_agent(run_id))


@router.post("/runs/{run_id}/approve", summary="Approve a parked irreversible action")
async def approve(run_id: int, req: Decision, user=Depends(_ADMIN)):
    from opendms.agent import memory, planner

    result = await planner.approve_step(run_id, req.step_id, user["id"])
    if isinstance(result, dict) and result.get("error"):
        raise HTTPException(409, result["error"])
    return await _shape(await memory.get_run(run_id))


@router.post("/runs/{run_id}/reject", summary="Refuse a parked action and stop the run")
async def reject(run_id: int, req: Decision, user=Depends(_ADMIN)):
    from opendms.agent import memory, planner

    await planner.reject_step(run_id, req.step_id, user["id"], req.reason)
    return await _shape(await memory.get_run(run_id))


@router.get("/runs/{run_id}/messages", summary="Conversation turns for a run")
async def get_messages(run_id: int, user=Depends(_USER)):
    from opendms.agent import memory

    return {"messages": [
        {"id": m["id"], "role": m["role"], "content": m["content"],
         "pending": m["consumed_at"] is None, "created_at": m["created_at"]}
        for m in await memory.messages(run_id)
    ]}


@router.post("/chat", summary="Talk to the agent")
async def chat(req: ChatMessage, user=Depends(_ADMIN)):
    """One entry point for three different situations, because from the
    operator's side they are all just "saying something":

      no run          -> the message becomes the goal and a run starts
      run in flight   -> the message is queued as an interjection and the
                         planner picks it up at its next iteration
      run finished    -> the message is a follow-up; the run resumes with a
                         topped-up budget rather than losing its memory

    The third case is the reason follow-ups do not start a fresh run: the
    scratchpad and decision log are the context that make the conversation
    worth having.
    """
    from opendms import ai
    from opendms.agent import memory, planner

    if not ai.is_configured():
        raise HTTPException(503, "No LLM configured - the planner cannot run")

    text = (req.message or "").strip()
    if not text:
        raise HTTPException(400, "Message is empty")

    if req.run_id is None:
        run = await memory.create_run(
            text, document_id=req.document_id, max_steps=req.max_steps,
            model_ref=ai._cfg().get("model"), created_by=user["id"])
        await memory.add_message(run["id"], "user", text, user["id"], consumed=True)
        run = await planner.run_agent(run["id"])
        return await _shape(run)

    run = await memory.get_run(req.run_id)
    if run is None:
        raise HTTPException(404, "Run not found")

    await memory.add_message(run["id"], "user", text, user["id"])

    if run["status"] == "awaiting_approval":
        # Deliberately not resumed: an operator typing while an irreversible
        # action is parked must not have that count as approving it. The
        # message is queued and the gate stays shut.
        return {**await _shape(run),
                "note": "Message queued. The parked action still needs an explicit "
                        "decision - approve or reject it to continue."}

    if run["status"] in ("completed", "halted", "failed"):
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE agent_runs
                     SET status = 'running', max_steps = max_steps + $2,
                         halt_reason = NULL, completed_at = NULL
                   WHERE id = $1""",
                run["id"], req.max_steps)
        run = await memory.get_run(run["id"])

    return await _shape(await planner.run_agent(run["id"]))
