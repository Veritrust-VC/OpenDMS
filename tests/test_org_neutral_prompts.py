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
