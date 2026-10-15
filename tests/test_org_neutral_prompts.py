"""AI instructions name the DVS's own organisation; drafts accept any process variable."""

import asyncio

from opendms import org_context
from opendms.uapf import handlers, learning


def run(c):
    return asyncio.run(c)


def test_org_label_uses_default_org(monkeypatch):
    async def org():
        return {"name": 'AS "Rīgas siltums"'}
    monkeypatch.setattr(org_context, "get_default_org", org)
    assert run(org_context.org_label()) == 'AS "Rīgas siltums"'


def test_org_label_fallback(monkeypatch):
    async def boom():
        raise RuntimeError("no db")
    monkeypatch.setattr(org_context, "get_default_org", boom)
    assert run(org_context.org_label()) == "a Latvian organisation"


def test_prompts_have_no_fixed_institution():
    assert "{org}" in learning.CLASSIFY_PROMPT and "Ombudsman" not in learning.CLASSIFY_PROMPT
    assert "{org}" in handlers.INCOMING_FACETS_PROMPT and "public institution" not in handlers.INCOMING_FACETS_PROMPT


def test_draft_takes_process_variables():
    out = run(handlers.handle_ai_draft({"input": {
        "templateBody": "Adresāts: {adresats}\nTemats: {temats}\nNr. {registracijas_nr}\nCits: {nav_tada}",
        "adresats": "SIA Piemērs", "temats": "Pieslēguma tehniskie noteikumi", "registrationNumber": "RS-1/2"}}))
    t = out["output"]["draftText"]
    assert "Adresāts: SIA Piemērs" in t and "Temats: Pieslēguma tehniskie noteikumi" in t
    assert "Nr. RS-1/2" in t and "Cits: […]" in t


def test_draft_takes_document_metadata():
    out = run(handlers.handle_ai_draft({"input": {
        "templateBody": "Adresāts: {adresats}; temats: {temats}",
        "metadata": {"adresats": "Rīgas valstspilsētas pašvaldība", "temats": "Ielu remonts", "x": {"nested": 1}}}}))
    assert out["output"]["draftText"] == "Adresāts: Rīgas valstspilsētas pašvaldība; temats: Ielu remonts"


def test_outgoing_route_fields_are_recorded():
    for k in ("saskanotajs", "parakstitajs", "statuss"):
        assert k in handlers.PROCESS_RESULT_KEYS


def test_classify_uses_draft_text_when_no_file(monkeypatch):
    seen = {}

    async def ref(_):
        return {"klasifikators": {"versija": "t", "kodi": [{"kods": "02-02", "nosaukums": "Sūdzības", "izvelams": True,
                 "joma": "KAD", "jomasNosaukums": "Klienti", "kategorija": "02-02", "kategorijasNosaukums": "Sūdzības",
                 "cels": "Sūdzības"}]}, "vienibas": None, "avoti": {}}

    async def none(*a, **k):
        return None

    async def nothing(*a, **k):
        return []

    async def model(system, user):
        seen["user"] = user
        return {"kods": "02-02", "parliecība": 0.9, "pamatojums": "x"}

    import opendms.ai as ai
    monkeypatch.setattr(learning, "reference_data", ref)
    monkeypatch.setattr(learning, "_package_of", none)
    monkeypatch.setattr(learning, "similar_precedents", nothing)
    monkeypatch.setattr(learning, "_structured_choice", none)
    monkeypatch.setattr(ai, "_complete_json", model)
    async def org():
        return "AS RS"
    monkeypatch.setattr(org_context, "org_label", org)
    out = run(learning.handle_ai_classify({"input": {"draftText": "Atbilde uz sūdzību par apkuri"}}))["output"]
    assert out["kods"] == "02-02" and "Atbilde uz sūdzību" in seen["user"]
