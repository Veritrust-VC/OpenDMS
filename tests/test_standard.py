"""Tests for opendms.standard — identifiers and document packages."""

from datetime import datetime, timezone

import pytest

from opendms.standard import package as pkg
from opendms.standard.ids import (
    document_did,
    make_id,
    org_code_kind,
    package_folder,
    parse_id,
    uuid7,
)


# ── identifiers ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("code,kind", [("05-0000", "vpk"), ("0052000", "atvk"), ("40003000000", "ur")])
def test_org_code_kinds(code, kind):
    assert org_code_kind(code) == kind


@pytest.mark.parametrize("code", ["LV.0012.0001", "5-0000", "005200", "400030000001", "", "21-00000"])
def test_org_code_rejects(code):
    with pytest.raises(ValueError):
        org_code_kind(code)


def test_uuid7_carries_timestamp():
    at = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
    u = uuid7(at)
    assert u[14] == "7" and u[19] in "89ab"
    assert int(u.replace("-", "")[:12], 16) == int(at.timestamp() * 1000)


def test_make_and_parse_id_round_trip():
    at = datetime(2026, 10, 12, 9, 30, tzinfo=timezone.utc)
    value = make_id("LV-DOK", "05-0000", at)
    parts = parse_id(value)
    assert value.startswith("LV-DOK:05-0000:2026:")
    assert parts["orgKind"] == "vpk" and parts["year"] == 2026 and parts["yearMatches"]
    assert parts["createdAt"] == at


def test_year_is_riga_time():
    # 31 Dec 23:30 UTC is already 1 January in Riga
    at = datetime(2025, 12, 31, 23, 30, tzinfo=timezone.utc)
    assert make_id("LV-DOK", "0052000", at).split(":")[2] == "2026"


def test_document_did_and_folder():
    doc = make_id("LV-DOK", "05-0000")
    did = document_did("did:web:ombud.pac.kis.gov.lv", doc)
    assert did == "did:web:ombud.pac.kis.gov.lv:doc:" + doc[len("LV-DOK:"):]
    assert document_did("did:web:example.org", doc) is None
    assert package_folder(doc) == doc.replace(":", "_")


# ── package ───────────────────────────────────────────────────────────────

CREATED = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
ORG = {"id": 1, "std_code": "05-0000", "name": "Latvijas Republikas Tiesībsarga birojs",
       "org_did": "did:web:ombud.pac.kis.gov.lv", "reg_number": "90000055101"}


def _package(files_bytes=None):
    doc_uid = make_id("LV-DOK", "05-0000", CREATED)
    data = files_bytes or {"iesniegums.txt": "Iesnieguma teksts".encode("utf-8")}
    files = [{"std_id": make_id("LV-DATNE", "05-0000", CREATED), "file_name": n,
              "mime_type": "text/plain", "file_size": len(b), "checksum_sha256": pkg.sha256_hex(b),
              "is_primary": i == 0} for i, (n, b) in enumerate(data.items())]
    document = {"id": 7, "doc_uid": doc_uid, "title": "Iesniegums par piekļuvi informācijai",
                "content_summary": "Izdomāts iesniegums", "created_at": CREATED,
                "registration_number": "1-00001",
                "metadata": {"sender": {"type": "FiziskaPersona", "name": "Anna Paraudziņa",
                                        "email": "anna@example.lv"},
                             "receivedAt": "2026-10-12T08:55:00+00:00", "channel": "EPasts"}}
    rules = {"documentType": {"code": "IESN", "name": "Iesniegums"},
             "case": {"id": make_id("LV-LIETA", "05-0000", CREATED), "index": "1-12",
                      "name": "Iesniegumi", "year": 2026},
             "retention": {"years": 10, "trigger": "NoLietasSlegsanas", "disposition": "NodotArhivam"},
             "infoStatus": "IerobezotasPieejamibas", "personalData": True}
    events = pkg.standard_events([
        {"id": 1, "event_type": "DocumentCreated", "created_at": CREATED, "actor_id": 3, "details": {}},
        {"id": 2, "event_type": "iesniegums.classified", "created_at": CREATED, "details": {}},
        {"id": 3, "event_type": "DokumentsRegistrets", "created_at": CREATED, "actor_id": None,
         "details": {"registration_number": "1-00001"}},
    ])
    for e in events:
        e["std_id"] = make_id("LV-NOT", "05-0000", e["created_at"])
    users = {3: {"id": 3, "email": "lietvede@tiesibsargs.lv", "full_name": "Lietvede Paraugs"}}
    meta = pkg.build_metadata_xml(org=ORG, document=document, files=files, rules=rules,
                                  creator=users[3], system={"instance": "ombud.pac.kis.gov.lv"},
                                  generated_at=CREATED)
    track = pkg.build_tracking_xml(org=ORG, document=document, events=events, users=users,
                                   generated_at=CREATED)
    return pkg.assemble(meta, track, data), events


def test_event_mapping_drops_domain_events_and_tracks_status():
    _, events = _package()
    assert [e["std_type"] for e in events] == ["DokumentsIzveidots", "DokumentsRegistrets"]
    assert events[1]["status_from"] == "Projekts" and events[1]["status_to"] == "Registrets"


def test_package_is_valid():
    package, _ = _package({"iesniegums.txt": b"a", "pielikums.txt": b"bb"})
    assert set(package) == {"metadati.xml", "izsekosana.xml", "datnes/iesniegums.txt",
                            "datnes/pielikums.txt", "SHA256SUMS"}
    assert pkg.validate(package) == []


def test_validation_catches_tampered_file():
    package, _ = _package()
    package["datnes/iesniegums.txt"] = b"changed"
    problems = pkg.validate(package)
    assert any("checksum" in p for p in problems)
    assert any("SHA256SUMS" in p for p in problems)


def test_validation_catches_schema_error():
    package, _ = _package()
    package["metadati.xml"] = package["metadati.xml"].replace(b"05-0000", b"LV.0005.0000", 1)
    assert any(p.startswith("metadati.xml") for p in pkg.validate(package))


# ── package file access ────────────────────────────────────────────────────

def test_package_file_serves_only_listed_paths(monkeypatch):
    import asyncio
    from opendms.standard import service

    async def fake_info(doc_id):
        return "LV-DOK_05-0000_2026_x", ["metadati.xml", "datnes/a.docx", "SHA256SUMS"]

    class Store:
        async def get(self, key):
            return b"<x/>" if key.endswith("metadati.xml") else None

    monkeypatch.setattr(service, "_package_info", fake_info)
    monkeypatch.setattr(service, "get_storage", lambda: Store())
    data, media = asyncio.run(service.package_file(1, "metadati.xml"))
    assert data == b"<x/>" and media == "application/xml"
    for bad in ["../../etc/passwd", "datnes/../metadati.xml", "other.xml"]:
        with pytest.raises(LookupError):
            asyncio.run(service.package_file(1, bad))
