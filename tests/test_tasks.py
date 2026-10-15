"""User tasks (Mans darbs): deadlines, the work list shape, completing a step."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from opendms import tasks
from opendms.mcp import server, tools

T0 = "2026-10-01T08:00:00+00:00"
START = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)


def test_deadline_from_days_date_hours_and_classification():
    assert tasks.deadline_of({"requestedAt": T0, "proposal": {"termins": 10}}) == START + timedelta(days=10)
    assert tasks.deadline_of({"requestedAt": T0, "proposal": {"termins": "5"}}) == START + timedelta(days=5)
    d = tasks.deadline_of({"requestedAt": T0, "proposal": {"termins": "2026-10-20"}})
    assert (d.year, d.month, d.day) == (2026, 10, 20)
    assert tasks.deadline_of({"requestedAt": T0, "proposal": {"slaHours": 48}}) == START + timedelta(hours=48)
    due = START + timedelta(days=30)
    assert tasks.deadline_of({"requestedAt": T0, "proposal": {}}, due) == due
    assert tasks.deadline_of({"requestedAt": T0, "proposal": {"termins": "nav"}}) is None


class FakeConn:
    def __init__(self, db):
        self.db = db

    async def fetch(self, sql, *a):
        return [self._row(d) for d in self.db["docs"].values()
                if json.loads(d["metadata"]).get("uapf_review", {}).get("status") == "gaida"
                and ("suspended" in sql or True)]

    async def fetchrow(self, sql, *a):
        d = self.db["docs"].get(a[0])
        if not d or json.loads(d["metadata"]).get("uapf_review", {}).get("status") != "gaida":
            return None
        return self._row(d)

    async def fetchval(self, sql, *a):
        if "package_id" in sql:
            return "lv.x.pkg"
        d = self.db["docs"].get(a[0])
        return d["metadata"] if d else None

    async def execute(self, sql, *a):
        self.db["exec"].append((sql.split()[0], a))
        if sql.strip().startswith("UPDATE documents") and "requestedAt" in sql:
            d = self.db["docs"][a[1]]
            m = json.loads(d["metadata"])
            if m.get("uapf_review", {}).get("requestedAt") == a[2]:
                m.update(json.loads(a[0]))
                d["metadata"] = json.dumps(m)
        return "UPDATE 1"

    def _row(self, d):
        return {"id": d["id"], "registration_number": d["reg"], "title": d["title"], "status": "registered",
                "metadata": d["metadata"], "created_at": None, "content_summary": "Kopsavilkums", "package_id": "lv.x.pkg",
                "process_id": "p", "session_state": "suspended", "classification_due": None}


class FakePool:
    def __init__(self, db):
        self.db = db

    def acquire(self):
        pool = self

        class Ctx:
            async def __aenter__(self):
                return FakeConn(pool.db)

            async def __aexit__(self, *e):
                return False
        return Ctx()


def _doc(i, review):
    return {"id": i, "reg": f"T-{i}", "title": f"Dok {i}", "metadata": json.dumps({"uapf_review": review, "sender": "Jānis"})}


@pytest.fixture
def db(monkeypatch):
    db = {"exec": [], "resumed": [], "events": [], "docs": {
        1: _doc(1, {"status": "gaida", "sessionId": "s1", "stepId": "Izskatit", "role": "vaditajs",
                    "requestedAt": T0, "proposal": {"termins": 3}}),
        2: _doc(2, {"status": "gaida", "sessionId": "s2", "stepId": "Registret", "role": "registretajs",
                    "requestedAt": T0, "proposal": {}, "decisions": ["registrets", "nav-musu"]}),
        3: _doc(3, {"status": "apstiprinats", "sessionId": "s3"}),
    }}
    pool = FakePool(db)

    async def gp():
        return pool
    monkeypatch.setattr(tasks, "get_pool", gp)
    monkeypatch.setattr(tasks, "step_names", lambda pid: {"Izskatit": "Izskatīt", "__process__": "Ienākošais"})

    class Client:
        def __init__(self, *a):
            pass

        async def resume_session(self, sid, output):
            db["resumed"].append((sid, output))
            return {"state": "completed", "output": {}}
    import opendms.uapf.client as uc
    monkeypatch.setattr(uc, "UapfClient", Client)
    import opendms.uapf.bridge as br

    async def ev(*a, **k):
        db["events"].append(a)
    monkeypatch.setattr(br, "on_document_event", ev)
    return db


def test_list_sorted_by_deadline_with_step_names_and_decisions(db):
    items = asyncio.run(tasks.list_tasks())
    assert [t["documentId"] for t in items] == [1, 2]          # with deadline first, closed one absent
    t = items[0]
    assert t["stepName"] == "Izskatīt" and t["processName"] == "Ienākošais" and t["role"] == "vaditajs"
    assert t["overdue"] is True and t["sender"] == "Jānis"
    assert [d["id"] for d in t["decisions"]] == ["apstiprinats", "labots", "noraidits"]
    assert [d["id"] for d in items[1]["decisions"]] == ["registrets", "nav-musu"]


def test_complete_validates_and_resumes(db):
    user = {"id": 7, "email": "agent@x.lv"}
    with pytest.raises(tasks.TaskError) as e:
        asyncio.run(tasks.complete(2, "apstiprinats", user=user))
    assert e.value.status == 400
    with pytest.raises(tasks.TaskError) as e:
        asyncio.run(tasks.complete(1, "labots", user=user))
    assert e.value.status == 400
    with pytest.raises(tasks.TaskError) as e:
        asyncio.run(tasks.complete(3, "apstiprinats", user=user))
    assert e.value.status == 409

    res = asyncio.run(tasks.complete(1, "apstiprinats", user=user, via="agent", on_behalf_of="anna@x.lv"))
    assert db["resumed"] == [("s1", {"decision": "apstiprinats", "comment": None, "reviewer": "anna@x.lv"})]
    r = json.loads(db["docs"][1]["metadata"])["uapf_review"]
    assert r["status"] == "apstiprinats" and r["decidedBy"] == "anna@x.lv" and r["recordedBy"] == "agent@x.lv"
    assert db["events"] and db["events"][0][0] == "document.decided"
    assert res["nextTask"] is None


def test_newer_step_written_during_resume_is_kept(db):
    class Client:
        def __init__(self, *a):
            pass

        async def resume_session(self, sid, output):   # the process asks the next person at once
            m = json.loads(db["docs"][1]["metadata"])
            m["uapf_review"] = {"status": "gaida", "sessionId": "s1", "stepId": "Izpildit",
                                "requestedAt": "2026-10-02T08:00:00+00:00", "proposal": {}}
            db["docs"][1]["metadata"] = json.dumps(m)
            return {"state": "suspended"}
    import opendms.uapf.client as uc
    uc.UapfClient = Client
    res = asyncio.run(tasks.complete(1, "apstiprinats", user={"id": 1, "email": "a@x.lv"}))
    assert json.loads(db["docs"][1]["metadata"])["uapf_review"]["stepId"] == "Izpildit"
    assert res["nextTask"]["stepId"] == "Izpildit"


def test_mcp_tools_listed_and_completion_needs_confirmation():
    names = {t["name"] for t in tools.public_tools()}
    assert {"mans_darbs", "uzdevums", "pabeigt_uzdevumu"} <= names
    assert tools.TOOL_INDEX["pabeigt_uzdevumu"]["class"] == tools.WRITE

    async def call(args, scope="full"):
        return await server._dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
             "params": {"name": "pabeigt_uzdevumu", "arguments": args}},
            {"ok": True, "principal": "x", "scope": scope, "user": {"id": 1, "email": "agent@x.lv"}})
    res = asyncio.run(call({"document_id": 1, "decision": "apstiprinats", "person": "a@x.lv", "confirmed": False}))
    assert "not confirmed" in json.loads(res["result"]["content"][0]["text"])["error"]
    res = asyncio.run(call({"document_id": 1, "decision": "apstiprinats", "person": "a@x.lv", "confirmed": True},
                           scope="read"))
    assert res["result"]["isError"] is True


def test_decisions_named_by_the_process_with_labels():
    r = {"decisions": ["nodot-izpildei=Nodot izpildei", "nodot-iepazities=Nodot iepazīties", "apstiprinats"]}
    assert tasks.decisions_of(r) == [("nodot-izpildei", "Nodot izpildei"), ("nodot-iepazities", "Nodot iepazīties"),
                                     ("apstiprinats", "Apstiprināt")]
    assert tasks.decisions_of({})[0] == ("apstiprinats", "Apstiprināt")


def test_process_names_next_event_and_source_package(db):
    import opendms.uapf.client as uc

    class Client:
        def __init__(self, *a):
            pass

        async def resume_session(self, sid, output):
            return {"state": "completed", "output": {"nakamaisNotikums": "document.decided"}}
    uc.UapfClient = Client
    calls = []
    import opendms.uapf.bridge as br

    async def ev(*a, **k):
        calls.append((a, k))
    br.on_document_event = ev
    asyncio.run(tasks.complete(2, "registrets", user={"id": 1, "email": "a@x.lv"}))
    assert calls == [(("document.decided", 2), {"exclude_package": "lv.x.pkg", "source_package": "lv.x.pkg"})]


def test_comment_required_and_draft_edit_only_where_the_step_allows(db):
    db["docs"][4] = _doc(4, {"status": "gaida", "sessionId": "s4", "stepId": "Saskanot", "requestedAt": T0, "proposal": {},
                             "decisions": ["saskanots=Saskaņot", "nesaskanots*=Nesaskaņot"]})
    t = asyncio.run(tasks.get_task(4))
    assert t["decisions"][1] == {"id": "nesaskanots", "label": "Nesaskaņot", "commentRequired": True}
    with pytest.raises(tasks.TaskError) as e:
        asyncio.run(tasks.complete(4, "nesaskanots", user={"id": 1, "email": "a@x.lv"}))
    assert "komentārs" in e.value.message
    with pytest.raises(tasks.TaskError) as e:
        asyncio.run(tasks.complete(4, "saskanots", user={"id": 1, "email": "a@x.lv"}, changes={"projektaTeksts": "x"}))
    assert "labot nevar" in e.value.message


def test_outgoing_capabilities_registered():
    from opendms.uapf.handlers import HANDLERS
    for k in ("document/outgoing", "visa/record", "document/sign", "document/sent"):
        assert k in HANDLERS
    from opendms.outgoing import VISA_OF
    from opendms.archive.marks import VISA_RESULTS
    assert set(VISA_OF.values()) <= set(VISA_RESULTS)
