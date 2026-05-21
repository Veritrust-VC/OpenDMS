"""
Parse a UAPF .uapf package (zip) and return a structured summary.

Used by the Demo Console UI to show:
- Process name, purpose, version, EU AI Act classification
- All BPMN steps with their capability bindings
- All DMN decision tables with their rules and outputs
- The trigger status (active/inactive) and the matched event

The parser is intentionally tolerant: a step or rule that can't be read
still appears in the output with reduced detail rather than failing the
whole request. This is what makes the demo robust to ProcessGit edits
that may introduce slightly malformed XML.
"""

from __future__ import annotations
import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The api container mounts /home/OpenDMS/uapf-packages → /uapf-packages:ro
PACKAGES_DIR = Path("/uapf-packages")

# Human-friendly description for each capability the demo package uses.
# Drawn from the UAPF capability catalog. Editing here only affects the
# Demo Console explanation panel; runtime semantics live in handlers.py.
CAPABILITY_DESCRIPTIONS = {
    "document.fetch@1": "Lasa dokumenta saturu un metadatus no DMS, kā arī piesaistītos failus.",
    "ai.redact@1": "Aizklāj personu identificējošu informāciju (vārdi, personas kodi, adreses) pirms turpmākās AI apstrādes.",
    "ai.extract@1": "Strukturēti izvelk faktus un pazīmes no maskētā teksta — vai pieminēti bērni, vai notiek pārkāpums, kāda valoda, u.c.",
    "data.write@1": "Saglabā lēmuma rezultātu OpenDMS datu bāzē kā audit-trail ierakstu.",
    "event.emit@1": "Publicē CloudEvents notikumu, ko var saņemt citas sistēmas (lietu vadība, statistika, u.c.).",
}


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag.split(":", 1)[-1]


def _read(z: zipfile.ZipFile, name: str) -> Optional[str]:
    try:
        return z.read(name).decode("utf-8")
    except KeyError:
        return None
    except Exception as e:
        logger.warning("Failed to read %s from package: %s", name, e)
        return None


# ─────────────────────────────────────────────────────────────
# BPMN parsing
# ─────────────────────────────────────────────────────────────

def _parse_bpmn(xml_text: str) -> dict[str, Any]:
    """Extract process name + ordered list of executable steps."""
    proc_match = re.search(
        r'<\w*:?process\s+id="([^"]+)"\s+name="([^"]+)"', xml_text,
    )
    process_id = proc_match.group(1) if proc_match else "?"
    process_name = proc_match.group(2) if proc_match else "?"

    # Find each task: match the open tag, then find the matching close tag for
    # the SAME element name (so we read exactly one task body, never bleeding
    # into the next one).
    task_open_re = re.compile(
        r'<(\w+:)?(serviceTask|businessRuleTask|userTask|task)\s+([^>/]*?)(/?)>',
    )
    cap_re = re.compile(r'(?:uapf:capability|invokedCapability)="([^"]+)"')
    cap_elem_re = re.compile(
        r'<\w*:?capability[^>]*>([^<]+)</\w*:?capability>',
    )
    decision_ref_re = re.compile(
        r'(?:uapf:decision|camunda:decisionRef|decisionRef)="([^"]+)"',
    )

    steps = []
    for m in task_open_re.finditer(xml_text):
        prefix = m.group(1) or ""
        typ = m.group(2)
        attrs_blob = m.group(3)
        self_closing = m.group(4) == "/"

        id_m = re.search(r'id="([^"]+)"', attrs_blob)
        name_m = re.search(r'name="([^"]+)"', attrs_blob)
        if not id_m:
            continue
        step_id = id_m.group(1)
        step_name = name_m.group(1) if name_m else step_id

        # Body: from the end of the open tag to the matching close tag
        if self_closing:
            body = ""
        else:
            close_tag = f"</{prefix}{typ}>"
            close_idx = xml_text.find(close_tag, m.end())
            body = xml_text[m.end():close_idx] if close_idx > 0 else ""

        cap = None
        # Look in both attributes and body for the capability binding
        m_cap = cap_re.search(attrs_blob) or cap_re.search(body)
        if m_cap:
            cap = m_cap.group(1)
        else:
            m_cap_elem = cap_elem_re.search(body)
            if m_cap_elem:
                cap = m_cap_elem.group(1).strip()

        decision_ref = None
        m_dec = decision_ref_re.search(attrs_blob) or decision_ref_re.search(body)
        if m_dec:
            decision_ref = m_dec.group(1)

        steps.append({
            "id": step_id,
            "name": step_name,
            "type": typ,
            "capability": cap,
            "decisionRef": decision_ref,
            "description": CAPABILITY_DESCRIPTIONS.get(cap) if cap else None,
        })

    return {
        "id": process_id,
        "name": process_name,
        "steps": steps,
    }


# ─────────────────────────────────────────────────────────────
# DMN parsing
# ─────────────────────────────────────────────────────────────

def _parse_dmn(xml_text: str) -> dict[str, Any]:
    """Extract a single decision table: inputs, outputs, rules."""
    decision_match = re.search(
        r'<\w*:?decision\s+([^>]*?)>', xml_text,
    )
    decision_id, decision_name = "?", "?"
    if decision_match:
        attrs = decision_match.group(1)
        id_m = re.search(r'id="([^"]+)"', attrs)
        name_m = re.search(r'name="([^"]+)"', attrs)
        if id_m: decision_id = id_m.group(1)
        if name_m: decision_name = name_m.group(1)

    hit_policy_m = re.search(r'hitPolicy="([^"]+)"', xml_text)
    hit_policy = hit_policy_m.group(1) if hit_policy_m else "UNIQUE"

    # Inputs: in declaration order
    input_blocks = re.findall(
        r'<\w*:?input\s+id="[^"]*"\s+label="([^"]+)"[^>]*>(.+?)</\w*:?input>',
        xml_text, re.DOTALL,
    )
    inputs = []
    for label, body in input_blocks:
        expr_m = re.search(r'<\w*:?text>([^<]+)</\w*:?text>', body)
        type_m = re.search(r'typeRef="([^"]+)"', body)
        inputs.append({
            "label": label,
            "expression": expr_m.group(1).strip() if expr_m else None,
            "type": type_m.group(1) if type_m else "string",
        })

    # Outputs
    output_re = re.compile(
        r'<\w*:?output\s+id="[^"]*"\s+(?:label="([^"]+)"\s+)?name="([^"]+)"\s+typeRef="([^"]+)"',
    )
    outputs = []
    for m in output_re.finditer(xml_text):
        outputs.append({
            "label": m.group(1) or m.group(2),
            "name": m.group(2),
            "type": m.group(3),
        })

    # Rules
    rule_re = re.compile(
        r'<\w*:?rule\s+id="([^"]+)">(.+?)</\w*:?rule>',
        re.DOTALL,
    )
    rules = []
    for m in rule_re.finditer(xml_text):
        rule_id = m.group(1)
        body = m.group(2)
        desc_m = re.search(r'<\w*:?description>([^<]+)</\w*:?description>', body)
        ins = re.findall(
            r'<\w*:?inputEntry[^>]*>\s*<\w*:?text>([^<]*)</\w*:?text>',
            body,
        )
        outs = re.findall(
            r'<\w*:?outputEntry[^>]*>\s*<\w*:?text>([^<]*)</\w*:?text>',
            body,
        )
        # Strip surrounding quotes from string output values for cleaner display
        outs = [o.strip('"') if o.startswith('"') and o.endswith('"') else o for o in outs]
        rules.append({
            "id": rule_id,
            "description": desc_m.group(1).strip() if desc_m else None,
            "when": ins,  # parallel to inputs
            "then": outs,  # parallel to outputs
        })

    return {
        "id": decision_id,
        "name": decision_name,
        "hitPolicy": hit_policy,
        "inputs": inputs,
        "outputs": outputs,
        "rules": rules,
    }


# ─────────────────────────────────────────────────────────────
# Package parsing (combines manifest + BPMN + DMNs)
# ─────────────────────────────────────────────────────────────

def _semver_key(name: str) -> tuple:
    """Sort key for filenames like '{id}-1.2.3.uapf' — newest sorts highest."""
    m = re.search(r"-(\d+)\.(\d+)\.(\d+)(?:[-+][^.]*)?\.uapf$", name)
    if not m:
        return (0, 0, 0, name)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), name)


def find_package_file(package_id: str) -> Optional[Path]:
    """Find the .uapf file in PACKAGES_DIR for the given package id.

    Accepts two filename forms:
      - {id}-{semver}.uapf   — versioned (manual builds)
      - {id}.uapf            — unversioned (engine writes this when it
                               installs from a ProcessGit archive URL)
    If multiple match, the highest semver wins; the unversioned form
    sorts as (0,0,0) so a versioned file beats it when both exist.
    """
    if not PACKAGES_DIR.exists():
        return None
    candidates = [
        p for p in PACKAGES_DIR.glob("*.uapf")
        if p.name == f"{package_id}.uapf"
        or p.name.startswith(f"{package_id}-")
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda p: _semver_key(p.name))
    return candidates[-1]


def inspect_package(package_id: str) -> Optional[dict[str, Any]]:
    """Return enriched info about a package, or None if it can't be found."""
    path = find_package_file(package_id)
    if not path:
        return None

    info: dict[str, Any] = {"packageId": package_id, "source_file": path.name}

    with zipfile.ZipFile(path) as z:
        # Manifest
        manifest_raw = _read(z, "manifest.json")
        if manifest_raw:
            try:
                info["manifest"] = json.loads(manifest_raw)
            except Exception as e:
                info["manifest_error"] = str(e)

        # BPMN — assume single process per package
        bpmn_path = next(
            (n for n in z.namelist() if n.startswith("bpmn/") and n.endswith((".bpmn", ".bpmn.xml"))),
            None,
        )
        if bpmn_path:
            bpmn_raw = _read(z, bpmn_path)
            if bpmn_raw:
                info["process"] = _parse_bpmn(bpmn_raw)

        # DMNs
        decisions = []
        for name in sorted(z.namelist()):
            if name.startswith("dmn/") and name.endswith((".dmn", ".dmn.xml")):
                raw = _read(z, name)
                if raw:
                    try:
                        decisions.append(_parse_dmn(raw))
                    except Exception as e:
                        logger.warning("DMN parse error in %s: %s", name, e)
                        decisions.append({"file": name, "error": str(e)})
        info["decisions"] = decisions

        # Docs (just the headers and first paragraph for the demo)
        docs = []
        for name in sorted(z.namelist()):
            if name.startswith("docs/") and name.endswith(".md"):
                raw = _read(z, name)
                if raw:
                    lines = raw.split("\n", 60)
                    title = lines[0].lstrip("# ").strip() if lines else name
                    body = "\n".join(lines[1:30]).strip()
                    docs.append({"file": name, "title": title, "body_preview": body})
        info["docs"] = docs

    return info
