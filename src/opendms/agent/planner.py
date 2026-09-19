"""The planner: observe → think → act → observe, until done or stopped.

THIS IS THE COMPONENT THAT MAKES OPENDMS AN AGENT. Everything before it
executed a sequence somebody declared in BPMN. This chooses the next action at
runtime from a brokered catalogue, having seen what the previous ones returned.

Three properties are non-negotiable and are enforced in code, not prompt:

  BOUNDED   — max_steps, checked by the interceptor before every action.
              A planner that can loop forever will eventually loop forever.
  GATED     — every chosen action passes through guardrails.check() before it
              executes. Irreversible actions park the run for human approval.
  ACCOUNTABLE — the thought, the alternatives offered and the verdict are
              written to agent_steps BEFORE the action runs, so a run that
              crashes mid-action still explains what it was attempting.

The prompt asks for strict JSON. Models are not reliably obedient about this,
so _parse_decision strips fences and, failing that, halts the run rather than
guessing at intent — an unparseable plan is not a plan.
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from opendms.agent import guardrails, memory
from opendms.agent import tools as tool_broker

PROMPT_VERSION = "planner/v1"

_SYSTEM = """You plan document-handling work for a Latvian public-sector \
document management system (lietvedība).

You work one step at a time. Each turn you see the goal, what you have already \
done, and the tools available. You choose exactly ONE next action, or you \
declare the goal complete.

Rules you must follow:
- Choose only from the listed tools. Never invent a capability name.
- Tools marked IRREVERSIBLE leave the organisation's boundary and cannot be \
undone. A human must approve them. Prefer gathering information first.
- Tools marked "not implemented" will refuse. Do not retry them; work around \
them or report the gap.
- If a tool fails twice for the same reason, stop and report rather than retry.
- Record durable facts you establish in "scratchpad" so later steps can use them.

Answer with STRICT JSON only, no prose, no code fences:
{
  "thought": "why this action, in one or two sentences",
  "action": "capability/name or null when finished",
  "inputs": {},
  "scratchpad": {},
  "done": false,
  "answer": "final summary, only when done is true"
}"""


def _parse_decision(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _render_history(window: dict[str, Any]) -> str:
    parts = []
    if window["earlier"]:
        parts.append("Earlier steps:\n" + "\n".join(window["earlier"]))
    for s in window["recent"]:
        if s["phase"] != "act":
            continue
        parts.append(
            f"[{s['seq']}] thought: {s['thought']}\n"
            f"     action: {s['action']} inputs={json.dumps(s['inputs'], default=str)[:300]}\n"
            f"     result: {s['observation']}"
        )
    return "\n\n".join(parts) if parts else "(nothing done yet)"


async def run_agent(
    run_id: int,
    *,
    max_iterations: Optional[int] = None,
    require_approval_for_irreversible: bool = True,
) -> dict[str, Any]:
    """Drive the loop until done, blocked, or out of budget.

    Returns the terminal run state. Safe to call again after an approval:
    completed steps are already durable, so it resumes rather than restarts.
    """
    from opendms.ai import _complete
    from opendms.connectors.runtime import run_capability

    run = await memory.get_run(run_id)
    if run is None:
        return {"error": f"run {run_id} not found"}
    if run["status"] in ("completed", "failed", "halted"):
        return run

    allowed = run.get("allowed_capabilities") or []
    if isinstance(allowed, str):
        allowed = json.loads(allowed)
    catalogue = tool_broker.catalogue(allowed or None)
    tool_text = tool_broker.describe_for_prompt(catalogue)
    offered = [t["capability"] for t in catalogue]

    ceiling = max_iterations or (run["max_steps"] - run["steps_used"] + 2)

    for _ in range(max(1, ceiling)):
        run = await memory.get_run(run_id)
        if run["steps_used"] >= run["max_steps"]:
            await memory.record_step(run_id, "halt",
                                     guardrail_reason="step budget exhausted")
            await memory.finish_run(run_id, "halted",
                                    halt_reason="step budget exhausted")
            break

        # Interjections claimed before planning, so a correction typed while
        # the loop was mid-flight changes the NEXT decision rather than being
        # noticed after the budget is gone.
        interjections = await memory.take_pending_messages(run_id)
        for msg in interjections:
            await memory.record_step(run_id, "observe",
                                     observation={"user_message": msg})

        window = await memory.recent_window(run_id)
        scratch = run.get("scratchpad") or {}
        if isinstance(scratch, str):
            scratch = json.loads(scratch)

        interject_block = ""
        if interjections:
            interject_block = (
                "OPERATOR INSTRUCTION - this arrived after the last step and "
                "takes priority over your previous plan:\n"
                + "\n".join(f"- {m}" for m in interjections) + "\n\n"
            )

        user_msg = (
            f"GOAL: {run['goal']}\n\n"
            f"{interject_block}"
            f"ESTABLISHED FACTS: {json.dumps(scratch, default=str, ensure_ascii=False)}\n\n"
            f"STEPS USED: {run['steps_used']} of {run['max_steps']}\n\n"
            f"AVAILABLE TOOLS:\n{tool_text}\n\n"
            f"HISTORY:\n{_render_history(window)}\n\n"
            "What is the single next action?"
        )

        started = time.monotonic()
        raw = await _complete(_SYSTEM, user_msg, temperature=0.1, max_tokens=1200)
        latency = int((time.monotonic() - started) * 1000)
        decision = _parse_decision(raw or "")

        if decision is None:
            # Unparseable plan. Halting beats guessing at intent.
            await memory.record_step(run_id, "halt", thought=(raw or "")[:500],
                                     guardrail_reason="planner returned unparseable output",
                                     latency_ms=latency, prompt_version=PROMPT_VERSION)
            await memory.finish_run(run_id, "failed",
                                    halt_reason="planner returned unparseable output")
            break

        if decision.get("scratchpad"):
            await memory.update_scratchpad(run_id, decision["scratchpad"])

        if decision.get("done") or not decision.get("action"):
            await memory.record_step(run_id, "reflect",
                                     thought=decision.get("thought"),
                                     observation={"answer": decision.get("answer")},
                                     latency_ms=latency, prompt_version=PROMPT_VERSION)
            await memory.finish_run(run_id, "completed",
                                    outcome={"answer": decision.get("answer"),
                                             "scratchpad": scratch})
            if decision.get("answer"):
                await memory.add_message(run_id, "agent", decision["answer"])
            break

        capability = str(decision["action"]).strip()
        inputs = decision.get("inputs") or {}
        history = await memory.steps(run_id)

        verdict = guardrails.check(
            capability, inputs, run, history,
            require_approval_for_irreversible=require_approval_for_irreversible,
        )

        # Written BEFORE execution: a crash mid-action still leaves a record of
        # what was attempted and why it was permitted.
        step = await memory.record_step(
            run_id, "act",
            thought=decision.get("thought"),
            offered_capabilities=offered,
            action_capability=capability,
            action_inputs=inputs,
            guardrail_verdict=verdict.decision,
            guardrail_reason=verdict.reason,
            latency_ms=latency,
            prompt_version=PROMPT_VERSION,
        )

        if verdict.decision == guardrails.REQUIRE_APPROVAL:
            await memory.finish_run(run_id, "awaiting_approval",
                                    halt_reason=verdict.reason)
            await memory.add_message(
                run_id, "agent",
                f"I need approval before running {capability}. "
                f"{decision.get('thought') or ''}".strip())
            run = await memory.get_run(run_id)
            run["pending_step_id"] = step["id"]
            return run

        if verdict.decision == guardrails.DENY:
            # The planner is told why and gets to adapt. A denial is feedback,
            # not a crash — except for budget, which is terminal.
            await memory.record_step(
                run_id, "observe",
                observation={"ok": False, "reason": f"blocked: {verdict.reason}"})
            if "budget" in verdict.reason:
                await memory.finish_run(run_id, "halted", halt_reason=verdict.reason)
                break
            continue

        result = await run_capability(capability, inputs,
                                      {"trace_id": run["run_uuid"],
                                       "source": "agent_planner"})
        await memory.record_step(run_id, "observe",
                                 action_capability=capability,
                                 observation=result.as_dict())

    return await memory.get_run(run_id)


async def approve_step(run_id: int, step_id: int, user_id: int) -> dict[str, Any]:
    """Execute a parked irreversible action, then resume the loop.

    Approval executes exactly the action that was recorded — the stored
    capability and inputs, not a re-planned version. Otherwise a human would be
    approving one thing and authorising another.
    """
    from opendms.connectors.runtime import run_capability
    from opendms.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        step = await conn.fetchrow(
            "SELECT * FROM agent_steps WHERE id = $1 AND run_id = $2", step_id, run_id)
        if step is None:
            return {"error": "step not found"}
        if step["guardrail_verdict"] != guardrails.REQUIRE_APPROVAL:
            return {"error": "step is not awaiting approval"}
        if step["approved_at"] is not None:
            return {"error": "step already approved"}
        await conn.execute(
            """UPDATE agent_steps
                 SET approved_by = $2, approved_at = NOW(), guardrail_verdict = 'allow'
               WHERE id = $1""",
            step_id, user_id)
        await conn.execute(
            "UPDATE agent_runs SET steps_used = steps_used + 1, status = 'running' WHERE id = $1",
            run_id)

    run = await memory.get_run(run_id)
    inputs = step["action_inputs"]
    if isinstance(inputs, str):
        inputs = json.loads(inputs)

    result = await run_capability(step["action_capability"], inputs or {},
                                  {"trace_id": run["run_uuid"],
                                   "source": "agent_planner_approved"})
    await memory.record_step(run_id, "observe",
                             action_capability=step["action_capability"],
                             observation=result.as_dict())
    return await run_agent(run_id)


async def reject_step(run_id: int, step_id: int, user_id: int, reason: str = "") -> dict:
    """Refuse a parked action and stop the run."""
    from opendms.database import get_pool

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE agent_steps
                 SET guardrail_verdict = 'deny',
                     guardrail_reason = $3,
                     approved_by = $2, approved_at = NOW()
               WHERE id = $1""",
            step_id, user_id, f"rejected by operator: {reason}"[:2000])
    await memory.finish_run(run_id, "halted",
                            halt_reason=f"operator rejected step {step_id}: {reason}"[:2000])
    return await memory.get_run(run_id)
