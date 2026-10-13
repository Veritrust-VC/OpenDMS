"""
(Vendored from vdvc/dokumentu-semantikas-formats tools/dsf.py — keep in sync.)

Dokumentu semantikas formāts — atsauces īstenojums.

Bez ārējām atkarībām, izņemot PyYAML (modeļa lasīšanai), lxml (XML) un, pārbaudei,
jsonschema. DVS un reģistrs var lietot šo moduli tieši vai īstenot to pašu pēc docs/.

  model = load(root)                       # modelis + vārdnīca + tēmu shēmas + profili
  xml   = to_xml(obj, model)               # JSON -> XML (metadati.xml 13. sadaļai)
  obj   = from_xml(xml, model)             # XML -> JSON
  c, r  = project_central(obj, model)      # lokālais -> centrālais slānis + atskaite
  errs  = check(obj, model)                # struktūra (JSON Schema) + profils + de-identifikācija
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import yaml

SCALARS = {"teksts", "datums", "laiks", "skaitlis", "vesels", "bulis", "uri", "enum"}


# ─────────────────────────── modelis ───────────────────────────

def load(root: str | Path) -> dict:
    root = Path(root)
    m = yaml.safe_load((root / "modelis/kodols.yaml").read_text(encoding="utf-8"))
    m["vardnica"] = yaml.safe_load((root / "modelis/vardnica.yaml").read_text(encoding="utf-8"))
    m["tematika"] = yaml.safe_load((root / "tematika/shemas.yaml").read_text(encoding="utf-8"))
    m["eurovoc"] = yaml.safe_load((root / "tematika/eurovoc-izlase.yaml").read_text(encoding="utf-8"))
    m["profili"] = {}
    for p in sorted((root / "profili").glob("*/profils.yaml")):
        prof = yaml.safe_load(p.read_text(encoding="utf-8"))
        m["profili"][prof["profils"]] = prof
    return m


def fields(model: dict, cls: str) -> dict:
    return model["klases"][cls]["lauki"]


def is_class(model: dict, t: str) -> bool:
    return t in model["klases"]


def xml_name(field: str) -> str:
    return field[0].upper() + field[1:]


# ─────────────────────────── JSON <-> XML ───────────────────────────
# Konvencija (docs/05): objekts -> elements; lauks -> apakšelements ar lauka nosaukumu
# lielajā sākumburtā (vai atribūts, ja xml: atributs); saraksts -> ietverošs elements ar
# lauka nosaukumu un tajā elementi ar klases nosaukumu (skalāram — "Vertiba"); bulis -> true/false.

def _scalar_to_text(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def to_xml(obj: dict, model: dict):
    from lxml import etree
    ns = model["vardtelpa"]

    def el(parent, name):
        return etree.SubElement(parent, f"{{{ns}}}{name}") if parent is not None else etree.Element(f"{{{ns}}}{name}", nsmap={None: ns})

    def fill(node, cls, data):
        for f, spec in fields(model, cls).items():
            if f not in data or data[f] is None:
                continue
            v = data[f]
            t = spec["tips"]
            if spec.get("xml") == "atributs":
                node.set(f, _scalar_to_text(v))
                continue
            if spec.get("saraksts"):
                wrap = el(node, xml_name(f))
                for item in v:
                    if is_class(model, t):
                        fill(el(wrap, t), t, item)
                    else:
                        el(wrap, "Vertiba").text = _scalar_to_text(item)
            elif is_class(model, t):
                fill(el(node, xml_name(f)), t, v)
            else:
                el(node, xml_name(f)).text = _scalar_to_text(v)

    root = el(None, model["xml_saknes_elements"])
    fill(root, model["saknes_klase"], obj)
    return root


def _cast(text: str, t: str):
    if t == "bulis":
        return text == "true"
    if t == "vesels":
        return int(text)
    if t == "skaitlis":
        return float(text)
    return text


def from_xml(node, model: dict) -> dict:
    def local(tag):
        return tag.split("}", 1)[-1]

    def read(n, cls):
        out: dict = {}
        flds = fields(model, cls)
        for f, spec in flds.items():
            if spec.get("xml") == "atributs" and f in n.attrib:
                out[f] = _cast(n.attrib[f], spec["tips"])
        for c in n:
            if not isinstance(c.tag, str):
                continue
            name = local(c.tag)
            f = name[0].lower() + name[1:]
            spec = flds.get(f)
            if not spec:
                continue
            t = spec["tips"]
            if spec.get("saraksts"):
                out[f] = [read(i, t) if is_class(model, t) else _cast(i.text or "", t) for i in c if isinstance(i.tag, str)]
            elif is_class(model, t):
                out[f] = read(c, t)
            else:
                out[f] = _cast(c.text or "", t)
        return out

    return read(node, model["saknes_klase"])


# ─────────────────────────── centrālā projekcija ───────────────────────────

MASKS = [
    (re.compile(r"\b[0-3]\d[01]\d\d{2}-?[0-2]\d{4}\b"), "personas kods"),
    (re.compile(r"\b3[2-9]\d{4}-?\d{5}\b"), "personas kods (jaunais)"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "e-pasts"),
    (re.compile(r"\bLV\d{2}[A-Z]{4}[A-Z0-9]{13}\b"), "konta numurs"),
    (re.compile(r"(?:\+371[\s-]?)?\b[2-6]\d{7}\b"), "tālrunis"),
    (re.compile(r"\[(?:VĀRDS|VARDS|UZVĀRDS|PERSONAS KODS|ADRESE|TĀLRUNIS|E-PASTS|[A-ZĀČĒĢĪĶĻŅŠŪŽ -]{3,})\]"), "aizklāšanas vietturis"),
    (re.compile(r"\b\d{1,3}\s?(?:gadus|gadu|g\.)\s?(?:vecs|veca|vecam|vecai|vecu)\b", re.I), "precīzs vecums"),
    (re.compile(r"\b[A-ZĀČĒĢĪĶĻŅŠŪŽ][a-zāčēģīķļņšūž]+\s(?:iela|ielā|prospekts|prospektā|bulvāris|bulvārī)\s?\d+", re.U), "adrese"),
]


def text_findings(text: str) -> list[str]:
    out = []
    for rx, name in MASKS:
        if name == "tālrunis" and text.isdigit():
            continue
        if rx.search(text or ""):
            out.append(name)
    return out


def _generalise_time(v: str) -> str:
    return v[:7] if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v) else v


def _predicate_central(model: dict, profile: dict | None, code: str):
    for src in ((profile or {}).get("predikati") or {}, model["vardnica"].get("predikati") or {}):
        if code in src:
            return src[code].get("centrals", True)
    return True


def project_central(local: dict, model: dict) -> tuple[dict, dict]:
    """Lokālais slānis -> centrālais slānis. Atgriež (centrālais, atskaite)."""
    profile = model["profili"].get(str(local.get("profils", "")).split("/")[0])
    report = {"nonemti": [], "visparinati": 0, "atradumi": []}

    def walk(cls, data, path, owner=None):
        if not isinstance(data, dict):
            return data
        out = {}
        for f, spec in fields(model, cls).items():
            if f not in data:
                continue
            v = data[f]
            c = spec.get("centrals", True)
            p = f"{path}.{f}"
            if c is False:
                report["nonemti"].append(p)
                continue
            if c == "tikai-iestadei" and (owner or {}).get("tips") != "iestade":
                report["nonemti"].append(p)
                continue
            t = spec["tips"]
            if spec.get("saraksts"):
                items = []
                for i, item in enumerate(v or []):
                    if cls == "SemantiskaisApraksts" and f == "apgalvojumi":
                        if _predicate_central(model, profile, item.get("predikats")) is False:
                            report["nonemti"].append(f"{p}[{i}]")
                            continue
                    if cls == "SemantiskaisApraksts" and f == "paplasinajumi" and not item.get("centrals"):
                        report["nonemti"].append(f"{p}[{i}]")
                        continue
                    items.append(walk(t, item, f"{p}[{i}]", item) if is_class(model, t) else item)
                out[f] = items
            elif is_class(model, t):
                out[f] = walk(t, v, p, data)
            else:
                if c == "vispārināts":
                    g = _generalise_time(v)
                    if g != v:
                        report["visparinati"] += 1
                    v = g
                out[f] = v
        return out

    central = walk(model["saknes_klase"], copy.deepcopy(local), "$")
    # Laiku centrālajā slānī vispārina līdz mēnesim visiem apgalvojumiem
    for a in central.get("apgalvojumi") or []:
        lk = a.get("laiks")
        if lk:
            for k in ("datums", "no", "lidz"):
                if k in lk:
                    g = _generalise_time(lk[k])
                    if g != lk[k]:
                        report["visparinati"] += 1
                    lk[k] = g
            if lk.get("precizitate") == "diena":
                lk["precizitate"] = "menesis"
    central["slanis"] = "centrals"
    # Teksta pārbaudes visos centrālā slāņa tekstos
    for path, text in iter_texts(central):
        for name in text_findings(text):
            report["atradumi"].append({"vieta": path, "iemesls": name})
    central.setdefault("piekluve", {})
    central["piekluve"]["klase"] = "centrals-iestadem"
    central["piekluve"]["deidentifikacija"] = {
        "noteikumi": "deidentifikacija/1.0",
        "parbaudes": ["lauku-noņemšana", "laika-vispārināšana", "identifikatoru-paraugi"],
        "izmainas": len(report["nonemti"]) + report["visparinati"],
        "rezultats": "neatbilst" if report["atradumi"] else "atbilst",
    }
    return central, report


def iter_texts(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_texts(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_texts(v, f"{path}[{i}]")
    elif isinstance(obj, str):
        yield path, obj


# ─────────────────────────── pārbaude ───────────────────────────

def check(obj: dict, model: dict, schema: dict | None = None) -> list[str]:
    """Struktūra (ja dota JSON Schema) + profila noteikumi + centrālā slāņa teksti."""
    errs: list[str] = []
    if schema is not None:
        import jsonschema
        v = jsonschema.Draft202012Validator(schema)
        errs += [f"{'/'.join(map(str, e.path)) or '$'}: {e.message}" for e in v.iter_errors(obj)]
    prof_name = str(obj.get("profils", "")).split("/")[0]
    prof = model["profili"].get(prof_name)
    if not prof:
        return errs + [f"profils: nezināms profils '{prof_name}'"]
    voc = model["vardnica"]
    preds = {**(voc.get("predikati") or {}), **(prof.get("predikati") or {})}
    roles = set(voc.get("lomas") or {})
    groups = set(voc.get("grupas") or {})
    people = {d.get("id"): d for d in obj.get("dalibnieki") or []}
    for d in obj.get("dalibnieki") or []:
        if d.get("loma") not in roles:
            errs.append(f"dalibnieki/{d.get('id')}: nezināma loma '{d.get('loma')}'")
        if d.get("grupa") and d["grupa"] not in groups:
            errs.append(f"dalibnieki/{d.get('id')}: nezināma grupa '{d['grupa']}'")
        if d.get("tips") == "fiziska-persona" and (d.get("nosaukums") or d.get("identifikators")):
            errs.append(f"dalibnieki/{d.get('id')}: fiziskai personai nedrīkst būt nosaukums vai identifikators")
    claim_ids = set()
    for a in obj.get("apgalvojumi") or []:
        claim_ids.add(a.get("id"))
        p = preds.get(a.get("predikats"))
        if not p:
            errs.append(f"apgalvojumi/{a.get('id')}: nezināms predikāts '{a.get('predikats')}'")
        elif a.get("statuss") not in (p.get("statusi") or []):
            errs.append(f"apgalvojumi/{a.get('id')}: statuss '{a.get('statuss')}' nav atļauts predikātam '{a.get('predikats')}'")
        for k in ("subjekts", "apgalvo"):
            if a.get(k) not in people and a.get(k) != "dokuments":
                errs.append(f"apgalvojumi/{a.get('id')}: {k} '{a.get(k)}' nav dalībnieks")
        if obj.get("slanis") == "lokals" and not a.get("pieradijumi"):
            errs.append(f"apgalvojumi/{a.get('id')}: nav pierādījuma vietas")
    have = {a.get("predikats") for a in obj.get("apgalvojumi") or []}
    for req in prof.get("obligati_predikati") or []:
        if req not in have:
            errs.append(f"apgalvojumi: trūkst obligātā predikāta '{req}'")
    for ref in (obj.get("kopsavilkums") or {}).get("balstitsUz") or []:
        if ref not in claim_ids:
            errs.append(f"kopsavilkums.balstitsUz: '{ref}' nav apgalvojums")
    facets = prof.get("pazimes") or {}
    got = {}
    for f in obj.get("pazimes") or []:
        spec = facets.get(f.get("kods"))
        if not spec:
            errs.append(f"pazimes: nezināma pazīme '{f.get('kods')}'")
            continue
        allowed = set(groups) if spec.get("vertibas_no") == "vardnica.grupas" else set(spec.get("vertibas") or {})
        if f.get("vertiba") not in allowed:
            errs.append(f"pazimes/{f.get('kods')}: vērtība '{f.get('vertiba')}' nav atļauta")
        got[f.get("kods")] = got.get(f.get("kods"), 0) + 1
    for k, spec in facets.items():
        if spec.get("obligata") and k not in got:
            errs.append(f"pazimes: trūkst obligātās pazīmes '{k}'")
        if got.get(k, 0) > 1 and not spec.get("vairakas"):
            errs.append(f"pazimes/{k}: drīkst būt tikai viena vērtība")
    ev_uri = model["tematika"]["shemas"]["eurovoc"]["uri"]
    ev = [t for t in obj.get("temas") or [] if t.get("shema") == ev_uri]
    tp = prof.get("temas") or {}
    if len(ev) < tp.get("min_eurovoc", 1):
        errs.append("temas: vajag vismaz vienu EuroVoc tēmu")
    known = set(str(k) for k in (model["eurovoc"].get("koncepti") or {}))
    for t in ev:
        if str(t.get("kods")) not in known:
            errs.append(f"temas: EuroVoc '{t.get('kods')}' nav izlasē (tematika/eurovoc-izlase.yaml)")
    if obj.get("slanis") == "centrals":
        for path, text in iter_texts(obj):
            for name in text_findings(text):
                errs.append(f"{path}: centrālajā slānī atrasts — {name}")
    return errs
