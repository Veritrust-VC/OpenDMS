"""Working memory for a planner run.

Two kinds, and the distinction matters.

EPISODIC — the ordered step history in agent_steps. Append-only within a run.
This is what makes the run reconstructible afterwards: not just the actions but
the reasoning offered for each one, the alternatives that were on the table, and
the interceptor's verdict. A declared UAPF package needs none of this because
the sequence is the evidence; a planner composes its sequence at runtime, so the
reasoning IS the evidence.

SCRATCHPAD — a small JSONB dict the planner carries across iterations for facts
it has established ("counterparty resolved to reg 40003286750"). Deliberately
separate from the step log: the log is history and immutable, the scratchpad is
current belief and gets overwritten.

COMPACTION. The loop feeds history back into each prompt, so an unbounded run
would grow its own context until it fails. recent_window() returns the last N
steps in full and collapses everything older into a one-line-per-step digest.
Observations are truncated hard — a mailbox fetch can return megabytes and the
planner only needs to know what came back, not every byte of it.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

from opendms.database import get_pool

# Full detail for the last N steps; older ones collapse to one line each.
_RECENT_FULL = 6
_OBS_CHARS = 1200


def new_run_uuid() -> str:
    return "run_" + uuid.uuid4().hex[:16]


def _loads(value: Any, default: Any) -> Any:
    if value is None:
        return default
    return json.loads(value) if isinstance(value, str) else value


async def create_run(
    goal: str,
    *,
    document_id: Optional[int] = None,
    org_id: Optional[int] = None,
    max_steps: int = 12,
    allowed_capabilities: Optional[list[str]] = None,
    model_ref: Optional[str] = None,
    created_by: Optional[int] = None,
) -> dict:
    run_uuid = new_run_uuid()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO agent_runs
                 (run_uuid, goal, document_id, org_id, max_steps,
                  allowed_capabilities, model_ref, created_by)
               VALUES ($1,$2,$3,$4,$5,$6::jsonb,$7,$8)
               RETURNING *""",
            run_uuid, goal, document_id, org_id, max_steps,
            json.dumps(allowed_capabilities or []), model_ref, created_by,
        )
    return dict(row)


async def get_run(run_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM agent_runs WHERE id = $1", run_id)
    return dict(row) if row else None


async def get_run_by_uuid(run_uuid: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM agent_runs WHERE run_uuid = $1", run_uuid)
    return dict(row) if row else None


async def record_step(
    run_id: int,
    phase: str,
    *,
    thought: Optional[str] = None,
    offered_capabilities: Optional[list[str]] = None,
    action_capability: Optional[str] = None,
    action_inputs: Optional[dict] = None,
    observation: Optional[dict] = None,
    guardrail_verdict: Optional[str] = None,
    guardrail_reason: Optional[str] = None,
    model_ref: Optional[str] = None,
    prompt_version: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> dict:
    """Append one step. seq is allocated inside the transaction.

    steps_used counts ACT steps only. Observation and reflection are
    bookkeeping and must not consume the run's budget, or a chatty planner
    would starve itself before doing anything.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            seq = await conn.fetchval(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM agent_steps WHERE run_id = $1", run_id)
            row = await conn.fetchrow(
                """INSERT INTO agent_steps
                     (run_id, seq, phase, thought, offered_capabilities,
                      action_capability, action_inputs, observation,
                      guardrail_verdict, guardrail_reason, model_ref,
                      prompt_version, latency_ms)
                   VALUES ($1,$2,$3,$4,$5::jsonb,$6,$7::jsonb,$8::jsonb,$9,$10,$11,$12,$13)
                   RETURNING *""",
                run_id, seq, phase, thought,
                json.dumps(offered_capabilities or []),
                action_capability,
                json.dumps(action_inputs or {}),
                json.dumps(observation or {}, default=str),
                guardrail_verdict, guardrail_reason, model_ref,
                prompt_version, latency_ms,
            )
            if phase == "act" and guardrail_verdict == "allow":
                await conn.execute(
                    "UPDATE agent_runs SET steps_used = steps_used + 1 WHERE id = $1", run_id)
    return dict(row)


async def steps(run_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM agent_steps WHERE run_id = $1 ORDER BY seq", run_id)
    return [dict(r) for r in rows]


def _digest(step: dict) -> str:
    """One line for an old step."""
    if step["phase"] != "act":
        return f"[{step['seq']}] {step['phase']}"
    obs = _loads(step.get("observation"), {})
    verdict = "ok" if obs.get("ok") else f"failed: {str(obs.get('reason'))[:80]}"
    return f"[{step['seq']}] {step.get('action_capability')} -> {verdict}"


async def recent_window(run_id: int) -> dict[str, Any]:
    """History shaped for the prompt: old steps digested, recent ones in full."""
    all_steps = await steps(run_id)
    old, recent = all_steps[:-_RECENT_FULL], all_steps[-_RECENT_FULL:]
    detailed = []
    for s in recent:
        obs = _loads(s.get("observation"), {})
        detailed.append({
            "seq": s["seq"],
            "phase": s["phase"],
            "thought": s.get("thought"),
            "action": s.get("action_capability"),
            "inputs": _loads(s.get("action_inputs"), {}),
            "observation": json.dumps(obs, default=str)[:_OBS_CHARS],
            "guardrail": s.get("guardrail_verdict"),
        })
    return {"earlier": [_digest(s) for s in old], "recent": detailed}


async def update_scratchpad(run_id: int, patch: dict[str, Any]) -> dict:
    """Merge facts into the scratchpad. Merge, not replace — a planner that
    overwrites its own notes each turn has no memory at all."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            current = _loads(
                await conn.fetchval("SELECT scratchpad FROM agent_runs WHERE id = $1", run_id), {})
            merged = {**current, **(patch or {})}
            await conn.execute(
                "UPDATE agent_runs SET scratchpad = $2::jsonb WHERE id = $1",
                run_id, json.dumps(merged, default=str))
    return merged


async def finish_run(run_id: int, status: str, *,
                     outcome: Optional[dict] = None,
                     halt_reason: Optional[str] = None) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE agent_runs
                 SET status = $2,
                     outcome = $3::jsonb,
                     halt_reason = $4,
                     completed_at = NOW()
               WHERE id = $1""",
            run_id, status, json.dumps(outcome or {}, default=str), halt_reason)


# ── conversation ──────────────────────────────────────────────

async def add_message(run_id: int, role: str, content: str,
                      author_id: Optional[int] = None,
                      consumed: bool = False) -> dict:
    """Append a conversation turn.

    Agent and system turns are written already-consumed; only user turns need
    to be picked up by the loop, so only they are left pending.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO agent_messages (run_id, role, content, author_id, consumed_at)
               VALUES ($1,$2,$3,$4, CASE WHEN $5 THEN NOW() ELSE NULL END)
               RETURNING *""",
            run_id, role, content, author_id, consumed or role != "user")
    return dict(row)


async def messages(run_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM agent_messages WHERE run_id = $1 ORDER BY id", run_id)
    return [dict(r) for r in rows]


async def take_pending_messages(run_id: int) -> list[str]:
    """Claim any unconsumed user turns and stamp them in one statement.

    Stamped in the same UPDATE that returns them, so two concurrent loop
    iterations cannot both consume the same interjection.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """UPDATE agent_messages SET consumed_at = NOW()
                WHERE run_id = $1 AND role = 'user' AND consumed_at IS NULL
            RETURNING content""",
            run_id)
    return [r["content"] for r in rows]
