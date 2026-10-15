"""P2: reģistrācijas minimums un datņu formāti (lēmumi registracijas-minimums, datnu-formati)."""

from datetime import datetime, timezone

import pytest

from opendms.archive import registration as rg

OK = {"irLieta": True, "lietaAtverta": True, "irTermins": True, "irStatuss": True, "statuss": "Visparpieejama",
      "irPamatojums": False, "irDatums": True, "irVeids": True, "datnuFormatiDerigi": True}


def test_minimum_ok():
    assert rg.check_minimum(OK) == []


@pytest.mark.parametrize("change,msg", [
    ({"irLieta": False}, "Nav lietas"),
    ({"lietaAtverta": False}, "Lieta slēgta"),
    ({"irTermins": False}, "glabāšanas termiņa"),
    ({"irStatuss": False, "statuss": None}, "informācijas statusa"),
    ({"statuss": "IerobezotasPieejamibas"}, "tiesiskā pamatojuma"),
    ({"irVeids": False}, "dokumenta veida"),
    ({"datnuFormatiDerigi": False}, "formātā"),
])
def test_minimum_gaps(change, msg):
    t = rg.check_minimum({**OK, **change})
    assert len(t) == 1 and msg in t[0]


def test_restricted_with_basis_ok():
    assert rg.check_minimum({**OK, "statuss": "DienestaVajadzibam", "irPamatojums": True}) == []


@pytest.mark.parametrize("mime,name,signed,riciba", [
    ("application/pdf", "a.pdf", False, "Saglabat"),
    (None, "lēmums.edoc", True, "Saglabat"),
    ("application/octet-stream", "x.docx", False, "KonvertetPDFA"),
    ("application/msword", "x.doc", True, "Saglabat"),
    ("image/jpeg; q=1", "x.jpg", False, "Saglabat"),
    ("application/zip", "x.zip", False, "Noraidit"),
    (None, "bez-paplasinajuma", False, "Noraidit"),
])
def test_file_action(mime, name, signed, riciba):
    assert rg.file_action(mime, name, signed)["riciba"] == riciba


def test_inputs_inherit_status_from_scheme():
    doc = {"id": 1, "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc), "classification_id": None,
           "metadata": {"standartaPakotne": {"noteikumi": {"documentType": {"code": "IESN"}}}}}
    case = {"scheme_entry_id": 4, "status": "Atverta", "retention_kind": "Gadi"}
    entry = {"default_info_status": "IerobezotasPieejamibas", "access_basis": "Fizisko personu datu apstrādes likums"}
    v, files = rg.inputs(doc, case, entry, [{"file_name": "iesniegums.pdf", "mime_type": "application/pdf"}])
    assert rg.check_minimum(v) == [] and v["statuss"] == "IerobezotasPieejamibas" and files[0]["derigs"]


def test_inputs_no_case():
    doc = {"id": 1, "created_at": datetime(2026, 3, 1, tzinfo=timezone.utc), "classification_id": 3, "metadata": "{}"}
    v, _ = rg.inputs(doc, None, None, [])
    assert rg.check_minimum(v) == ["Nav lietas no spēkā esošās klasifikācijas shēmas", "Nav informācijas statusa"]
