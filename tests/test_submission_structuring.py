import asyncio
from pathlib import Path
from unittest import mock

from lxml import etree

from opendms.intake import esubmission as E
from opendms.intake import structuring as S

F = Path(__file__).parent / "fixtures" / "esubmission"
FILES = {"tiesibsargs/iesnieguma-shema/shemas/e-submission-0.1.xsd": F / "e-submission-0.1.xsd",
         "tiesibsargs/iesnieguma-shema/noteikumi/e-submission-0.1.sch": F / "e-submission-0.1.sch",
         "tiesibsargs/temu-klasifikators/klasifikators.xml": F / "klasifikators.xml"}
NS = {"es": E.NS}
LETTER = ("Labdien! Mani sauc Jānis Piemērs, personas kods 010180-12345, tālr. 29123456, e-pasts janis@example.lv. "
          "18.08.2026 iesniedzu Parauga novada sociālajā dienestā iesniegumu par mājokļa pabalstu. "
          "Atbildes nav joprojām. Lūdzu palīdzēt, lai dienests pieņem lēmumu.")


async def _ff(ref):
    return FILES[ref].read_bytes()


def test_mask_roundtrip_hides_identifiers_and_sender():
    masked, m = S.mask(LETTER, "Jānis Piemērs")
    for secret in ("010180-12345", "29123456", "janis@example.lv", "Jānis", "Piemērs"):
        assert secret not in masked, secret
    assert S.unmask(masked, m) == LETTER


def test_sanitise_drops_unknown_values_and_broken_refs():
    raw = {"submissionType": ["sudziba", "zzz"],
           "parties": [{"id": "p1", "role": ["submitter"], "partyType": "naturalPerson", "givenName": "Jānis", "legalName": "x"},
                       {"id": "r1", "role": ["respondent"], "partyType": "institution", "legalName": "Dienests"},
                       {"id": "bad id", "role": ["respondent"]}],
           "facts": [{"id": "f1", "statement": "Iesniedza.", "actor": ["p1", "zz"], "when": {"date": "18.08.2026"}, "conduct": "act"},
                     {"id": "f1", "statement": "Nav atbildes.", "when": {"period": {"from": "2026-08-18", "to": "2026-01-01"}}}],
           "claims": [{"id": "c1", "type": "help", "text": "Palīdzēt", "relatedFact": ["f2", "f9"], "addressedTo": "r9"}],
           "privacy": {"doNotDiscloseIdentity": "yes"}}
    p = S.sanitise(raw, sender={"email": "j@example.lv"})
    assert p["submissionType"] == ["sudziba"]
    assert [x["id"] for x in p["parties"]] == ["p1", "r1"] and "legalName" not in p["parties"][0]
    assert p["parties"][0]["contact"]["email"] == "j@example.lv"
    f1, f2 = p["facts"]
    assert f1["actor"] == ["p1"] and "when" not in f1 and "conduct" not in f1 and f1["basis"] == "claimed"
    assert f2["id"] == "f2" and f2["when"] == {"period": {"from": "2026-08-18"}}
    c = p["claims"][0]
    assert c["type"] == "other" and c["relatedFact"] == ["f2"] and "addressedTo" not in c
    assert p["privacy"]["doNotDiscloseIdentity"] is False and p["priorSteps"]["court"]["status"] == "unknown"


MODEL = {"submissionType": ["sudziba"], "title": "Nav atbildes par mājokļa pabalstu",
         "parties": [{"id": "p1", "role": ["submitter", "affectedPerson"], "partyType": "naturalPerson",
                      "givenName": "[P1_VARDS_1]", "contact": {"email": "[EPASTS_1]", "phone": "[TALRUNIS_1]"}},
                     {"id": "r1", "role": ["respondent"], "partyType": "institution", "legalName": "Parauga novada sociālais dienests"}],
         "narrative": {"summary": "Sociālais dienests nav atbildējis uz iesniegumu par mājokļa pabalstu."},
         "facts": [{"id": "f1", "when": {"date": "2026-08-18"}, "actor": ["p1"], "conduct": "action",
                    "statement": "Iesniedzējs iesniedza iesniegumu par mājokļa pabalstu.", "sourceExcerpt": "18.08.2026 iesniedzu"},
                   {"id": "f2", "when": {"period": {"from": "2026-08-18"}}, "actor": ["r1"], "conduct": "omission",
                    "statement": "Dienests nav atbildējis.", "sourceExcerpt": "Atbildes nav joprojām."}],
         "rightsAffected": {"domain": ["SEK"]},
         "claims": [{"id": "c1", "type": "remedy", "text": "Lai dienests pieņem lēmumu.", "addressedTo": "r1", "relatedFact": ["f2"]}],
         "priorSteps": {"step": [{"type": "contactedRespondent", "addressedTo": "r1", "date": "2026-08-18", "responseReceived": False}],
                        "court": {"status": "unknown"}},
         "privacy": {"doNotDiscloseIdentity": False, "replyChannel": "email"}}


def test_structure_from_email_end_to_end():
    stored, recorded, seen_prompt = {}, {}, {}

    async def fake_doc(doc_id):
        return {"row": {"id": 7, "doc_uid": "LV-DOK:90000055101:2026:0001", "registration_number": "TB-2026/7", "created_at": None},
                "meta": {"ievade": {"channel": "EPasts", "receivedAt": "2026-10-22T21:40:00+03:00",
                                    "sender": {"name": "Jānis Piemērs", "email": "janis@example.lv"}}},
                "files": [{"id": 1, "file_name": "pavadteksts.txt", "mime_type": "text/plain", "checksum_sha256": "a" * 64, "storage_key": "k1"},
                          {"id": 2, "file_name": "lemums.pdf", "mime_type": "application/pdf", "checksum_sha256": "b" * 64, "storage_key": "k2"}]}

    async def fake_model(system, user_msg, **kw):
        seen_prompt["user"] = user_msg
        return MODEL

    async def fake_store(doc_id, name, xml):
        stored[name] = xml
        return 99

    async def fake_record(doc_id, info):
        recorded.update(info)

    async def go():
        with mock.patch("opendms.uapf.learning.fetch_file", _ff), mock.patch.object(S, "_document", fake_doc), \
             mock.patch.object(S, "_store", fake_store), mock.patch.object(S, "_record", fake_record), \
             mock.patch("opendms.ai._complete_json", fake_model), mock.patch("opendms.ai._cfg", lambda: {"model": "test-model"}):
            E._cache.clear()
            return await S.handle_submission_structure({"input": {"documentId": 7, "content": LETTER}})
    out = asyncio.run(go())["output"]
    assert out["strukturaStatuss"] == "structured" and out["strukturasFakti"] == 2 and out["strukturasPrasijumi"] == 1
    for secret in ("010180-12345", "29123456", "janis@example.lv", "Piemērs"):
        assert secret not in seen_prompt["user"], secret
    doc = etree.fromstring(stored[S.FILE_NAME])
    t = lambda p: doc.findtext(p, namespaces=NS)  # noqa: E731
    assert t("es:identity/es:status") == "structured" and t("es:identity/es:channel") == "email"
    assert t("es:identity/es:documentId") == "LV-DOK:90000055101:2026:0001"
    assert t("es:provenance/es:structuring/es:method") == "ai" and t("es:provenance/es:structuring/es:model") == "test-model"
    assert t("es:parties/es:party/es:contact/es:email") == "janis@example.lv"          # token restored in code
    assert t("es:attachments/es:attachment/es:fileName") == "lemums.pdf"              # the original is the source, not an attachment
    assert {"W-110", "W-111", "W-103"} <= set(out["strukturasBridinajumi"])
    assert recorded["status"] == "structured" and recorded["datne"] == 99
