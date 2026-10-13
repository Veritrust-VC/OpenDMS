"""Semantic description helpers (opendms.semantics)."""
import json
import pathlib

import pytest

from opendms.semantics import dsf, service

DSF = pathlib.Path("/home/claude/dsf")
pytestmark = pytest.mark.skipif(not DSF.exists(), reason="format repository not checked out")


def fmt():
    m = dsf.load(DSF)
    prof = m["profili"]["iesniegums"]
    return {"root": DSF, "repo": "vdvc/dokumentu-semantikas-formats", "revision": "test", "model": m,
            "profile": prof, "prompt": (DSF / prof["uzvedne"]).read_text().split("\n---\n", 1)[-1],
            "schemas": {l: json.loads((DSF / f"shemas/semantika-{l}.schema.json").read_text()) for l in ("lokals", "centrals")},
            "class_scheme": m["tematika"]["shemas"]["tiesibsargs-temas"]}


def test_prompt_has_no_unfilled_placeholders():
    p = service.build_prompt(fmt(), "=== LAPA 1 ===\nTeksts")
    assert "{{" not in p and "iesnieguma-prieksmets" in p and "`6230`" in p


def test_pages_and_quote_location():
    pages = service.split_pages("Pirmā lappuse par darbu.\fOtrā lappuse: Valsts darba inspekcijai rakstīju septembrī.")
    assert len(pages) == 2
    assert service.locate("Valsts darba inspekcijai rakstīju", pages) == {"lapa": 2, "sakums": 14, "beigas": 47, "metode": "precizs"}
    assert service.locate("[VĀRDS] rakstīja darba inspekcijai septembrī", pages)["lapa"] == 2


def test_category_maps_to_eurovoc():
    assert service._mapped_eurovoc(fmt(), "23")["kods"] == "3916"
    assert service._mapped_eurovoc(fmt(), "nav") is None


def test_institution_topic_uses_the_named_classifier():
    t = service._institution_topic(fmt(), {"kods": "26.H.A", "kodaNosaukums": "Diskriminācija invaliditātes dēļ"}, "cilveks")
    assert t["shema"] == "urn:lv:tiesibsargs:klasifikators:1.0" and t["kods"] == "26.H.A"


def test_central_semantics_replace_the_local_section_in_the_register_projection():
    from opendms.standard.central import attach_semantics, project
    xml = (DSF / "piemeri/metadati-13-sadala/metadati.xml").read_bytes()
    p = project(xml, "pilns")
    assert "SemantiskaisKopsavilkums" not in json.dumps(p["metadata"])
    central = json.loads((DSF / "piemeri/iesniegums-centrals.json").read_text())
    q = attach_semantics(p, central)
    docs = q["metadata"]["Dokuments"]
    docs = docs if isinstance(docs, list) else [docs]
    assert any((d.get("SemantiskaisKopsavilkums") or {}).get("slanis") == "centrals" for d in docs)
    assert q["sha256"] != p["sha256"]
