import base64
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opendms import div

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def emu(tmp_path, monkeypatch):
    (tmp_path / "a.yaml").write_text(
        "adreses:\n"
        "  - {eAddress: '_DEFAULT@A', name: 'Iestāde A', code: '99-0001', did: 'did:web:a', token_env: TA}\n"
        "  - {eAddress: '_DEFAULT@B', name: 'Iestāde B', code: '99-0002', did: 'did:web:b', token_env: TB}\n", encoding="utf-8")
    monkeypatch.setenv("DIV_ADDRESSES", str(tmp_path / "a.yaml"))
    monkeypatch.setenv("DIV_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("TA", "tok-a")
    monkeypatch.setenv("TB", "tok-b")
    spec = importlib.util.spec_from_file_location("div_emulator", ROOT / "div-emulator" / "div_emulator.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["div_emulator"] = mod
    spec.loader.exec_module(mod)
    return TestClient(mod.app)


def env_and_files(sender="_DEFAULT@A", recipients=("_DEFAULT@B",), data=b"%PDF-1.4 x"):
    files = [{"content_id": "LV-DATNE:1", "name": "iesniegums.pdf", "mime_type": "application/pdf", "data": data}]
    env = div.build_envelope(sender=sender, recipients=list(recipients), sender_ref="1-00027-PX", title="Iesniegums",
                             description="Pārsūtām pēc piekritības", author="OpenDMS — A", kind_code="PARSUTISANA",
                             files=files, identity={"DokumentaID": "LV-DOK:05-0000:2026:x", "RegistraDID": "did:web:r:doc:1",
                                                    "Iemesls": "piekritiba"})
    return env, files


def body(env, files):
    return {"envelope": env.decode(), "attachments": [{"contentId": f["content_id"],
                                                       "contents": base64.b64encode(f["data"]).decode()} for f in files]}


A = {"Authorization": "Bearer tok-a"}
B = {"Authorization": "Bearer tok-b"}


def test_envelope_roundtrip():
    env, _ = env_and_files()
    p = div.parse_envelope(env)
    assert p["title"] == "Iesniegums" and p["kind"] == "PARSUTISANA" and p["sender"] == "_DEFAULT@A"
    assert p["files"][0]["content_id"] == "LV-DATNE:1" and p["identity"]["DokumentaID"].startswith("LV-DOK")


def test_full_cycle(emu):
    env, files = env_and_files()
    r = emu.post("/UnifiedService/SendMessage", json=body(env, files), headers=A)
    assert r.status_code == 200, r.text
    mid = r.json()["MessageId"]
    h = emu.get("/UnifiedService/GetMessageHeaders", headers=B).json()["Headers"]
    assert [x["MessageId"] for x in h] == [mid] and h[0]["SenderName"] == "Iestāde A"
    m = emu.get(f"/UnifiedService/GetMessage/{mid}", headers=B).json()
    pe = div.parse_envelope(m["Envelope"])
    assert pe["serverRef"].startswith("DIV-") and base64.b64decode(m["Attachments"][0]["Contents"]) == files[0]["data"]
    assert emu.post(f"/UnifiedService/ConfirmMessage/{mid}", json={"NotifySender": True}, headers=B).status_code == 200
    assert emu.get("/UnifiedService/GetMessageHeaders", headers=B).json()["Headers"] == []
    kinds = [n["Kind"] for n in emu.get("/UnifiedService/GetNotifications", headers=A).json()["Notifications"]]
    assert kinds == ["Delivered", "Confirmed"]


def test_rejects_wrong_sender_bad_digest_unknown_recipient(emu):
    env, files = env_and_files(sender="_DEFAULT@B")
    assert emu.post("/UnifiedService/SendMessage", json=body(env, files), headers=A).status_code == 403
    env, files = env_and_files()
    files[0] = {**files[0], "data": b"changed"}
    assert emu.post("/UnifiedService/SendMessage", json=body(env, files), headers=A).status_code == 400
    env, files = env_and_files(recipients=("_DEFAULT@X",))
    assert emu.post("/UnifiedService/SendMessage", json=body(env, files), headers=A).status_code == 400
    assert emu.get("/UnifiedService/GetMessageHeaders").status_code == 401


def test_other_recipient_cannot_read(emu):
    env, files = env_and_files()
    mid = emu.post("/UnifiedService/SendMessage", json=body(env, files), headers=A).json()["MessageId"]
    assert emu.get(f"/UnifiedService/GetMessage/{mid}", headers=A).status_code == 404
