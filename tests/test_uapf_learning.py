"""Classifier reference data and precedent similarity (uapf/learning.py)."""
import pathlib
import pytest

from opendms.uapf import learning

KLAS = pathlib.Path("/home/claude/tb/temu-klasifikators/klasifikators.xml")


def test_parse_refs():
    r = learning.parse_refs("processgit:tiesibsargs/temu-klasifikators/klasifikators.xml, "
                            "processgit:tiesibsargs/organizacijas-registrs/strukturvienibas.xml")
    assert r["klasifikators.xml"] == "tiesibsargs/temu-klasifikators/klasifikators.xml"
    assert r["strukturvienibas.xml"].startswith("tiesibsargs/organizacijas-registrs/")


@pytest.mark.skipif(not KLAS.exists(), reason="klasifikators.xml not checked out")
def test_klasifikators_codes_carry_joma_and_kategorija():
    k = learning.parse_klasifikators(KLAS.read_bytes())
    by = {c["kods"]: c for c in k["kodi"]}
    assert by["23.E"]["joma"] == "BT" and by["23.E"]["kategorija"] == "23"
    assert by["23.B.A"]["kategorija"] == "23" and by["23.B.A"]["izvelams"]
    assert not by["23"]["izvelams"]
    assert learning._result_from_code(k, "23.B.A")["kategorijasNosaukums"] == "Bērna tiesības"
    assert learning._result_from_code(k, "nav") is None


def test_similar_texts_score_higher_than_unrelated():
    a = learning.stems("Skolā bērns tiek pazemots, skolotāji nereaģē, skolas vadība neatbild.")
    b = learning.stems("Bērns skolā regulāri pazemots; skolas vadība un skolotāji neko nedara.")
    c = learning.stems("Pašvaldība atteica sociālo pabalstu pensionāram bez pamatojuma.")
    assert learning.similarity(a, b) > learning.similarity(a, c)
    assert learning.similarity(a, a) == 1.0
