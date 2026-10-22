"""Klasifikācijas shēma: termiņu nolasīšana, izklājlapas imports, ark XML eksports/imports."""

from datetime import date, datetime

import pytest

from opendms.archive import scheme as sch


@pytest.mark.parametrize("text,kind,years,marks", [
    ("Pastāvīgi", "Pastavigi", None, []),
    ("pastāvīgi", "Pastavigi", None, []),
    ("P", "Pastavigi", None, []),
    ("10 g.", "Gadi", 10, []),
    ("5 g. EK", "Gadi", 5, ["EK"]),
    ("75 gadi", "Gadi", 75, []),
    ("3 g. AI", "Gadi", 3, ["AI"]),
    (10, "Gadi", 10, []),
    ("10", "Gadi", 10, []),
])
def test_parse_retention(text, kind, years, marks):
    r = sch.parse_retention(text)
    assert r["ok"] and r["kind"] == kind and r["years"] == years and r["marks"] == marks


@pytest.mark.parametrize("text", ["", None, "līdz nepieciešamībai", "kamēr aktuāls"])
def test_parse_retention_unreadable(text):
    r = sch.parse_retention(text)
    assert not r["ok"] and r["warning"]


ROWS = [
    ["Parauga iestāde (SINTĒTISKS)"],
    ["Lietu klasifikācijas shēma 2027. gadam"],
    [],
    ["Indekss", "Lietas nosaukums", "Glabāšanas termiņš", "Pants vai normatīvais akts", "Atbildīgā struktūrvienība", "Informācijas vide", "Piezīmes"],
    ["1", "Vadība un administrācija", None, None, None, None, None],
    ["1.1", "Rīkojumi par pamatdarbību", "Pastāvīgi", "Arhīvu likums", "Juridiskā nodaļa", "E", None],
    ["1.2", "Sarakste ar iedzīvotājiem par iesniegumiem", "10 g.", None, "Lietvedība", "elektroniska", "personas dati"],
    ["2", "Personāls", None, None, None, None, None],
    ["2.1", "Darba līgumi", "75 g.", "Darba likums", "Personāldaļa", "papīrs", None],
    ["2.2", "Mācību materiāli", "5 g. EK", None, "Personāldaļa", "E", None],
    ["2.3", "Neskaidrs termiņš", "līdz nepieciešamībai", None, None, None, None],
    ["1.2", "Dublikāts", "1 g.", None, None, None, None],
    ["", "Bez indeksa", "1 g.", None, None, None, None],
]


def test_rows_to_entries():
    r = sch.rows_to_entries(ROWS)
    by = {e["idx"]: e for e in r["entries"]}
    assert r["summary"]["limeni"] == 2 and r["summary"]["lietas"] == 5
    assert by["1"]["kind"] == "limenis" and by["1.1"]["parent_idx"] == "1" and by["2.2"]["parent_idx"] == "2"
    assert by["1.1"]["retention_kind"] == "Pastavigi" and by["1.1"]["disposition"] == "NodotArhivam"
    assert by["1.2"]["retention_years"] == 10 and by["1.2"]["medium"] == "E"
    assert by["2.1"]["medium"] == "P" and by["2.1"]["retention_legal_basis"] == "Darba likums"
    assert by["2.2"]["retention_marks"] == ["EK"] and by["2.2"]["disposition"] == "Parskatit"
    assert by["2.3"]["retention_kind"] is None
    w = " ".join(r["warnings"])
    assert "2.3" in w and "atkārtojas" in w and "trūkst indeksa" in w


def test_rows_dash_index():
    rows = [["Indekss", "Nosaukums", "Termiņš"], ["1", "Iesniegumi", None], ["1-12", "Iesniegumi un sūdzības", "10 g."]]
    r = sch.rows_to_entries(rows)
    assert {e["idx"]: e["parent_idx"] for e in r["entries"]}["1-12"] == "1"


def test_no_header():
    with pytest.raises(sch.SchemeError):
        sch.rows_to_entries([["a", "b"], ["c", "d"]])


def _as_db(parsed):
    """Importētos ierakstus pārvērš DB ierakstu formā (id, parent_id)."""
    ids = {e["idx"]: i for i, e in enumerate(parsed["entries"], 1)}
    out = []
    for e in parsed["entries"]:
        d = {f: e.get(f) for f in sch.ENTRY_FIELDS}
        d.update(id=ids[e["idx"]], parent_id=ids.get(e.get("parent_idx")))
        d["retention_marks"] = d["retention_marks"] or []
        out.append(d)
    return out


def test_ark_xml_roundtrip():
    parsed = sch.rows_to_entries([r for r in ROWS if r and r[0] != "2.3"])
    entries = _as_db(parsed)
    scheme = {"id": 7, "period_from": date(2027, 1, 1), "period_to": date(2027, 12, 31), "version": "1",
              "status": "Projekts", "history": [{"statuss": "Projekts", "datums": "2026-10-15"}]}
    xml = sch.to_ark_xml(scheme, entries, {"std_code": "05-0000", "name": "Parauga iestāde"}, {"registration_number": "90000000000"})
    back = sch.parse_ark_xml(xml)
    assert back["summary"]["lietas"] == parsed["summary"]["lietas"]
    assert back["meta"]["period_from"] == "2027-01-01"
    b = {e["idx"]: e for e in back["entries"]}
    assert b["2.1"]["retention_years"] == 75 and b["2.1"]["parent_idx"] == "2"
    assert b["1.1"]["retention_kind"] == "Pastavigi"
    assert b["2.2"]["retention_marks"] == ["EK"]


def test_ark_xml_rejects_invalid():
    with pytest.raises(sch.SchemeError):
        sch.parse_ark_xml(b'<ark:KlasifikacijasShema xmlns:ark="urn:lv:kisc:arhivesana:1.0" id="x"/>')


def test_transitions_follow_p1():
    assert sch.TRANSITIONS["Projekts"] == {"IzskatitsEK"}
    assert "Apstiprinats" in sch.TRANSITIONS["SaskanotsLNA"] and "Apstiprinats" in sch.TRANSITIONS["NavJasaskano"]
    assert "Apstiprinats" not in sch.TRANSITIONS["IesniegtsLNA"]


@pytest.mark.parametrize("text,kind,years,until,trigger", [
    ("līdz 31.12.2039. EK", "LidzDatumam", None, date(2039, 12, 31), None),
    ("31.12.2030.", "LidzDatumam", None, date(2030, 12, 31), None),
    (datetime(2031, 12, 31), "LidzDatumam", None, date(2031, 12, 31), None),
    ("5 gadi pēc projekta noslēguma pārskata apstiprināšanas", "Gadi", 5, None, "NoNotikuma"),
    ("10 gadi EK pēc līguma termiņa beigām", "Gadi", 10, None, "NoNotikuma"),
    ("5gadi", "Gadi", 5, None, None),
    ("Pastāvīgi?", "Pastavigi", None, None, None),
])
def test_parse_retention_varam(text, kind, years, until, trigger):
    r = sch.parse_retention(text)
    assert r["ok"] and r["kind"] == kind and r["years"] == years and r["until"] == until and r["trigger"] == trigger


def test_sheets_varam_layout():
    hdr = [" Klasifikācijas shēmas līmeņa un lietas indekss", "Klasifikācijas indekss citas-centralizētu pakalpojumu sistēmas",
           "Klasifikācijas līmeņa nosaukums", "Lietas nosaukums", "Glabāšanas termiņš", "Atbildīgā struktūrvienība",
           "Informācijas nesēja forma (HL-hibrīdlieta, El-elektroniska)", "IS, kurā atrodas elektroniskie dokumenti", "Piezīmes/apraksts"]
    p = [[None, None, None, "2027. gada dokumentu klasifikācijas shēma"], hdr,
         ["P", None, "Pārvaldība", "Iestādes pārvaldība", None],
         ["P-1", None, "Iestādes vadība", "Iestādes vadība", "\xa0"],
         ["P-1-1", None, "Iestādes vadība", "Nolikums", "Pastāvīgi", "VARAM", "El", "DVS Namejs"],
         ["P-1-2", None, "Iestādes vadība", "Projekta lieta", None, "VARAM", "HL"],
         ["P-5-3-2 P-5-3-3", None, "x", "Nederīgs", "5 gadi"]]
    i = [hdr[:1] + hdr[2:], ["I1", "Investīciju programmu vadība", "Investīciju programmu vadība"],
         ["I1-1", "Investīciju programmu vadība", "Tiesiskais regulējums", "Pastāvīgi"],
         ["I1-1-1", "Investīciju programmu vadība", "Metodikas", "līdz 31.12.2039. EK", "IPD", "El"]]
    r = sch.sheets_to_entries([("P Pārvalde", p), ("I1 Investīciju", i), ("Sheet1", [hdr]), ("Saīsinājumi", [["N.p.k.", "Saīsinājums"]])])
    by = {e["idx"]: e for e in r["entries"]}
    assert set(by) == {"P", "P-1", "P-1-1", "P-1-2", "I1", "I1-1", "I1-1-1"}
    assert by["P-1-1"]["kind"] == "lieta" and by["P-1-1"]["medium"] == "E" and by["P-1-1"]["name"] == "Nolikums"
    assert by["P-1-1"]["information_system"] == "DVS Namejs" and by["P-1-1"]["parent_idx"] == "P-1"
    assert by["P-1-2"]["kind"] == "lieta" and by["P-1-2"]["retention_kind"] is None and by["P-1-2"]["medium"] == "H"
    assert by["I1-1"]["kind"] == "limenis" and "Termiņš līmenim" in by["I1-1"]["notes"]
    assert by["I1-1-1"]["retention_kind"] == "LidzDatumam" and by["I1-1-1"]["retention_until"] == date(2039, 12, 31)
    w = " ".join(r["warnings"])
    assert "Sheet1" in w and "Saīsinājumi" in w and "P-5-3-2 P-5-3-3" in w and "P-1-2" in w
    assert r["lapas"] == ["P Pārvalde", "I1 Investīciju"]
