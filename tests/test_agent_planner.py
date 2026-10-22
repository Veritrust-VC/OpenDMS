"""Agent planner: what the model sees, and how tools are executed."""

import asyncio
import json

from opendms.agent import planner, tools


def _step(seq, phase, action=None, obs=None, thought=None):
    return {"seq": seq, "phase": phase, "thought": thought, "action": action, "inputs": {},
            "observation": json.dumps(obs or {}), "guardrail": None}


def test_history_shows_the_result_of_each_action():
    # The run that answered "nothing new" while the e-mail fetch had failed.
    window = {"earlier": [], "recent": [
        _step(1, "act", "connector/email.fetch", thought="check e-mail"),
        _step(2, "observe", "connector/email.fetch",
              {"ok": False, "reason": "no enabled email_imap connection is configured"}),
    ]}
    text = planner._render_history(window)
    assert "no enabled email_imap connection is configured" in text
    assert "result: {}" not in text


def test_history_shows_operator_messages_and_refusals():
    window = {"earlier": [], "recent": [
        _step(1, "act", "connector/email.send"),
        _step(2, "observe", None, {"ok": False, "reason": "blocked: needs approval"}),
        _step(3, "observe", None, {"user_message": "check documents instead"}),
    ]}
    text = planner._render_history(window)
    assert "blocked: needs approval" in text and "check documents instead" in text


def test_prompt_forbids_reporting_failures_as_nothing_found():
    assert '"ok": false means the check FAILED' in planner._SYSTEM
    assert planner.PROMPT_VERSION == "planner/v2"


def test_execute_runs_builtin_tools_and_reports_failures(monkeypatch):
    from opendms.uapf import handlers

    async def ok(ctx):
        return {"output": {"total": 2, "seen": ctx["input"]}}

    async def boom(ctx):
        raise LookupError("Document not found")

    async def connector(ctx):
        return {"output": {"ok": False, "reason": "no connection"}}

    monkeypatch.setitem(handlers.HANDLERS, "t/ok", (ok, {}))
    monkeypatch.setitem(handlers.HANDLERS, "t/boom", (boom, {}))
    monkeypatch.setitem(handlers.HANDLERS, "t/conn", (connector, {}))
    run = lambda cap: asyncio.run(tools.execute(cap, {"limit": 3}, {"trace_id": "x"}))

    assert run("t/ok") == {"ok": True, "total": 2, "seen": {"limit": 3}}
    assert run("t/boom") == {"ok": False, "reason": "LookupError: Document not found"}
    assert run("t/conn") == {"ok": False, "reason": "no connection"}
    assert run("t/missing")["ok"] is False


def test_document_list_is_offered_read_only():
    cat = {t["capability"]: t for t in tools.catalogue()}
    assert cat["document/list"]["reversibility"] == tools.READ_ONLY
    assert "recent documents" in cat["document/list"]["summary"]
