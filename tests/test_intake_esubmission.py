import asyncio
from pathlib import Path
from unittest import mock

from lxml import etree

from opendms.intake import esubmission as E

F = Path(__file__).parent / "fixtures" / "esubmission"
FILES = {"t/s/e-submission-0.1.xsd": F / "e-submission-0.1.xsd", "t/s/e-submission-0.1.sch": F / "e-submission-0.1.sch",
         "t/k/klasifikators.xml": F / "klasifikators.xml"}
SH = {"xsd": "t/s/e-submission-0.1.xsd", "noteikumi": "t/s/e-submission-0.1.sch", "klasifikators": "t/k/klasifikators.xml"}
NS = {"es": E.NS}


async def _ff(ref):
    return FILES[ref].read_bytes()


def payload(**over):
    p = {
        "submissionType": ["sudziba"],
        "parties": [
            {"id": "p1", "role": ["submitter", "affectedPerson"], "partyType": "naturalPerson",
             "givenName": "Jānis", "familyName": "Paraugs", "address": "Parauga iela 1, LV-0000",
             "contact": {"email": "j@example.lv"}},
            {"id": "r1", "role": ["respondent"], "partyType": "institution", "legalName": "Paraugu pašvaldība"},
        ],
        "narrative": {"summary": "Ēkā nav uzbrauktuves, un dokumentus atteica pieņemt."},
        "facts": [{"id": "f1", "when": {"yearMonth": "2026-09"}, "actor": ["r1"], "conduct": "omission",
                   "statement": "Pašvaldības ēkā nav uzbrauktuves ratiņkrēslam.", "basis": "documented", "evidence": ["a1"]}],
        "rightsAffected": {"domain": ["TV"]},
        "claims": [{"id": "c1", "type": "investigate", "text": "Izvērtēt pieejamību.", "addressedTo": "r1", "relatedFact": ["f1"]}],
        "priorSteps": {"step": [{"type": "contactedRespondent", "addressedTo": "r1", "responseReceived": False}],
                       "court": {"status": "no"}},
        "privacy": {"doNotDiscloseIdentity": False, "doNotDiscloseFacts": False, "noReplyNeeded": False, "replyChannel": "email"},
    }
    p.update(over)
    return p


ATT = [{"file_name": "foto.jpg", "mime_type": "image/jpeg", "data": b"abc", "apraksts": "Ieeja"}]
DECL = {"informationTruthful": True, "dataProcessingAcknowledged": True}


def run(p, **kw):
    async def go():
        with mock.patch("opendms.uapf.learning.fetch_file", _ff):
            E._cache.clear()
            kw.setdefault("channel", "portal")
            kw.setdefault("attachments", ATT)
            kw.setdefault("signature", "latvijaLvIdentified")
            kw.setdefault("signers", ["p1"])
            kw.setdefault("declarations", DECL)
            x = E.build(p, **kw)
            return x, await E.validate(x, SH, await E.classifier(SH))
    return asyncio.run(go())


def test_form_submission_valid_without_warnings():
    x, r = run(payload())
    assert r["errors"] == [] and r["warnings"] == [], r
    doc = etree.fromstring(x)
    assert doc.findtext("es:identity/es:channel", namespaces=NS) == "portal"
    assert doc.findtext("es:attachments/es:attachment/es:sha256", namespaces=NS).startswith("ba7816bf")
    assert r["info"]["sender"]["name"] == "Jānis Paraugs" and r["info"]["iestades"] == ["Paraugu pašvaldība"]
    assert r["info"]["prasijumi"][0]["veids"] == "investigate"


def test_payload_cannot_set_identity_or_attachments():
    p = payload(identity={"channel": "a2a"}, attachments={"attachment": []})
    x, r = run(p)
    doc = etree.fromstring(x)
    assert doc.findtext("es:identity/es:channel", namespaces=NS) == "portal"
    assert len(doc.findall("es:attachments/es:attachment", NS)) == 1


def test_broken_reference_is_error():
    p = payload()
    p["claims"][0]["relatedFact"] = ["f9"]
    _, r = run(p)
    assert any("E-012" in e for e in r["errors"])


def test_missing_address_is_warning_not_error():
    p = payload()
    del p["parties"][0]["address"]
    _, r = run(p)
    assert r["errors"] == [] and {w["id"] for w in r["warnings"]} == {"W-103"}


def test_email_unsigned_warnings():
    _, r = run(payload(), channel="email", signature="none", signers=[], declarations=None,
               structuring={"method": "ai", "model": "test"})
    ids = {w["id"] for w in r["warnings"]}
    assert {"W-110", "W-111", "W-021"} <= ids and r["errors"] == []


def test_classifier_code_strict_for_form_lenient_for_model():
    p = payload(rightsAffected={"domain": ["TV"], "classifierCode": ["23.A"]})
    _, r = run(p)
    assert any("nepieder" in e for e in r["errors"])

    async def go():
        with mock.patch("opendms.uapf.learning.fetch_file", _ff):
            x = E.build(p, channel="email", attachments=ATT, structuring={"method": "ai"})
            return await E.validate(x, SH, await E.classifier(SH), strict_classifier=False)
    r2 = asyncio.run(go())
    assert any(w["id"] == "W-KLAS" for w in r2["warnings"]) and not any("nepieder" in e for e in r2["errors"])


def test_text_is_clipped_to_schema_limits():
    p = payload(narrative={"summary": "x" * 5000})
    x, r = run(p)
    assert r["errors"] == []
    assert len(etree.fromstring(x).findtext("es:narrative/es:summary", namespaces=NS)) == 1000


def test_submitter_of():
    x, _ = run(payload())
    assert E.submitter_of(x) == {"name": "Jānis Paraugs", "email": "j@example.lv"}
    assert E.submitter_of(b"<a/>") is None
