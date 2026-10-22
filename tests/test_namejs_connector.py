"""Namejs connector tests.

The unit tests run offline. The live tests drive a real Namejs API — normally the
Namejs emulator from PPPA-LV/Namejs-MCP (emulator/) — and are skipped unless
NAMEJS_TEST_URL points at one, e.g.:

    NAMEJS_TEST_URL=http://localhost:8090/API \
    NAMEJS_TEST_CLIENT=ombud-dvs NAMEJS_TEST_SECRET=demo-secret pytest tests/test_namejs_connector.py
"""

import asyncio
import base64
import os

import pytest

from opendms.connectors import capability_index, describe_all, get_driver, namejs


def run(coro):
    return asyncio.run(coro)


# ── offline ──────────────────────────────────────────────────────────────────

def test_registered_and_advertised():
    assert get_driver("namejs") is namejs
    d = next(x for x in describe_all() if x["kind"] == "namejs")
    assert d["implemented"] is True
    assert {f["key"] for f in d["secret_fields"]} == {"client_secret", "password"}
    assert capability_index()["connector/namejs.register-document"] == ("namejs", "register_document")


def test_token_url_derived_from_api_address():
    assert namejs._token_url({"base_url": "https://dvs.example.lv/API"}) == "https://dvs.example.lv/STS/connect/token"
    assert namejs._token_url({"base_url": "https://h.lv/namejs/API/"}) == "https://h.lv/namejs/STS/connect/token"
    assert namejs._token_url({"base_url": "https://h.lv/API", "token_url": "https://sts.h.lv/t"}) == "https://sts.h.lv/t"


def test_incomplete_connection_is_a_result_not_an_exception():
    r = run(namejs.test({"base_url": "https://x/API"}, {}))
    assert not r.ok and set(r.data["missing"]) == {"client_id", "client_secret"}
    r = run(namejs.invoke("get_document", {"base_url": "https://x/API", "client_id": "a",
                                           "grant_type": "password"}, {}, {}, {}))
    assert not r.ok and set(r.data["missing"]) == {"username", "password"}


def test_unknown_operation():
    r = run(namejs.invoke("nope", {}, {}, {}, {}))
    assert not r.ok and "available" in r.data


def test_unreachable_host_is_reported():
    cfg = {"base_url": "http://127.0.0.1:9/API", "client_id": "a"}
    r = run(namejs.test(cfg, {"client_secret": "b"}))
    assert not r.ok and r.reason


# ── live, against a Namejs API (emulator) ────────────────────────────────────

URL = os.environ.get("NAMEJS_TEST_URL")
live = pytest.mark.skipif(not URL, reason="NAMEJS_TEST_URL not set")
CFG = {"base_url": URL or "", "client_id": os.environ.get("NAMEJS_TEST_CLIENT", "ombud-dvs")}
SEC = {"client_secret": os.environ.get("NAMEJS_TEST_SECRET", "demo-secret")}


def op(_operation, **inputs):
    return run(namejs.invoke(_operation, CFG, SEC, inputs, {}))


@live
def test_live_connection_test():
    r = run(namejs.test(CFG, SEC))
    assert r.ok, r.reason
    assert r.data["flow_statuses"] > 0


@live
def test_live_wrong_secret():
    namejs._TOKENS.clear()
    r = run(namejs.test(CFG, {"client_secret": "wrong"}))
    assert not r.ok and "token request rejected" in r.reason


@live
def test_live_document_round_trip():
    created = op("create_document", name="OpenDMS savienojuma tests", folder_id=4, type_id=1,
                 description="Izveidots no OpenDMS Namejs savienotāja testa")
    assert created.ok, created.reason
    doc_id = created.data["document_id"]

    found = op("search_documents", name="savienojuma tests")
    assert found.ok and any(d["id"] == doc_id for d in found.data["documents"])

    content = "Testa saturs ar garumzīmēm: āčēģīķļņšūž".encode()
    att = op("attach_file", document_id=doc_id, file_name="tests.txt",
             content_b64=base64.b64encode(content).decode(), content_type="text/plain")
    assert att.ok and att.data["file_id"], att.reason

    files = op("list_files", document_id=doc_id)
    assert files.ok and files.data["files"][0]["name"] == "tests.txt"
    dl = op("download_file", document_id=doc_id, file_id=att.data["file_id"])
    assert dl.ok and base64.b64decode(dl.data["content_b64"]) == content

    reg = op("register_document", document_id=doc_id)
    assert reg.ok and reg.data["registration_no"], reg.reason
    again = op("register_document", document_id=doc_id)
    assert not again.ok and "409" in again.reason

    attr = op("set_attribute", document_id=doc_id, attribute_id=1,
              text_value="did:web:ombud.pac.kisc.gov.lv:doc:test")
    assert attr.ok, attr.reason
    doc = op("get_document", document_id=doc_id)
    assert doc.data["document"]["attributes"][0]["textValue"].startswith("did:web:")

    flow = op("start_task_flow", document_id=doc_id)
    assert flow.ok, flow.reason


@live
def test_live_status_feed():
    assert op("subscribe_status").ok
    op("poll_status", ack=True)  # drain
    created = op("create_document", name="Statusu plūsmas tests", folder_id=1)
    assert created.ok
    doc_id = created.data["document_id"]
    assert op("register_document", document_id=doc_id).ok

    polled = op("poll_status")
    mine = [e for e in polled.data["events"] if e["documentId"] == doc_id]
    assert [e["status"] for e in mine] == ["DST_NPS", "DST_REG_DONE"]

    assert op("ack_status", event_ids=",".join(str(e["id"]) for e in polled.data["events"])).ok
    assert op("poll_status").data["count"] == 0


@live
def test_live_missing_document():
    r = op("get_document", document_id=999999)
    assert not r.ok and "not found" in r.reason
