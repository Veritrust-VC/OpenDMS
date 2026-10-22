"""Vīzas, iepazīšanās atzīmes, rezolūcijas → ark:DokumentaArhivaMetadati (XSD)."""

from datetime import datetime, timezone

from lxml import etree

from opendms.archive import marks as mk
from opendms.archive.scheme import ARK, _xsd

P = {"lietotajaId": "a@x.lv", "vardsUzvards": "Anna Bērziņa", "amats": "Juriste", "strukturvieniba": "Juridiskā nodaļa"}
T = datetime(2026, 10, 15, 9, 0, tzinfo=timezone.utc)


def _doc(marks):
    A = lambda t: f"{{{ARK}}}{t}"
    root = etree.Element(A("DokumentaArhivaMetadati"), nsmap={"ark": ARK})
    etree.SubElement(root, A("ArhivaID")).text = "a" * 40
    etree.SubElement(root, A("DokumentuGrupa")).text = "Sanemtais"
    mk.append_marks(root, marks)
    return root


def test_marks_valid_and_replaced_excluded():
    marks = {"vizas": [{"id": 1, "persona": P, "datums": T, "rezultats": "SaskanotsArIebildumiem", "piezimes": "precizēt 2. p.", "aizstats": True},
                       {"id": 2, "persona": P, "datums": T, "rezultats": "Saskanots", "aizstaj": 1, "aizstats": False}],
             "iepazisanas": [{"id": 3, "persona": {"vardsUzvards": "Jānis"}, "datums": T}],
             "rezolucijas": [{"id": 4, "persona": P, "datums": T, "piezimes": "steidzami",
                              "uzdevumi": [{"atbildigie": [P, {"vardsUzvards": "Ilze"}], "apraksts": "Sagatavot atbildi", "termins": "2026-10-30"}]}]}
    root = _doc(marks)
    assert _xsd().validate(root.getroottree()), _xsd().error_log
    vizas = root.findall(f"{{{ARK}}}Vizas/{{{ARK}}}Viza")
    assert len(vizas) == 1 and vizas[0].findtext(f"{{{ARK}}}Piezimes") == "Saskaņots"
    assert len(root.findall(f".//{{{ARK}}}Atbildigais")) == 2


def test_no_marks_valid():
    root = _doc({"vizas": [], "iepazisanas": [], "rezolucijas": []})
    assert _xsd().validate(root.getroottree())
