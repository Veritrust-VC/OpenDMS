"""4e: adresāti, ark:DokumentaArhivaMetadati paplašinājumā, parakstīšanas pierādījumi — pilna pakotne pret abām shēmām."""

from datetime import datetime, timezone

from lxml import etree

from opendms.archive import docmeta as dm
from opendms.archive.scheme import ARK
from opendms.standard import package as pkg
from opendms.standard.ids import make_id

T = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)
P = {"lietotajaId": "a@x.lv", "vardsUzvards": "Anna Bērziņa", "amats": "Juriste"}
ORG = {"id": 1, "std_code": "05-0000", "name": "Tiesībsarga birojs", "org_did": "did:web:ombud.pac.kisc.gov.lv"}


def test_addressees_dedup_and_sources():
    meta = {"recipients": [{"name": "VARAM", "eAddress": "_DEFAULT@90000048472"}],
            "parsutisana": {"adresats": "_DEFAULT@90000048472", "adresataNosaukums": "VARAM", "statuss": "nosutits",
                            "vesture": [{"adresats": "_DEFAULT@1", "adresataNosaukums": "Tukuma novads", "statuss": "kluda"}]}}
    ev = [{"event_type": "DocumentSent", "details": {"recipient": "did:web:varam.pac.kisc.gov.lv"}, "created_at": T}]
    a = dm.addressees(meta, ev)
    assert [x["nosaukums"] for x in a] == ["VARAM", "did:web:varam.pac.kisc.gov.lv"]


def _doc(archive_id="b" * 40):
    return {"id": 9, "archive_id": archive_id, "content_summary": "Iesniegums par piekļuvi",
            "metadata": {"sender": {"name": "Jānis", "reference": "JB-7"}, "semantika": {"atslegvardi": ["piekļuve", " "]}}}


def test_archive_metadata_valid():
    marks = {"vizas": [{"id": 1, "persona": P, "datums": T, "rezultats": "Saskanots"}], "iepazisanas": [], "rezolucijas": []}
    ev = [{"event_type": dm.EV_SIGN, "created_at": T, "details": {}}]
    root = dm.archive_metadata(_doc(), ev, marks, [{"file_name": "a.docx", "mime_type": None}])
    g = lambda t: root.findtext(f"{{{ARK}}}{t}")  # noqa: E731
    assert g("DokumentuGrupa") == "Sanemtais" and g("NosutitajaDokumentaNr") == "JB-7"
    assert "PDF/A" in g("TehniskaInformacija") and "30. p." in g("TehniskaInformacija")


def test_full_package_with_extras():
    uid = make_id("LV-DOK", "05-0000", T)
    fid = make_id("LV-DATNE", "05-0000", T)
    data = {"lemums.pdf": b"%PDF-1.7 x"}
    files = [{"std_id": fid, "file_name": "lemums.pdf", "mime_type": "application/pdf", "file_size": len(data["lemums.pdf"]),
              "checksum_sha256": pkg.sha256_hex(data["lemums.pdf"]), "is_primary": True}]
    sign_ev = [{"event_type": dm.EV_SIGN, "created_at": T,
                "details": {"persona": P, "datnes": [{"datnesId": fid, "nosaukums": "lemums.pdf", "sha256": files[0]["checksum_sha256"]}]}}]
    marks = {"vizas": [], "iepazisanas": [{"id": 2, "persona": P, "datums": T}], "rezolucijas": []}
    extras = {"fonds": "1234", "addressees": [{"tips": "ValstsIestade", "nosaukums": "VARAM", "eAdrese": "_DEFAULT@90000048472",
                                               "did": "did:web:varam.pac.kisc.gov.lv"}],
              "signatures": [{"persona": P, "laiks": T, "datnes": [fid]}],
              "extension": dm.archive_metadata(_doc(), sign_ev, marks, files),
              "technical": {"parakstisana.xml": dm.signing_xml(uid, sign_ev)}}
    document = {"id": 9, "doc_uid": uid, "title": "Lēmums", "created_at": T, "registration_number": "1-00031", "metadata": {}}
    rules = {"documentType": {"code": "LEM", "name": "Lēmums"},
             "case": {"id": make_id("LV-LIETA", "05-0000", T), "index": "1-12", "name": "Iesniegumi", "year": 2026},
             "retention": {"years": 10}, "infoStatus": "Visparpieejama"}
    meta = pkg.build_metadata_xml(org=ORG, document=document, files=files, rules=rules, generated_at=T, extras=extras)
    events = pkg.standard_events([{"id": 1, "event_type": "DocumentCreated", "created_at": T, "details": {}},
                                  {"id": 2, "event_type": dm.EV_SIGN, "created_at": T, "actor_id": None, "details": {}}])
    for e in events:
        e["std_id"] = make_id("LV-NOT", "05-0000", T)
    track = pkg.build_tracking_xml(org=ORG, document=document, events=events, users={}, generated_at=T)
    package = pkg.assemble(meta, track, data, extras["technical"])
    assert pkg.validate(package) == []
    assert "parakstisana.xml" in package["SHA256SUMS"].decode()
    root = etree.fromstring(meta)
    ns = {"dm": pkg.NS_META, "ark": ARK}
    assert root.findtext(".//dm:Arhivs/dm:FondaNumurs", namespaces=ns) == "1234"
    assert root.findtext(".//dm:Adresati/dm:Adresats/dm:Kontakti/dm:EAdrese", namespaces=ns) == "_DEFAULT@90000048472"
    assert root.findtext(".//dm:Paraksti/dm:Paraksts/dm:ParakstaVeids", namespaces=ns) == "Vizesana"
    assert root.findtext(".//dm:Paplasinajumi/ark:DokumentaArhivaMetadati/ark:ArhivaID", namespaces=ns) == "b" * 40
    assert [e["std_type"] for e in events] == ["DokumentsIzveidots", "DokumentsParakstits"]
