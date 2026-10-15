"""Lietas: glabāšanas termiņa beigas, dokumentu reģistrs un ark:Lieta pret XSD."""

from datetime import date, datetime, timezone

import pytest
from lxml import etree

from opendms.archive import cases as cs
from opendms.archive.scheme import ARK

ORG = {"id": 1, "std_code": "05-0000", "name": "Parauga iestāde"}
CASE_ID = "LV-LIETA:05-0000:2026:01928f3e-7b6a-7c3d-9e4f-0123456789ab"
DOC_UID = "LV-DOK:05-0000:2026:01928f3e-7b6a-7c3d-8e4f-0123456789ab"


@pytest.mark.parametrize("kind,years,trigger,closed,date_to,expected", [
    ("Gadi", 10, "NoLietasSlegsanas", date(2026, 12, 30), None, date(2037, 1, 1)),
    ("Gadi", 5, "NoDokumentaDatuma", date(2027, 2, 1), date(2026, 11, 3), date(2031, 11, 3)),
    ("Gadi", 1, "NoDokumentaDatuma", date(2025, 1, 5), date(2024, 2, 29), date(2025, 2, 28)),
    ("Gadi", 3, None, date(2026, 6, 1), None, date(2030, 1, 1)),
    ("Pastavigi", None, None, date(2026, 6, 1), None, None),
])
def test_retention_end(kind, years, trigger, closed, date_to, expected):
    assert cs.retention_end(kind, years, trigger, closed, date_to) == expected


def _doc(i, **kw):
    return {"id": i, "registration_number": f"1-12/{i}", "title": f"Iesniegums {i}", "doc_uid": DOC_UID if i == 1 else None,
            "created_at": datetime(2026, 3, i, 10, tzinfo=timezone.utc), "metadata": kw.pop("metadata", {}), **kw}


def test_register_xml_valid():
    case = {"case_id": CASE_ID, "case_index": "1-12", "case_name": "Iesniegumi un sūdzības"}
    docs = [_doc(1, metadata={"sender": {"name": "Jānis Bērziņš"}}),
            _doc(2, _sent=True, metadata={"recipients": [{"name": "VARAM"}]}),
            _doc(3, creator_name="Lietvede")]
    xml = cs.register_xml(ORG, {"registration_number": "90000000000"}, case, docs,
                          {1: ["iesniegums.pdf"], 2: ["atbilde.edoc"]}, {})
    root = etree.fromstring(xml)
    rows = root.findall(f"{{{ARK}}}Ieraksts")
    assert [r.findtext(f"{{{ARK}}}Veids") for r in rows] == ["Sanemtais", "Nosutamais", "Ieksejais"]
    assert [r.findtext(f"{{{ARK}}}InformacijasVide") for r in rows] == ["E", "E", "P"]
    assert rows[1].findtext(f"{{{ARK}}}Adresats") == "VARAM"
    assert rows[0].findtext(f"{{{ARK}}}DokumentaID") == DOC_UID


def test_register_rejects_bad_index():
    case = {"case_id": CASE_ID, "case_index": "1 12 x", "case_name": "x"}
    with pytest.raises(cs.CaseError):
        cs.register_xml(ORG, {}, case, [_doc(1)], {}, {})


def _case(**kw):
    c = {"case_id": CASE_ID, "case_index": "1-12", "case_year": 2026, "case_name": "Iesniegumi", "status": "Slegta",
         "scheme_entry_id": 4, "shemas_ieraksts": {"scheme_id": 2, "idx": "1-12"},
         "opened_at": datetime(2026, 1, 2, tzinfo=timezone.utc), "created_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
         "closed_at": datetime(2026, 12, 30, tzinfo=timezone.utc), "date_from": date(2026, 1, 5), "date_to": date(2026, 12, 1),
         "retention_end": date(2037, 1, 1), "disposition": "Iznicinat", "register_sha256": "a" * 64,
         "sejumi": [], "dokumenti": [{"datnes": 2}, {"datnes": 1}]}
    c.update(kw)
    return c


def test_case_xml_valid_default_volume():
    root = etree.fromstring(cs.case_xml(ORG, _case()))
    s = root.find(f"{{{ARK}}}Sejums")
    assert s.findtext(f"{{{ARK}}}Nesejs") == "E"
    assert {a.get("mervieniba"): a.text for a in s.findall(f"{{{ARK}}}Apjoms")} == {"dokumenti": "2", "datnes": "3"}


def test_case_xml_hybrid():
    vols = [{"number": 1, "medium": "E", "content_type": "Teksts", "document_count": 2, "file_count": 3},
            {"number": 2, "medium": "P", "content_type": "Teksts", "document_count": 4, "page_count": 37}]
    root = etree.fromstring(cs.case_xml(ORG, _case(sejumi=vols)))
    assert [s.findtext(f"{{{ARK}}}Nesejs") for s in root.findall(f"{{{ARK}}}Sejums")] == ["E", "P"]


def test_case_xml_needs_scheme():
    with pytest.raises(cs.CaseError):
        cs.case_xml(ORG, _case(shemas_ieraksts=None))
