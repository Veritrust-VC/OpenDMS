"""P4b: iznīcināšanas akts (5. pielikums) pret XSD; dzēšana bez S3 klienta."""

import asyncio
from datetime import date, datetime, timezone

from lxml import etree

from opendms.archive import destruction as ds
from opendms.archive.scheme import ARK

ORG = {"std_code": "05-0000", "name": "Tiesībsarga birojs", "reg_number": "90000055101"}
CID = "LV-LIETA:05-0000:2020:01928f3e-7b6a-7c3d-9e4f-0123456789ab"


def _act(**kw):
    a = {"number": "2026/1", "act_date": date(2026, 10, 15), "created_at": datetime(2026, 10, 15, tzinfo=timezone.utc),
         "ek_protocol_no": "EK-3", "ek_date": date(2026, 10, 14),
         "history": [{"darbiba": "Projekts", "kad": "2026-10-15T08:00:00+00:00"},
                     {"darbiba": "IzskatitsEK", "kad": "2026-10-15T09:00:00+00:00", "ek_protocol_no": "EK-3"},
                     {"darbiba": "NavJasaskano", "kad": "2026-10-15T09:10:00+00:00"},
                     {"darbiba": "Apstiprinats", "kad": "2026-10-15T09:20:00+00:00"},
                     {"darbiba": "Iznicinats", "kad": "2026-10-15T09:30:00+00:00"}],
         "lietas": [{"case_name": "Iesniegumi", "case_index": "1-12", "case_year": 2020, "date_from": date(2020, 1, 3),
                     "date_to": date(2020, 12, 20), "dokumenti": 12, "datnes": 20, "retention_kind": "Gadi", "retention_years": 5,
                     "retention_legal_basis": "Iesniegumu likums", "case_id": CID},
                    {"case_name": "Sarakste", "case_index": "2.3", "case_year": 2020, "date_from": None, "date_to": None,
                     "dokumenti": 0, "datnes": 0, "retention_kind": "Gadi", "retention_years": 1, "case_id": CID}]}
    a.update(kw)
    return a


def test_act_xml_valid():
    root = etree.fromstring(ds.act_xml(ORG, {"fonds_number": "1234"}, _act(), [{"vardsUzvards": "Anna", "amats": "Lietvede"}]))
    assert root.findtext(f"{{{ARK}}}FondaNumurs") == "1234"
    assert {k.get("mervieniba"): k.text for k in root.findall(f"{{{ARK}}}Kopskaits")} == {"dokumenti": "12", "datnes": "20"}
    assert [s.findtext(f"{{{ARK}}}Statuss") for s in root.findall(f"{{{ARK}}}Saskanosana")] == ["Projekts", "IzskatitsEK", "NavJasaskano", "Apstiprinats"]
    assert root.find(f"{{{ARK}}}IznicinasanasAtzime") is None


def test_act_xml_with_destruction_mark():
    a = _act(destroyed_at=datetime(2026, 10, 15, 9, 30, tzinfo=timezone.utc), _destroyer={"vardsUzvards": "Vadītājs"})
    root = etree.fromstring(ds.act_xml(ORG, {}, a, []))
    assert root.findtext(f"{{{ARK}}}IznicinasanasAtzime/{{{ARK}}}Datums") == "2026-10-15"


def test_purge_without_versions():
    class St:
        deleted = []

        async def delete(self, k):
            self.deleted.append(k)
            return True
    st = St()
    assert asyncio.run(ds._purge(st, "a/b.pdf")) == 1 and st.deleted == ["a/b.pdf"]


def test_purge_all_versions():
    calls = []

    class C:
        def list_object_versions(self, Bucket, Prefix):
            return {"Versions": [{"Key": "k", "VersionId": "1"}, {"Key": "k", "VersionId": "2"}, {"Key": "k2", "VersionId": "9"}],
                    "DeleteMarkers": [{"Key": "k", "VersionId": "3"}]}

        def delete_object(self, **kw):
            calls.append(kw)

    class St:
        client, bucket = C(), "b"
    assert asyncio.run(ds._purge(St(), "k")) == 3 and {c["VersionId"] for c in calls} == {"1", "2", "3"}
