"""Jauns dokuments from the Agent: proposal without storing, submit through intake."""

import asyncio
import base64

from opendms.intake import agent_channel
from opendms.mcp import tools


def test_tools_listed():
    names = {t["name"] for t in tools.public_tools()}
    assert {"dokumenta_priekslikums", "iesniegt_dokumentu"} <= names
    assert tools.TOOL_INDEX["iesniegt_dokumentu"]["class"] == tools.WRITE


def test_propose_redacts_and_keeps_known_types(monkeypatch):
    seen = {}

    async def redact(ctx):
        return {"output": {"redactedContent": ctx["input"]["content"].replace("Jānis Bērziņš", "[VĀRDS]")}}

    async def complete_json(system, user, **k):
        seen["user"] = user
        return {"temats": "Bērnudārza vieta", "dokumentaVeids": "nezināms", "prasaAtbildi": True}

    async def label():
        return "Tiesībsarga birojs"
    import opendms.uapf.handlers as h
    import opendms.ai as ai
    import opendms.org_context as oc
    monkeypatch.setattr(h, "handle_ai_redact", redact)
    monkeypatch.setattr(ai, "_complete_json", complete_json)
    monkeypatch.setattr(oc, "org_label", label)
    r = asyncio.run(agent_channel.propose(text="Es, Jānis Bērziņš, lūdzu vietu bērnudārzā."))
    assert "Jānis" not in seen["user"]
    assert r["priekslikums"]["temats"] == "Bērnudārza vieta" and r["priekslikums"]["dokumentaVeids"] is None


def test_submit_goes_through_intake_without_ack(monkeypatch):
    got = {}

    async def ingest(channel, **k):
        got.update(channel=channel, **k)
        return {"documentId": 77, "registrationNumber": "1-00077", "datnes": 1}
    import opendms.intake.service as svc
    monkeypatch.setattr(svc, "ingest", ingest)
    r = asyncio.run(agent_channel.submit(fields={"temats": "Sūdzība", "dokumentaVeids": "sūdzība"}, person="a@x.lv",
                                         file_name="a.txt", mime_type="text/plain",
                                         file_b64=base64.b64encode(b"teksts").decode()))
    assert r["documentId"] == 77
    assert got["channel"]["apstiprinajums"]["ieslegts"] is False
    assert got["subject"] == "Sūdzība" and got["attachments"][0]["data"] == b"teksts"
    assert got["extra"]["ievadija"] == "a@x.lv"
