import asyncio
from pathlib import Path
from unittest import mock

import pytest
from lxml import etree

from opendms.intake import structured as S

F = Path(__file__).parent / "fixtures" / "iesniegums"
FILES = {"t/r/iesniegums-1.0.xsd": F / "iesniegums-1.0.xsd", "t/r/iesniegums-1.0.sch": F / "iesniegums-1.0.sch",
         "t/k/klasifikators.xml": F / "klasifikators.xml"}
SH = {"xsd": "t/r/iesniegums-1.0.xsd", "noteikumi": "t/r/iesniegums-1.0.sch", "klasifikators": "t/k/klasifikators.xml"}


async def _ff(ref):
    return FILES[ref].read_bytes()


def fields(**over):
    f = {"Iesniedzejs": {"PusesTips": "FiziskaPersona", "Vards": "Jānis", "Uzvards": "Paraugs",
                         "Kontakti": {"Epasts": "j@example.lv"}, "AtbildesVeids": "EPasts"},
         "Jautajums": {"Joma": "TV", "Iestade": [{"Nosaukums": "Paraugu pašvaldība"}], "NotikumaMenesis": "2026-09",
                       "Apraksts": "Ēkā nav uzbrauktuves, un dokumentus atteica pieņemt.", "Lugums": "Izvērtēt."},
         "IeprieksejieSoli": {"VersiesIestade": False, "Tiesvediba": "Ne"},
         "Apliecinajumi": {"InformacijaPatiesa": True, "IepaziniesArDatuApstradi": True}}
    for k, v in over.items():
        f[k] = {**f.get(k, {}), **v}
    return f


def run(f, atts=()):
    async def go():
        with mock.patch("opendms.uapf.learning.fetch_file", _ff):
            S._cache.clear()
            x = S.build(f, kanals="Portals", attachments=list(atts))
            return x, await S.validate(x, SH, await S.classifier(SH))
    return asyncio.run(go())


def test_valid_and_header_set_by_server():
    x, info = run(fields(Galvene={"Kanals": "EPasts"}))
    doc = etree.fromstring(x)
    assert doc.findtext("{urn:lv:tiesibsargs:iesniegums:1.0}Galvene/{urn:lv:tiesibsargs:iesniegums:1.0}Kanals") == "Portals"
    assert info["joma"] == "TV" and info["sender"]["name"] == "Jānis Paraugs"


def test_attachments_listed_with_hash():
    x, _ = run(fields(), [{"file_name": "foto.jpg", "data": b"abc", "apraksts": "Ieeja"}])
    assert b"<Sha256>ba7816bf" in x and b"<DatnesNosaukums>foto.jpg" in x


def test_code_must_belong_to_joma():
    with pytest.raises(S.InvalidSubmission) as e:
        run(fields(Jautajums={"Kods": "23.A"}))
    assert "nepieder" in e.value.errors[0]


def test_valid_code_returned():
    k = next(c for c in __import__("opendms.uapf.learning", fromlist=["x"]).parse_klasifikators(
        FILES["t/k/klasifikators.xml"].read_bytes())["kodi"] if c["joma"] == "TV" and c["izvelams"])
    _, info = run(fields(Jautajums={"Kods": k["kods"]}))
    assert info["kods"] == k["kods"] and info["kodaNosaukums"]


def test_messages_readable():
    with pytest.raises(S.InvalidSubmission) as e:
        run(fields(Iesniedzejs={"Kontakti": {}}, Jautajums={"Apraksts": "īss"}))
    errs = " | ".join(e.value.errors)
    assert "Apraksts: jābūt vismaz 20 zīmēm." in errs
    assert "Lai atbildi saņemtu e-pastā, jānorāda e-pasta adrese." in errs


def test_unknown_fields_ignored():
    f = fields()
    f["Cits"] = {"x": 1}
    f["Jautajums"]["Brivi"] = "nekas"
    x, _ = run(f)
    assert b"Cits" not in x and b"Brivi" not in x
