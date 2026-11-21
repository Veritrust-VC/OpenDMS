import asyncio
from pathlib import Path
from unittest import mock

from opendms.uapf import classification_scheme as CS

F = Path(__file__).parent / "fixtures" / "vdvc"
FILES = {"vdvc/vienotais-dokumentu-klasifikators/classification-v1-asis.xml": F / "classification-v1-asis.xml",
         "vdvc/vienotais-dokumentu-klasifikators/vocabularies.xml": F / "vocabularies.xml"}
REF = ("processgit:vdvc/vienotais-dokumentu-klasifikators/classification-v1-asis.xml, "
       "processgit:vdvc/vienotais-dokumentu-klasifikators/vocabularies.xml")


async def _ff(ref):
    return FILES[ref].read_bytes()


def run(ctx, answer):
    async def go():
        with mock.patch.object(CS, "fetch_file", _ff), \
             mock.patch.object(CS, "similar_precedents", mock.AsyncMock(return_value=[])), \
             mock.patch.object(CS, "_package_of", mock.AsyncMock(return_value=None)), \
             mock.patch("opendms.ai._complete_json", mock.AsyncMock(return_value=answer)), \
             mock.patch("opendms.org_context.org_label", mock.AsyncMock(return_value="VARAM")):
            return await CS.lookup(ctx, "Pieteikums valsts budžeta līdzfinansējumam Interreg projektam")
    return asyncio.run(go())


def test_parse_scheme_has_case_level_codes():
    s = CS.parse_scheme((F / "classification-v1-asis.xml").read_bytes())
    codes = {c["kods"]: c for c in s["kategorijas"]}
    assert len(codes) > 400
    assert codes["I1-16-6"]["nosaukums"].startswith("Valsts budžeta līdzekļu piešķiršana Interreg")
    assert codes["I1-16-6"]["vieniba"] == "AID"
    assert codes["P-1-13-1"]["cels"].endswith("P-1-13 Sarakste")


def test_lookup_returns_case_with_unit_and_retention():
    r = run({"schema_ref": REF, "input": {}}, {"kods": "I1-16-6", "parliecība": 0.9, "pamatojums": "x"})
    assert r["klasifikacijasIndekss"] == "I1-16-6" and r["simulets"] is False
    assert r["strukturvieniba"] == "Attīstības instrumentu departaments" and r["strukturvienibasKods"] == "AID"
    assert r["glabasanasTermins"] == "2034-12-31 00:00:00"


def test_unknown_code_is_manual():
    r = run({"schema_ref": REF, "input": {}}, {"kods": "I9-99"})
    assert r["klasifikacijasIndekss"] == "X"


def test_resolve_unit_reuses_chosen_case_without_model():
    m = mock.AsyncMock()
    async def go():
        with mock.patch.object(CS, "fetch_file", _ff), mock.patch("opendms.ai._complete_json", m):
            return await CS.lookup({"schema_ref": REF, "input": {"klasifikacijasIndekss": "P-1-13-1", "simulets": False}}, "t")
    r = asyncio.run(go())
    assert r["klasifikacijasIndekss"] == "P-1-13-1" and not m.called


def test_no_schema_ref_falls_back():
    assert asyncio.run(CS.lookup({"input": {}}, "t")) is None
