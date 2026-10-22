"""P5/P6: uzskaites saraksts, uzskaites kodi, nodošanas akts pret XSD; DVS pakotne ar standarta rīkiem."""

import json
from datetime import date, datetime, timezone
from pathlib import Path

from lxml import etree

from opendms.archive import finding_aid as fa
from opendms.archive import transfer as tr
from opendms.archive.lna import builder, validator
from opendms.archive.scheme import ARK, _xsd

ORG = {"std_code": "05-0000", "name": "Tiesībsarga birojs", "reg_number": "90000055101"}
S = {"archive_code": "LVA", "archive_name": "Latvijas Valsts arhīvs", "fonds_number": "1234", "fonds_name": "Tiesībsarga birojs"}
CID = "LV-LIETA:05-0000:2020:01928f3e-7b6a-7c3d-9e4f-0123456789ab"


def _list(**kw):
    l = {"number": 3, "title": "Pastāvīgi glabājamo elektronisko lietu uzskaites saraksts Nr. 3", "retention_kind": "Pastavigi",
         "medium": "E", "content_type": "Teksts", "transfer_year": 2031,
         "history": [{"darbiba": "Projekts", "kad": "2026-10-15T08:00:00"}, {"darbiba": "Apstiprinats", "kad": "2026-10-16T08:00:00", "lna_ref": "LNA-7"}],
         "lietas": [{"kartas_numurs": 1, "case_index": "1-13", "case_name": "Rīkojumi", "case_year": 2020, "date_from": date(2020, 1, 2),
                     "date_to": date(2020, 12, 30), "document_count": 4, "file_count": 6, "series_idx": "1", "case_id": CID,
                     "default_info_status": "IerobezotasPieejamibas", "access_basis": "VDAL", "access_until": date(2045, 1, 1),
                     "sejumi": [{"number": 1, "medium": "E"}, {"number": 2, "medium": "P", "page_count": 12, "notes": "oriģināli"}]}]}
    l.update(kw)
    return l


def test_codes():
    assert fa.code(S) == "LV_LNA_LVA_F1234" and fa.code(S, 3, 1) == "LV_LNA_LVA_F1234_3_1" and fa.code(S, 3, 1, 2).endswith("_3_1_2")
    assert fa.settings_problems({}) and not fa.settings_problems(S)


def test_list_xml_valid():
    root = etree.fromstring(fa.list_xml(ORG, S, _list(), [{"vardsUzvards": "Anna"}]))
    assert _xsd().validate(root.getroottree()), _xsd().error_log
    v = root.find(f"{{{ARK}}}Vieniba")
    assert v.findtext(f"{{{ARK}}}UzskaitesKods") == "LV_LNA_LVA_F1234_3_1" and v.find(f"{{{ARK}}}HibridasNorades") is not None
    assert v.findtext(f"{{{ARK}}}PiekluvesIerobezojums/{{{ARK}}}IerobezojumsLidz") == "2045-01-01"


def test_transfer_act_valid():
    p = {"id": 5, "package_name": "LV_LNA_LVA_F1234_3_GV1-1", "sha256": "a" * 64, "size_bytes": 1234, "lna_date": date(2026, 10, 20),
         "lna_decision": "Pienemts", "lna_ref": "LNA-PA-1", "report": {"dokumenti": 4, "kludas": [], "bridinajumi": ["x"]}}
    root = etree.fromstring(tr.transfer_act_xml(ORG, S, p, _list(), _list()["lietas"], {"vardsUzvards": "Vadītājs"}))
    assert root.findtext(f"{{{ARK}}}NodotoVienibuSkaits") == "1"


def test_builder_validator_roundtrip(tmp_path):
    src = tmp_path / "src"; (src / "d1").mkdir(parents=True)
    (src / "d1" / "a.pdf").write_bytes(b"%PDF-1.7 a"); (src / "d1" / "b.pdf").write_bytes(b"%PDF-1.7 b")
    doc = {"dokumenta_id": "LV-DOK:05-0000:2020:x", "arhiva_id": "c" * 40, "nosaukums": "Rīkojums", "datums": "2020-02-02",
           "registracijas_nr": "1-13/1", "grupa": "Ieksejais", "tips": "Rīkojums", "informacijas_statuss": "Visparpieejama",
           "tehniska_informacija": "2 datnes", "datnes": ["d1/a.pdf", "d1/b.pdf"]}
    spec = {"izveides_datums": "2026-10-15", "arhivs": {"kods": "LVA", "nosaukums": "LVA"}, "iestade": {"nosaukums": "TB", "registracijas_nr": "9"},
            "fonds": {"numurs": "1234", "nosaukums": "TB"}, "saraksts": {"numurs": "3", "nosaukums": "US 3"},
            "lietas": [{"nr": 1, "indekss": "1-13", "nosaukums": "Rīkojumi", "dokumenti": [doc]}]}
    root = builder.build(spec, tmp_path / "out", src)
    rep = validator.validate_path(Path(str(root) + ".zip"))
    assert rep["derigs"], rep["ieraksti"]
    assert (root / "LV_LNA_LVA" / "LV_LNA_LVA_F1234" / "LV_LNA_LVA_F1234_3" / "LV_LNA_LVA_F1234_3_1" / "LV_LNA_LVA_F1234_3_1_1.pax").is_dir()
