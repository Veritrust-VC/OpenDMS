"""Host side of the lab process packages: P1 facets, simulated classifier."""
import asyncio

from opendms.uapf import handlers
from opendms.uapf.classification_sim import lookup


def test_classification_lookup_is_marked_simulated():
    out = asyncio.run(handlers.handle_classification_lookup(
        {"input": {"title": "INTERREG BSR", "content": "projekta progresa pārskats"}}))["output"]
    assert out["klasifikacijasIndekss"] == "I2"
    assert out["simulets"] is True and "Simulēta" in out["shema"]


def test_classification_lookup_unknown_goes_to_manual():
    assert lookup("nekas atbilstošs")["klasifikacijasIndekss"] == "X"


def test_extract_maps_p1_facets_from_model(monkeypatch):
    async def fake(_system, _user):
        return {"mentionsChildren": True, "respondentType": "privatpersona", "courtPending": "true"}
    monkeypatch.setattr(handlers, "_complete_json", fake)
    out = asyncio.run(handlers.handle_ai_extract({"input": {"content": "x"}}))["output"]
    assert out["mentionsChild"] is True            # defaulted from mentionsChildren
    assert out["respondentType"] == "privatpersona"
    assert out["courtPending"] is True
    assert out["competentAuthorityKnown"] is False


def test_extract_fallback_has_p1_keys(monkeypatch):
    async def none(_s, _u):
        return None
    monkeypatch.setattr(handlers, "_complete_json", none)
    out = asyncio.run(handlers.handle_ai_extract({"input": {"content": "x"}}))["output"]
    assert out["respondentType"] == "nav-zinams" and "socialRights" in out


def test_task_and_classification_are_offered():
    assert "task/request" in handlers.HANDLERS
    assert "classification/lookup" in handlers.HANDLERS


def test_incoming_facets_contract_selected_by_schema_ref(monkeypatch):
    async def none(_s, _u):
        return None
    monkeypatch.setattr(handlers, "_complete_json", none)
    out = asyncio.run(handlers.handle_ai_extract({
        "input": {"content": "Informatīvs paziņojums. Atbilde nav nepieciešama."},
        "schema_ref": "uapf:schema/dvs-ienakosa-dokumenta-pazimes"}))["output"]
    assert out["prasaAtbildi"] is False and out["irZinojums"] is True
    assert "mentionsChildren" not in out


def test_vc_issue_is_offered():
    assert "vc/issue" in handlers.HANDLERS


def test_verify_reports_missing_elements():
    out = asyncio.run(handlers.handle_ai_verify({"input": {
        "draftText": "Rekvizīti: …\nNormatīvā atsauce: …", "element": ["rekviziti", "normativa-atsauce", "parsudzibas-kartiba"]}}))["output"]
    assert out["missingElements"] == ["parsudzibas-kartiba"] and out["elementsOk"] is False


def test_template_fetch_selected_by_target(monkeypatch):
    async def fake(inp):
        return {"output": {"templateId": inp["templateId"]}}
    monkeypatch.setattr(handlers, "_fetch_template", fake)
    out = asyncio.run(handlers.handle_document_fetch({
        "input": {"templateId": "TPL-ATTEIKT", "documentId": 1},
        "target": {"id": "system.opendms-template-library"}}))["output"]
    assert out == {"templateId": "TPL-ATTEIKT"}


def test_seed_templates_cover_p2_outcomes():
    from opendms.uapf.templates import SEED
    ids = {t[0] for t in SEED}
    assert {"TPL-ATTEIKT", "TPL-VIRZIT-IZSKATISANAI", "TPL-PIENEMSANA-BERNU",
            "TPL-PARSUTIT-CITAI-IESTADEI", "TPL-UZSAKT-PARBAUDI"} <= ids
    for _id, _title, body in SEED:
        assert "SINTĒTISKA" in body and "Rekvizīti" in body
