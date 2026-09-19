"""The interceptor: sits between the planner's choice and its execution.

WHY IT HAS TO BE HERE. Under a declared process, guardrails validate the
package before it runs — static, upstream, outside the agent. That works
because the sequence is known in advance. A planner composes its sequence at
runtime, so upstream validation is validating a plan that does not exist yet.
The check must therefore happen per action, in the loop, in front of the
effectors. This is the component that makes adding a planner safe rather than
merely possible.

Three verdicts: allow, deny (planner is told and continues), require_approval
(the whole run parks until a human decides). Approval is not advisory — the
action does not execute.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Optional

from opendms.agent import tools as tool_broker

ALLOW = "allow"
DENY = "deny"
REQUIRE_APPROVAL = "require_approval"

# How many identical actions before we call it a loop. Three is enough to
# distinguish a deliberate retry from a planner stuck in a cycle.
_LOOP_THRESHOLD = 3


@dataclass
class Verdict:
    decision: str
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.decision != ALLOW


def _fingerprint(capability: str, inputs: dict[str, Any]) -> str:
    payload = json.dumps({"c": capability, "i": inputs}, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def check(
    capability: str,
    inputs: dict[str, Any],
    run: dict,
    history: list[dict],
    *,
    require_approval_for_irreversible: bool = True,
) -> Verdict:
    """Decide whether this action may execute. Ordered cheapest-first."""

    # 1. Budget. Checked before anything else so an exhausted run cannot be
    #    talked into one more action by a persuasive thought.
    if run["steps_used"] >= run["max_steps"]:
        return Verdict(DENY, f"step budget exhausted ({run['max_steps']})")

    # 2. Is it a real capability at all?
    from opendms.uapf.handlers import HANDLERS

    if capability not in HANDLERS:
        return Verdict(DENY, f"unknown capability '{capability}'")

    # 3. Run-scoped allowlist. Empty means "everything in the catalogue".
    allowed = run.get("allowed_capabilities") or []
    if isinstance(allowed, str):
        allowed = json.loads(allowed)
    if allowed and capability not in allowed:
        return Verdict(DENY, f"'{capability}' is outside this run's authority scope")

    # 4. Loop detection. A planner repeating an identical call is not making
    #    progress, and each repeat costs budget and possibly real side effects.
    fp = _fingerprint(capability, inputs)
    repeats = sum(
        1 for h in history
        if h.get("action_capability") == capability
        and _fingerprint(capability, h.get("action_inputs") or {}) == fp
    )
    if repeats >= _LOOP_THRESHOLD:
        return Verdict(DENY, f"identical action attempted {repeats}x - loop detected")

    # 5. Reversibility. The substantive control: anything that leaves our
    #    boundary and cannot be retracted needs a human before it happens.
    rev = tool_broker.reversibility(capability)
    if rev == tool_broker.IRREVERSIBLE and require_approval_for_irreversible:
        return Verdict(
            REQUIRE_APPROVAL,
            f"'{capability}' has irreversible external effect and requires approval",
        )

    return Verdict(ALLOW)


def summarize_policy(run: dict) -> dict[str, Any]:
    """Human-readable statement of what this run may do — for the GUI and for
    the register record's oversight_mode field."""
    allowed = run.get("allowed_capabilities") or []
    if isinstance(allowed, str):
        allowed = json.loads(allowed)
    return {
        "max_steps": run["max_steps"],
        "steps_used": run["steps_used"],
        "authority_scope": allowed or "full catalogue",
        "irreversible_actions": "require human approval",
        "loop_threshold": _LOOP_THRESHOLD,
    }
