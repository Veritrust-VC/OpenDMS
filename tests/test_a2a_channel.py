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
    assert got["extra"]["a2a"] == {"zvanitajs": "VARAM Lietvedības aģents", "uzdevums": "task-1", "iestade": "VARAM",
                                   "zvanitajaDid": None}
    assert got["register_did"] is None   # no identity sent: a new register record
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


def test_outbound_tools_need_the_agent_user():
    assert tools.TOOL_INDEX["a2a_izsutamais_dokuments"]["class"] == tools.WRITE
    assert tools.TOOL_INDEX["a2a_atzimet_nosutitu"]["class"] == tools.WRITE


def _out_pool(monkeypatch, doc, file_row=None, data=b""):
    seen = {"exec": []}

    class Conn:
        async def fetchrow(self, sql, *a):
            if "FROM documents" in sql:
                seen["find"] = a
                return doc
            return file_row

        async def execute(self, sql, *a):
            seen["exec"].append((sql, a))

    class Acq:
        async def __aenter__(self): return Conn()
        async def __aexit__(self, *a): return False

    class Pool:
        def acquire(self): return Acq()

    async def get_pool():
        return Pool()
    import opendms.database as db
    monkeypatch.setattr(db, "get_pool", get_pool)

    class St:
        async def get(self, key):
            seen["key"] = key
            return data
    import opendms.storage as storage
    monkeypatch.setattr(storage, "get_storage", lambda: St())
    return seen


def test_outgoing_gives_file_and_metadata(monkeypatch):
    import datetime
    from opendms import a2a_out
    doc = {"id": 55, "registration_number": "2026/0038", "title": "Iesniegums", "status": "registered",
           "metadata": {"dokumentaVeids": "Iesniegums"}, "content_summary": "Īsi.",
           "created_at": datetime.datetime(2026, 10, 20, 18, 40)}
    seen = _out_pool(monkeypatch, doc, {"file_name": "a.odt", "mime_type": "application/vnd.oasis.opendocument.text",
                                        "file_size": 3, "storage_key": "k1"}, b"odt")
    r = asyncio.run(a2a_out.outgoing({"registracijas_numurs": "2026/0038"}))
    assert seen["find"] == ("2026/0038",) and seen["key"] == "k1"
    assert base64.b64decode(r["file_b64"]) == b"odt" and r["file_name"] == "a.odt"
    assert r["temats"] == "Iesniegums" and r["dokumentaDatums"] == "2026-10-20"


def test_record_sent_once_per_task(monkeypatch):
    from opendms import a2a_out
    doc = {"id": 55, "registration_number": "2026/0038", "title": "T", "status": "registered",
           "metadata": {}, "content_summary": None, "created_at": None}
    seen = _out_pool(monkeypatch, doc)
    r = asyncio.run(a2a_out.record_sent({"registracijas_numurs": "2026/0038", "adresats": "VARAM Lietvedības aģents",
                                         "adresata_reg_nr": "1-00007", "a2a_uzdevums": "t9"}, {"id": 3}))
    assert r["atzimets"] and not r["jauAtzimets"]
    sqls = " ".join(s for s, _ in seen["exec"])
    assert "nosutisana" in sqls and "AtzimetsNosutits" in sqls and "status" not in sqls.split("SET")[1].split("WHERE")[0]
    doc["metadata"] = {"nosutisana": [{"uzdevums": "t9"}]}
    seen = _out_pool(monkeypatch, doc)
    r = asyncio.run(a2a_out.record_sent({"document_id": 55, "adresats": "X", "a2a_uzdevums": "t9"}, {"id": 3}))
    assert r["jauAtzimets"] and seen["exec"] == []


def _reg_patch(monkeypatch, ok=True):
    calls = []

    async def receive_document(did, sender_did, local_reg="", **k):
        calls.append((did, sender_did, local_reg))
        return {"_meta": {"status_code": 200 if ok else 403}, **({} if ok else {"detail": "nav adresāts"})}
    import opendms.sdk_client as sdk
    monkeypatch.setattr(sdk, "receive_document", receive_document)

    class S:
        sdk_enabled = True
    import opendms.config as cfg
    monkeypatch.setattr(cfg, "get_settings", lambda: S())
    return calls


IDENT = {"DokumentaID": "LV-DOK:05-0000:2026:01a1", "RegistraDID": "did:web:dokregistrs.x:doc:3e35",
         "SutitajaDID": "did:web:ombud.x", "SutitajaRegNr": "2026/0038"}


def test_receive_continues_the_senders_register_document(monkeypatch):
    got = _patch(monkeypatch)
    calls = _reg_patch(monkeypatch)
    r = asyncio.run(a2a_channel.receive({"a2a_zvanitajs": "TB aģents", "a2a_uzdevums": "t5", "a2a_zvanitaja_did": "did:web:ombud.x",
                                         "a2a_identitate": IDENT, "fields": {"temats": "T"}, "text": "x"}))
    assert calls == [("did:web:dokregistrs.x:doc:3e35", "did:web:ombud.x", "a2a-t5")]
    assert got["register_did"] == IDENT["RegistraDID"] and got["received_vc"] is True and got["doc_uid"] == IDENT["DokumentaID"]
    assert got["extra"]["sutitajaAtsauce"] == "2026/0038"
    assert r["centralaisRegistrs"].startswith("tas pats")


def test_receive_ignores_identity_not_matching_the_token(monkeypatch):
    got = _patch(monkeypatch)
    calls = _reg_patch(monkeypatch)
    asyncio.run(a2a_channel.receive({"a2a_zvanitajs": "TB aģents", "a2a_uzdevums": "t6", "a2a_zvanitaja_did": "did:web:cits.x",
                                     "a2a_identitate": IDENT, "fields": {"temats": "T"}, "text": "x"}))
    assert calls == [] and got["register_did"] is None and got["doc_uid"] is None
    assert "neatbilst" in got["extra"]["centralaisRegistrs"]["iemesls"]


def test_register_refusal_falls_back_to_a_new_record(monkeypatch):
    got = _patch(monkeypatch)
    _reg_patch(monkeypatch, ok=False)
    asyncio.run(a2a_channel.receive({"a2a_zvanitajs": "TB aģents", "a2a_uzdevums": "t7", "a2a_zvanitaja_did": "did:web:ombud.x",
                                     "a2a_identitate": IDENT, "fields": {"temats": "T"}, "text": "x"}))
    assert got["register_did"] is None and got["received_vc"] is False
