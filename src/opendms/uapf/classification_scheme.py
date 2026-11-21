"""
classification.lookup@1 against the institution's real classification scheme.

The scheme is read from ProcessGit, named by the binding's uapf:schemaRef:

    processgit:vdvc/vienotais-dokumentu-klasifikators/classification-v1-asis.xml,
    processgit:vdvc/vienotais-dokumentu-klasifikators/vocabularies.xml

(namespace urn:vdvc:classification:2026: domain › group › category, each category with
its retention and departmentRef; departments named in vocabularies.xml).

A language model chooses the single most specific category for the PII-redacted text;
the code is checked against the scheme, so the answer is always an existing case.
The output keeps the keys of the simulated lookup (klasifikacijasIndekss,
klasifikacijasNosaukums, strukturvieniba, glabasanasTermins), so the process and its
decision tables are unchanged. Without a schemaRef the simulated scheme is used.
"""

from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional

from opendms.uapf.learning import fetch_file, parse_refs, similar_precedents, _package_of

logger = logging.getLogger(__name__)

NS = "urn:vdvc:classification:2026"


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child_text(el, name: str) -> str:
    for c in el:
        if _local(c.tag) == name:
            return " ".join((c.text or "").split())
    return ""


def _dedupe_ns(xml: bytes) -> bytes:
    """The published scheme repeats xmlns:vdvc on the root element (not well-formed XML);
    keep the first declaration so the file still parses."""
    head, sep, rest = xml.partition(b">") if xml.startswith(b"<?xml") else (b"", b"", xml)
    start = rest.find(b"<")
    end = rest.find(b">", start)
    tag = rest[start:end]
    decl = re.findall(rb'\sxmlns:vdvc="[^"]*"', tag)
    if len(decl) > 1:
        first = tag.find(decl[0]) + len(decl[0])
        tag = tag[:first] + tag[first:].replace(decl[0], b"")
    return head + sep + rest[:start] + tag + rest[end:]


def parse_scheme(xml: bytes) -> dict:
    """Every category (the level a document is filed in) with its path, unit and retention."""
    root = ET.fromstring(_dedupe_ns(xml))
    version = root.get("version") or ""
    variant = root.get("variant") or ""
    cats: list[dict] = []

    def walk(el, path: list[str]):
        for c in el:
            t = _local(c.tag)
            if t in ("domain", "group"):
                walk(c, path + [f"{c.get('code')} {_child_text(c, 'name')}".strip()])
            elif t == "category":
                ret = next((r for r in c if _local(r.tag) == "retention"), None)
                cats.append({
                    "kods": c.get("code"),
                    "nosaukums": _child_text(c, "name"),
                    "cels": " › ".join(path),
                    "vieniba": _child_text(c, "departmentRef"),
                    "glabasana": (ret.get("original") if ret is not None else "") or "",
                })
                walk(c, path + [f"{c.get('code')} {_child_text(c, 'name')}"])   # nested categories, if any
            elif t in ("domains", "groups", "categories"):
                walk(c, path)

    walk(root, [])
    return {"versija": f"{version} {variant}".strip(), "kategorijas": [c for c in cats if c["kods"]]}


def parse_departments(xml: bytes) -> dict[str, str]:
    root = ET.fromstring(xml)
    return {d.get("id"): _child_text(d, "name") for d in root.iter() if _local(d.tag) == "department" and d.get("id")}


async def reference(schema_ref: Optional[str]) -> Optional[dict]:
    refs = parse_refs(schema_ref)
    scheme_ref = next((r for f, r in refs.items() if f.startswith("classification")), None)
    if not scheme_ref:
        return None
    scheme = parse_scheme(await fetch_file(scheme_ref))
    vocab_ref = next((r for f, r in refs.items() if f.startswith("vocabularies")), None)
    scheme["vienibas"] = parse_departments(await fetch_file(vocab_ref)) if vocab_ref else {}
    scheme["avots"] = scheme_ref
    return scheme


PROMPT = """You file a document received by {org} into its classification scheme
(lietu klasifikācijas shēma, MK noteikumi Nr. 282).

You get the scheme as lines "code | case name | path", earlier corrections by staff
(precedents) and the PII-redacted document.

Rules:
- Choose the single most specific case code whose subject matches what the document is
  about and what the ministry must do with it (e.g. a request for state budget
  co-financing goes to the case for allocating those funds, not to a generic case).
- A case named for a specific programme, project or procedure is used only when the
  document belongs to that programme or procedure.
- If no subject-matter case fits, use the correspondence case (group "Sarakste") that
  matches the kind of sender (state institution, municipality, private person, foreign …).
- Precedents are binding: follow a precedent's corrected code when the situation matches.
- Answer only with a code that appears in the scheme.

Respond ONLY with JSON:
{"kods": "<code>", "parliecība": <0..1>, "pamatojums": "<one sentence in Latvian>",
 "precedents": <id of the precedent you followed, or null>}"""


async def lookup(ctx: dict, text: str) -> Optional[dict]:
    """Real-scheme lookup, or None when the binding names no scheme."""
    from opendms.ai import _complete_json
    from opendms.org_context import org_label

    ref = await reference(ctx.get("schema_ref"))
    if not ref:
        return None
    inp = ctx.get("input") or {}
    cats = {c["kods"]: c for c in ref["kategorijas"]}

    def out(c: dict, **extra) -> dict:
        unit_id = c.get("vieniba") or ""
        unit = ref["vienibas"].get(unit_id) or unit_id
        return {"klasifikacijasIndekss": c["kods"], "klasifikacijasNosaukums": c["nosaukums"],
                "klasifikacijasCels": c["cels"], "strukturvieniba": unit, "strukturvienibasKods": unit_id,
                "glabasanasTermins": c.get("glabasana") or "", "shema": ref["avots"],
                "shemasVersija": ref["versija"], "simulets": False, **extra}

    # ResolveUnit after ClassifyAgainstScheme: the case is already chosen — read its unit.
    known = str(inp.get("klasifikacijasIndekss") or "").strip()
    if known in cats and inp.get("simulets") is not True:
        return out(cats[known], atbilstiba=inp.get("atbilstiba"),
                   klasifikacijasPamatojums=inp.get("klasifikacijasPamatojums"))

    package_id = await _package_of(ctx.get("session_id"))
    precedents = await similar_precedents(package_id, text, kind="klasifikacija")
    prec_txt = "\n\n".join(
        f"Precedent {p['id']} (similarity {p['score']}):\n  text: {p['excerpt'][:400]}\n"
        f"  wrongly proposed: {(p['predicted'] or {}).get('klasifikacijasIndekss') or (p['predicted'] or {}).get('kods')}\n"
        f"  correct: {(p['corrected'] or {}).get('klasifikacijasIndekss') or (p['corrected'] or {}).get('kods')}\n"
        f"  why: {p['reason'] or '-'}" for p in precedents) or "(none)"
    lines = "\n".join(f"{c['kods']} | {c['nosaukums']} | {c['cels']}" for c in ref["kategorijas"])
    ans = await _complete_json(PROMPT.replace("{org}", await org_label()),
                               f"--- SCHEME ---\n{lines}\n\n--- PRECEDENTS ---\n{prec_txt}\n\n"
                               f"--- DOCUMENT ---\n{text[:12000]}\n--- END ---", max_tokens=600, timeout=120)
    code = str((ans or {}).get("kods") or "").strip()
    if code not in cats:
        logger.warning("classification.lookup: model gave %r, not a code in %s", code, ref["avots"])
        return {"klasifikacijasIndekss": "X", "klasifikacijasNosaukums": "Nav noteikts — jāklasificē manuāli",
                "strukturvieniba": "", "glabasanasTermins": "", "atbilstiba": 0.0, "shema": ref["avots"],
                "shemasVersija": ref["versija"], "simulets": False,
                "klasifikacijasPamatojums": "Modelis neatgrieza derīgu shēmas kodu."}
    try:
        conf = max(0.0, min(1.0, float((ans or {}).get("parliecība", (ans or {}).get("parlieciba", 0.7)))))
    except (TypeError, ValueError):
        conf = 0.7
    return out(cats[code], atbilstiba=round(conf, 2),
               klasifikacijasPamatojums=str((ans or {}).get("pamatojums") or "")[:500],
               precedenti=[p["id"] for p in precedents])
