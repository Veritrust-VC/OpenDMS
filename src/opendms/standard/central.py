"""
Projection of metadati.xml for the central document register.

The register (VDVC) keeps metadata for search and analysis across
institutions, but never personal data. This module turns the institution's
metadati.xml into a JSON projection with:
  - the personal elements removed (creator, sender, contacts, file names,
    storage paths),
  - personas kods, e-mail, phone and IBAN masked in every remaining text,
  - the description dropped when the process decides scope "bez-apraksta".
The register re-checks the same patterns and rejects the submission if any
remain.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from lxml import etree

# SemantiskaisKopsavilkums holds the institution's LOCAL semantic layer; the register gets
# the separately projected central layer instead (see attach_semantics).
REMOVED_ELEMENTS = {"Izveidotajs", "Iesniedzejs", "Kontakti", "DatnesNosaukums", "GlabasanasAtsauce",
                    "SemantiskaisKopsavilkums"}

MASKS = [
    (re.compile(r"\b[0-3]\d[01]\d\d{2}-?[0-2]\d{4}\b"), "[personas kods]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[e-pasts]"),
    (re.compile(r"\bLV\d{2}[A-Z]{4}[A-Z0-9]{13}\b"), "[konts]"),
    (re.compile(r"(?:\+371[\s-]?)?\b[2-6]\d{7}\b"), "[tālrunis]"),
]

SCOPES = ("pilns", "bez-apraksta")


def mask(text: str) -> tuple[str, int]:
    """Mask personal identifiers in a text value. A value that is only digits
    (file size, internal counter) is not treated as a phone number."""
    n = 0
    for rx, repl in MASKS:
        if repl == "[tālrunis]" and text.isdigit():
            continue
        text, k = rx.subn(repl, text)
        n += k
    return text, n


def _local(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _to_obj(el, stats: dict) -> Any:
    children = [c for c in el if isinstance(c.tag, str)]
    attrs = {f"@{_local(k)}": v for k, v in el.attrib.items()}
    if not children:
        text = (el.text or "").strip()
        text, n = mask(text)
        stats["masked"] += n
        return {**attrs, "#text": text} if attrs else text
    out: dict = dict(attrs)
    for c in children:
        name = _local(c.tag)
        if name in REMOVED_ELEMENTS:
            stats["removed"].append(name)
            continue
        val = _to_obj(c, stats)
        if name in out:
            if not isinstance(out[name], list):
                out[name] = [out[name]]
            out[name].append(val)
        else:
            out[name] = val
    return out


def project(metadata_xml: bytes, scope: str = "pilns") -> dict:
    """Return {"metadata": {...}, "removed": [...], "masked": n, "sha256": hex}."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}")
    root = etree.fromstring(metadata_xml)
    stats = {"removed": [], "masked": 0}
    obj = {_local(root.tag): _to_obj(root, stats)}
    body = obj[_local(root.tag)]
    doc = body.get("Dokuments") if isinstance(body, dict) else None
    if scope == "bez-apraksta" and isinstance(doc, dict) and "Apraksts" in doc:
        doc.pop("Apraksts")
        stats["removed"].append("Apraksts")
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {"metadata": body, "removed": sorted(set(stats["removed"])), "masked": stats["masked"],
            "sha256": hashlib.sha256(canonical).hexdigest()}


def attach_semantics(projection: dict, central_layer: dict) -> dict:
    """Put the central semantic layer (vdvc/dokumentu-semantikas-formats, JSON) into
    Dokuments.SemantiskaisKopsavilkums and recompute the hash."""
    body = projection["metadata"]
    docs = body.get("Dokuments")
    docs = docs if isinstance(docs, list) else [docs]
    want = (central_layer.get("dokuments") or {}).get("id")
    target = next((d for d in docs if isinstance(d, dict) and d.get("DokumentaID") == want), docs[0])
    if isinstance(target, dict):
        target["SemantiskaisKopsavilkums"] = central_layer
    canonical = json.dumps(body, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return {**projection, "metadata": body, "sha256": hashlib.sha256(canonical).hexdigest()}
