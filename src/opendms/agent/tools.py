"""Tool broker — what the planner is allowed to see and choose from.

Under the declared-process model a capability was invoked by a step someone
wrote, reviewed and signed. Under a planner the SAME capability becomes a tool
the model picked. Identical HTTP call, completely different accountability, so
the broker is where that difference gets made explicit: every tool carries a
reversibility class, and the interceptor keys off it.

FAIL SAFE ON UNKNOWNS. Anything not explicitly classified is treated as
IRREVERSIBLE. A new connector added six months from now is therefore gated by
default rather than silently available to a planner — the alternative fails open,
which for something that can send mail on the organisation's behalf is not an
acceptable default.
"""

from __future__ import annotations

from typing import Any, Optional

READ_ONLY = "read_only"
REVERSIBLE = "reversible"
IRREVERSIBLE = "irreversible"

# Explicit classification. Keyed on the UAPF capability reference.
_REVERSIBILITY: dict[str, str] = {
    # reads
    "document/list": READ_ONLY,
    "document/fetch": READ_ONLY,
    "ai/extract": READ_ONLY,
    "ai/redact": READ_ONLY,
    "connector/email.fetch": READ_ONLY,
    "connector/sap.lookup-partner": READ_ONLY,
    "connector/sap.lookup-contract": READ_ONLY,
    "connector/medus.fetch-nomenclature": READ_ONLY,
    # internal writes: undoable inside our own boundary
    "data/write": REVERSIBLE,
    "event/emit": REVERSIBLE,
    "connector/email.mark-seen": REVERSIBLE,
    "connector/jira.transition": REVERSIBLE,
    "connector/jira.comment": REVERSIBLE,
    # leaves our boundary and cannot be taken back
    "connector/email.send": IRREVERSIBLE,
    "connector/jira.create-issue": IRREVERSIBLE,
    "connector/medus.register-document": IRREVERSIBLE,
    "connector/medus.attach-file": IRREVERSIBLE,
}


def reversibility(capability: str) -> str:
    return _REVERSIBILITY.get(capability, IRREVERSIBLE)


def catalogue(allowed: Optional[list[str]] = None) -> list[dict[str, Any]]:
    """Tools on offer this run, derived from the live host manifest.

    Built from HANDLERS rather than a separate list, so a capability that
    exists is either offered or explicitly excluded — it cannot be silently
    forgotten. Placeholder connectors ARE offered: the planner needs to learn
    from the refusal that SAP is unavailable, instead of hallucinating a
    lookup that never happened.
    """
    from opendms.uapf.handlers import HANDLERS

    tools: list[dict[str, Any]] = []
    for key, (_fn, ref) in HANDLERS.items():
        if allowed and key not in allowed:
            continue
        meta = ref if isinstance(ref, dict) else {}
        tools.append({
            "capability": key,
            "summary": meta.get("summary") or "",
            "reversibility": reversibility(key),
            "implemented": meta.get("implemented", True),
        })
    return sorted(tools, key=lambda t: t["capability"])


def describe_for_prompt(tools: list[dict[str, Any]]) -> str:
    """Render the catalogue for the planner prompt.

    The reversibility marker is shown deliberately: a planner told which
    actions cannot be undone makes visibly more conservative choices than one
    handed an undifferentiated tool list.
    """
    lines = []
    for t in tools:
        mark = {READ_ONLY: "read", REVERSIBLE: "undoable", IRREVERSIBLE: "IRREVERSIBLE"}[
            t["reversibility"]]
        note = "" if t["implemented"] else "  (not implemented - will refuse)"
        lines.append(f"- {t['capability']}  [{mark}]  {t['summary']}{note}")
    return "\n".join(lines)


async def execute(capability: str, inputs: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Run a tool the planner chose and return a uniform observation.

    Built-in host capabilities (document/*, ai/*, ...) and connector
    capabilities are both in HANDLERS, so one dispatch covers both. The
    connector runtime alone only knows connectors: routing everything through
    it made every built-in tool fail with "no connector implements ...".

    The observation always carries "ok". A failure is an observation with
    ok=false and a reason, never an empty result, so the planner cannot mistake
    "could not check" for "nothing there".
    """
    from opendms.uapf.handlers import HANDLERS

    entry = HANDLERS.get(capability)
    if entry is None:
        return {"ok": False, "reason": f"unknown capability '{capability}'"}
    fn, _ref = entry
    try:
        out = await fn({"input": inputs or {}, "session_id": ctx.get("trace_id"),
                        "step_id": ctx.get("step_id"), "source": ctx.get("source")})
    except Exception as exc:  # the planner gets the reason and can adapt
        return {"ok": False, "reason": f"{exc.__class__.__name__}: {exc}"}
    output = out.get("output", out) if isinstance(out, dict) else {"value": out}
    if isinstance(output, dict) and "ok" in output:
        return output
    return {"ok": True, **(output if isinstance(output, dict) else {"value": output})}
