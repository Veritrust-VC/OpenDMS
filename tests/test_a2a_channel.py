"""A2A intake: a document from another institution's agent goes through ingest like any channel;
the caller comes from the agent runtime, a task is one document, and a peer sees only its own."""

import asyncio
import base64

import pytest

from opendms.intake import a2a_channel
from opendms.mcp import tools


def test_tools_listed_with_their_class():
    assert tools.TOOL_INDEX["pienemt_dokumentu_a2a"]["class"] == tools.WRITE
    assert tools.TOOL_INDEX["dokumenta_statuss_a2a"]["class"] == tools.READ
    req = tools.TOOL_INDEX["pienemt_dokumentu_a2a"]["inputSchema"]["required"]
    assert "a2a_zvanitajs" in req and "a2a_uzdevums" in req


def _patch(monkeypatch, dublikats=False):
    got = {}

    async def ingest(channel, **k):
        got.update(channel=channel, **k)
        r = {"documentId": 91, "registrationNumber": "1-00091"}
        return {**r, "dublikats": True} if dublikats else r

    async def status(doc_id):
        return {"registracijasNr": "1-00091", "izsekosanasKods": "ab12cd34", "izsekosanasSaite": None}
    import opendms.intake.service as svc
    monkeypatch.setattr(svc, "ingest", ingest)
    monkeypatch.setattr(svc, "status", status)

    class Conn:
        async def execute(self, *a):
            got.setdefault("sql", []).append(a[0])

    class Acq:
        async def __aenter__(self): return Conn()
        async def __aexit__(self, *a): return False

    class Pool:
        def acquire(self): return Acq()

    async def get_pool():
        return Pool()
    import opendms.database as db
    monkeypatch.setattr(db, "get_pool", get_pool)
    return got


def test_receive_goes_through_intake_with_caller_from_runtime(monkeypatch):
    got = _patch(monkeypatch)
    r = asyncio.run(a2a_channel.receive({
        "a2a_zvanitajs": "VARAM Lietvedības aģents", "a2a_uzdevums": "task-1",
        "fields": {"temats": "Iesniegums par piekritību", "sutitajaOrganizacija": "VARAM", "kopsavilkums": "Pārsūtīts."},
        "text": "Iesnieguma teksts."}))
    assert r["registracijasNr"] == "1-00091" and r["jauASanemts"] is False
    assert got["channel"]["veids"] == "a2a" and got["channel"]["apstiprinajums"]["ieslegts"] is False
    assert got["external_ref"] == "a2a-task-1"
    assert got["sender"] == {"name": "VARAM Lietvedības aģents", "organization": "VARAM"}
    assert got["extra"]["a2a"] == {"zvanitajs": "VARAM Lietvedības aģents", "uzdevums": "task-1", "iestade": "VARAM"}
    assert got["body"] == "Iesnieguma teksts." and got["attachments"] == []


def test_receive_takes_a_file(monkeypatch):
    got = _patch(monkeypatch)
    asyncio.run(a2a_channel.receive({
        "a2a_zvanitajs": "X", "a2a_uzdevums": "t2", "fields": {"temats": "Dokuments"},
        "file_name": "iesniegums.odt", "mime_type": "application/vnd.oasis.opendocument.text",
        "file_b64": base64.b64encode(b"PK-odt").decode()}))
    assert got["attachments"][0]["data"] == b"PK-odt" and got["attachments"][0]["file_name"] == "iesniegums.odt"


def test_same_task_twice_is_one_document(monkeypatch):
    _patch(monkeypatch, dublikats=True)
    r = asyncio.run(a2a_channel.receive({"a2a_zvanitajs": "X", "a2a_uzdevums": "t1",
                                         "fields": {"temats": "T"}, "text": "x"}))
    assert r["jauASanemts"] is True


@pytest.mark.parametrize("args,msg", [
    ({"fields": {"temats": "T"}, "text": "x"}, "A2A uzdevumā"),
    ({"a2a_zvanitajs": "X", "a2a_uzdevums": "t", "fields": {}, "text": "x"}, "tematu"),
    ({"a2a_zvanitajs": "X", "a2a_uzdevums": "t", "fields": {"temats": "T"}}, "datni vai"),
])
def test_receive_refuses_incomplete(monkeypatch, args, msg):
    _patch(monkeypatch)
    with pytest.raises(ValueError, match=msg):
        asyncio.run(a2a_channel.receive(args))


def test_status_shows_only_own_documents(monkeypatch):
    seen = {}

    class Conn:
        async def fetchrow(self, sql, nr, caller):
            seen.update(sql=sql, nr=nr, caller=caller)
            return None

    class Acq:
        async def __aenter__(self): return Conn()
        async def __aexit__(self, *a): return False

    class Pool:
        def acquire(self): return Acq()

    async def get_pool():
        return Pool()
    import opendms.database as db
    monkeypatch.setattr(db, "get_pool", get_pool)
    r = asyncio.run(a2a_channel.status_for({"a2a_zvanitajs": "Svešs aģents", "registracijas_numurs": "1-00091"}))
    assert r["atrasts"] is False
    assert seen["caller"] == "Svešs aģents" and "zvanitajs" in seen["sql"]
