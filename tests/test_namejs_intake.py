"""Namejs intake — sync logic against a live Namejs API, database replaced by fakes.

Skipped unless NAMEJS_TEST_URL points at a Namejs API (e.g. the emulator):

    NAMEJS_TEST_URL=http://localhost:8090/API pytest tests/test_namejs_intake.py
"""

import asyncio
import os

import httpx
import pytest

from opendms import namejs_intake as intake
from opendms.connectors import namejs

URL = os.environ.get("NAMEJS_TEST_URL")
pytestmark = pytest.mark.skipif(not URL, reason="NAMEJS_TEST_URL not set")
CFG = {"base_url": URL or "", "client_id": os.environ.get("NAMEJS_TEST_CLIENT", "ombud-dvs")}
SEC = {"client_secret": os.environ.get("NAMEJS_TEST_SECRET", "demo-secret")}
ACTOR = {"id": 1, "email": "admin@test", "role": "superadmin"}


class FakeDb:
    def __init__(self):
        self.docs: dict[int, dict] = {}
        self.files: dict[int, list] = {}

    async def find(self, nid):
        return next(({"id": i, "registration_number": d["reg"]} for i, d in self.docs.items()
                     if d["metadata"].get("namejs_document_id") == str(nid)), None)

    async def update(self, doc_id, patch):
        self.docs[doc_id]["metadata"].update(patch)

    async def create(self, title, summary, metadata, actor):
        doc_id = len(self.docs) + 1
        self.docs[doc_id] = {"title": title, "summary": summary, "metadata": dict(metadata), "reg": f"1-{doc_id:05d}"}
        return {"id": doc_id, "registration_number": f"1-{doc_id:05d}"}

    async def add_file(self, doc_id, name, content, content_type, actor):
        self.files.setdefault(doc_id, []).append((name, content, content_type))
        return {"id": len(self.files[doc_id])}


@pytest.fixture
def db(monkeypatch):
    fake = FakeDb()

    async def run(operation, inputs, actor):
        return await namejs.invoke(operation, CFG, SEC, inputs, {})

    async def actor():
        return ACTOR

    monkeypatch.setattr(intake, "_run", run)
    monkeypatch.setattr(intake, "_system_actor", actor)
    monkeypatch.setattr(intake, "_find_imported", fake.find)
    monkeypatch.setattr(intake, "_update_metadata", fake.update)
    monkeypatch.setattr(intake, "_create_document", fake.create)
    monkeypatch.setattr(intake, "_add_file", fake.add_file)
    monkeypatch.setattr(intake, "_subscribed", False)
    return fake


def emulator_admin(path, **data):
    """Operator console of the emulator: simulates activity inside Namejs."""
    root = URL.rsplit("/API", 1)[0]
    auth = ("admin", os.environ.get("NAMEJS_TEST_ADMIN_PASSWORD", "namejs-demo"))
    return httpx.post(f"{root}/_emulator{path}", json=data, auth=auth).json()


def test_new_document_is_imported_with_its_file(db):
    asyncio.run(intake.sync(config={}))  # subscribe and drain earlier events
    created = emulator_admin("/documents", name="Iesniegums par intake testu", folderId="4",
                             correspondent="Testa pieteicējs", text="Lūdzu izvērtēt.")
    r = asyncio.run(intake.sync(config={}))
    assert r["ok"] and r["acknowledged"] >= 1, r
    mine = [x for x in r["imported"] if x["namejs_document_id"] == created["id"]]
    assert len(mine) == 1
    doc = db.docs[mine[0]["document_id"]]
    assert doc["title"] == "Iesniegums par intake testu"
    assert doc["metadata"]["source"] == "namejs" and doc["metadata"]["namejs_status"] == "DST_NPS"
    _name, content, _ = db.files[mine[0]["document_id"]][0]
    assert "Lūdzu izvērtēt." in content.decode()


def test_status_change_updates_the_imported_copy(db):
    asyncio.run(intake.sync(config={}))
    created = emulator_admin("/documents", name="Statusa maiņas tests", folderId="1")
    asyncio.run(intake.sync(config={}))
    emulator_admin(f"/documents/{created['id']}/register")
    r = asyncio.run(intake.sync(config={}))
    assert r["updated"] >= 1 and not r["imported"]
    doc = next(d for d in db.docs.values() if d["metadata"]["namejs_document_id"] == str(created["id"]))
    assert doc["metadata"]["namejs_status"] == "DST_REG_DONE"
    assert doc["metadata"]["namejs_registration_no"]
    assert len(db.docs) == 1  # no duplicate


def test_folder_filter_skips_and_acknowledges(db):
    asyncio.run(intake.sync(config={}))
    emulator_admin("/documents", name="Cita mape", folderId="1")
    r = asyncio.run(intake.sync(config={"intake_folder_ids": "4"}))
    assert r["skipped"] >= 1 and not r["imported"] and r["acknowledged"] >= 1
    assert asyncio.run(intake.sync(config={}))["events"] == 0  # nothing redelivered


def test_manual_import_is_idempotent(db):
    first = asyncio.run(intake.import_document(1, ACTOR))
    again = asyncio.run(intake.import_document(1, ACTOR))
    assert first["imported"] and again["already_imported"]
    assert again["document_id"] == first["document_id"]
    assert len(db.files[first["document_id"]]) == 1


def test_failed_import_is_not_acknowledged(db, monkeypatch):
    asyncio.run(intake.sync(config={}))
    emulator_admin("/documents", name="Kļūdas tests", folderId="4")

    async def broken(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr(intake, "_create_document", broken)
    r = asyncio.run(intake.sync(config={}))
    assert r["failed"] and r["acknowledged"] == 0

    monkeypatch.setattr(intake, "_create_document", db.create)
    r = asyncio.run(intake.sync(config={}))
    assert r["imported"], "event was redelivered and imported on the next poll"


def test_poll_interval_setting():
    assert intake._poll_seconds({}) == 0
    assert intake._poll_seconds({"intake_poll_seconds": "30"}) == 30
    assert intake._poll_seconds({"intake_poll_seconds": "x"}) == 0
    assert intake._folder_filter({"intake_folder_ids": "1, 4"}) == {1, 4}
