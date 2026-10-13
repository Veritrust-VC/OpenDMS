"""Semantic description helpers (opendms.semantics)."""
import json
import pathlib

import pytest

from opendms.semantics import dsf, service

DSF = pathlib.Path("/home/claude/dsf")
pytestmark = pytest.mark.skipif(not DSF.exists(), reason="format repository not checked out")


MAPPING = [{"kods": "23", "nosaukums": "Bērna tiesības", "eurovoc": "3916", "eurovoc_nosaukums": "bērnu tiesības"},
           {"kods": "26", "nosaukums": "Diskriminācija", "eurovoc": "688", "eurovoc_nosaukums": "vienāda attieksme"}]


def fmt():
    m = dsf.load(DSF)
    prof = m["profili"]["iesniegums"]
    return {"root": DSF, "repo": "vdvc/dokumentu-semantikas-formats", "revision": "test", "model": m,
            "profile": prof, "prompt": (DSF / prof["uzvedne"]).read_text().split("\n---\n", 1)[-1],
            "schemas": {l: json.loads((DSF / f"shemas/semantika-{l}.schema.json").read_text()) for l in ("lokals", "centrals")},
            "class_scheme": {"uri": "urn:lv:paraugiestade:klasifikators:1.0"}, "mapping": MAPPING,
            "eurovoc_candidates": {r["eurovoc"]: r["eurovoc_nosaukums"] for r in MAPPING}}


def test_prompt_has_no_unfilled_placeholders():
    p = service.build_prompt(fmt(), "=== LAPA 1 ===\nTeksts")
    assert "{{" not in p and "iesnieguma-prieksmets" in p and "`3916` — bērnu tiesības" in p


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
    assert t["shema"] == "urn:lv:paraugiestade:klasifikators:1.0" and t["kods"] == "26.H.A"


def test_central_semantics_replace_the_local_section_in_the_register_projection():
    from lxml import etree
    from opendms.standard.central import attach_semantics, project
    m = dsf.load(DSF)
    local = json.loads((DSF / "piemeri/iesniegums-lokals.json").read_text())
    M = "urn:lv:vdvc:dokumentu-metadati:2.0"
    root = etree.Element(f"{{{M}}}DokumentaPakotne", nsmap={None: M})
    d = etree.SubElement(root, f"{{{M}}}Dokuments")
    etree.SubElement(d, f"{{{M}}}DokumentaID").text = local["dokuments"]["id"]
    etree.SubElement(d, f"{{{M}}}SemantiskaisKopsavilkums").append(dsf.to_xml(local, m))
    p = project(etree.tostring(root), "pilns")
    assert "SemantiskaisKopsavilkums" not in json.dumps(p["metadata"])
    central = json.loads((DSF / "piemeri/iesniegums-centrals.json").read_text())
    q = attach_semantics(p, central)
    assert q["metadata"]["Dokuments"]["SemantiskaisKopsavilkums"]["slanis"] == "centrals"
    assert q["sha256"] != p["sha256"]
