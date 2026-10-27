"""Iesniegums as UAS e-submission 0.1 (tiesibsargs/iesnieguma-shema).

One builder for every way a submission becomes structured data:
  - the web form posts a JSON payload in the schema's shape,
  - the processing step `submission.structure@1` gets the same shape from the model,
  - a conversion from iesniegums-1.0 (tools/no-1-0.py in the schema repository).

The payload never sets identity, provenance or attachments: the server does,
from what it knows (channel, received time, signature, structuring method,
the files it actually received). Values are written in schema order; XSD and
Schematron then decide. Rule results are split by role: errors (E-…) make the
instance unusable, warnings (W-…) are legal incompleteness that the screening
step decides on — a submission is accepted even when incomplete (APL 56. p. 4. d.).

Channel config (ievade.yaml):
    shema:
      xsd: tiesibsargs/iesnieguma-shema/shemas/e-submission-0.1.xsd
      noteikumi: tiesibsargs/iesnieguma-shema/noteikumi/e-submission-0.1.sch
      klasifikators: tiesibsargs/temu-klasifikators/klasifikators.xml
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone
from typing import Any, Optional

from lxml import etree, isoschematron

NS = "urn:uas:esubmission:0.1"
SVRL = "http://purl.oclc.org/dsdl/svrl"
PROFILE = "lv.tiesibsargs"
RECIPIENT_CODE = "90000055101"   # Tiesībsarga birojs, reģ. nr.

DEFAULT_SHEMA = {
    "xsd": "tiesibsargs/iesnieguma-shema/shemas/e-submission-0.1.xsd",
    "noteikumi": "tiesibsargs/iesnieguma-shema/noteikumi/e-submission-0.1.sch",
    "klasifikators": "tiesibsargs/temu-klasifikators/klasifikators.xml",
}


def is_esubmission(shema: Optional[dict]) -> bool:
    return "e-submission" in ((shema or {}).get("xsd") or "")


# ── Schema order. A name ending in * repeats (list in the payload). ──────────
WHEN = [("date", None), ("yearMonth", None), ("year", None),
        ("period", [("from", None), ("to", None)]), ("ongoing", None)]
CONTACT = [("email", None), ("phone", None), ("eAddress", None)]
PARTY = [("id", None), ("role*", None), ("partyType", None), ("givenName", None), ("familyName", None),
         ("legalName", None), ("registrationNo", None), ("code", None), ("address", None),
         ("contact", CONTACT),
         ("representation", [("represents", None), ("basis", None), ("description", None), ("evidence", None)]),
         ("vulnerability*", None)]
FACT = [("id", None), ("when", WHEN), ("place", None), ("actor*", None), ("conduct", None),
        ("statement", None), ("basis", None), ("evidence*", None), ("sourceExcerpt", None)]
CLAIM = [("id", None), ("type", None), ("text", None), ("addressedTo", None), ("relatedFact*", None)]
STEP = [("type", None), ("addressedTo", None), ("date", None), ("responseReceived", None),
        ("responseDate", None), ("responseSummary", None), ("evidence*", None)]
BODY = [
    ("parties", [("party*", PARTY)]),
    ("narrative", [("summary", None), ("text", None)]),
    ("facts", [("fact*", FACT)]),
    ("rightsAffected", [("domain*", None), ("classifierCode*", None),
                        ("normativeReference*", [("eli", None), ("lawId", None), ("label", None)])]),
    ("claims", [("claim*", CLAIM)]),
    ("priorSteps", [("step*", STEP), ("court", [("status", None), ("caseNo", None), ("court", None)])]),
    ("privacy", [("doNotDiscloseIdentity", None), ("doNotDiscloseFacts", None),
                 ("noReplyNeeded", None), ("replyChannel", None)]),
]
LIMITS = {"summary": 1000, "text": 20000, "statement": 2000, "sourceExcerpt": 1000, "responseSummary": 1000}
LIMITS_200 = {"givenName", "familyName", "legalName", "address", "place", "eAddress", "label", "court",
              "description"}

CHANNELS = {"Portals": "portal", "EPasts": "email", "EAdrese": "eAddress", "Klatiene": "inPerson",
            "Pasts": "post", "DVSIntegracija": "a2a", "portal": "portal", "email": "email"}


class InvalidSubmission(ValueError):
    def __init__(self, errors: list[str], warnings: Optional[list[dict]] = None):
        super().__init__("; ".join(errors))
        self.errors = errors
        self.warnings = warnings or []


def _val(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    s = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(v)).strip()
    return s or None


def _clip(name: str, s: str) -> str:
    n = LIMITS.get(name) or (200 if name in LIMITS_200 else None)
    return s[:n] if n else s


def _emit(parent, spec, data: dict) -> None:
    for name, children in spec:
        many = name.endswith("*")
        name = name.rstrip("*")
        value = data.get(name) if isinstance(data, dict) else None
        items = value if many and isinstance(value, list) else ([value] if value is not None else [])
        for item in items:
            if children:
                if not isinstance(item, dict):
                    continue
                el = etree.Element(f"{{{NS}}}{name}")
                _emit(el, children, item)
                if len(el):
                    parent.append(el)
            else:
                s = _val(item)
                if s is not None:
                    etree.SubElement(parent, f"{{{NS}}}{name}").text = _clip(name, s)


WRAPPED = {"parties": "party", "facts": "fact", "claims": "claim"}


def _normalise(p: dict) -> dict:
    """The JSON may give parties/facts/claims as plain lists; the XML wraps them."""
    out = dict(p)
    for k, inner in WRAPPED.items():
        if isinstance(out.get(k), list):
            out[k] = {inner: out[k]}
    ps = out.get("priorSteps")
    if isinstance(ps, dict) and isinstance(ps.get("steps"), list) and "step" not in ps:
        out["priorSteps"] = {**ps, "step": ps["steps"]}
    return out


def _sub(parent, name, text=None):
    el = etree.SubElement(parent, f"{{{NS}}}{name}")
    if text is not None:
        el.text = text
    return el


def build(payload: dict, *, channel: str, attachments: list[dict] = (), received_at: Optional[str] = None,
          signature: str = "none", signers: list[str] = (), status: str = "received",
          structuring: Optional[dict] = None, source_document: Optional[dict] = None,
          declarations: Optional[dict] = None, document_id: Optional[str] = None,
          registration_no: Optional[str] = None) -> bytes:
    """Payload (JSON in the schema's shape) -> e-submission XML.

    attachments: [{file_name, mime_type, data | sha256, apraksts?, kind?}] — given ids a1, a2 …;
    the payload refers to them by those ids (facts/evidence, representation/evidence)."""
    p = payload or {}
    root = etree.Element(f"{{{NS}}}eSubmission", nsmap={None: NS})
    root.set("version", "0.1")
    root.set("profile", PROFILE)

    idn = _sub(root, "identity")
    types = [t for t in (p.get("submissionType") or []) if t in ("lugums", "sudziba", "prieksl", "jautajums")]
    for t in (types or ["lugums"])[:4]:
        _sub(idn, "submissionType", t)
    if _val(p.get("title")):
        _sub(idn, "title", _val(p["title"])[:200])
    _sub(idn, "language", (_val(p.get("language")) or "lv")[:8])
    _sub(idn, "status", status)
    if registration_no:
        _sub(idn, "registrationNo", registration_no)
    if document_id:
        _sub(idn, "documentId", document_id)
    _sub(idn, "receivedAt", received_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    _sub(idn, "channel", CHANNELS.get(channel, channel))
    rec = _sub(idn, "recipient")
    _sub(rec, "name", "Tiesībsarga birojs")
    _sub(rec, "code", RECIPIENT_CODE)
    sig = _sub(idn, "signature")
    _sub(sig, "method", signature)
    for s in signers:
        _sub(sig, "signer", s)

    st = structuring or {"method": "form"}
    prov = _sub(root, "provenance")
    if source_document:
        sd = _sub(prov, "sourceDocument")
        _sub(sd, "fileName", source_document["file_name"][:200])
        if source_document.get("mime_type"):
            _sub(sd, "mediaType", source_document["mime_type"])
        if source_document.get("data") is not None:
            _sub(sd, "sha256", hashlib.sha256(source_document["data"]).hexdigest())
    s = _sub(prov, "structuring")
    for k in ("method", "performedAt", "model", "reviewedBy", "reviewedAt"):
        v = st.get(k) or (datetime.now(timezone.utc).replace(microsecond=0).isoformat() if k == "performedAt" else None)
        if v:
            _sub(s, k, str(v)[:200])
    if st.get("method") == "form":
        _sub(prov, "formVersion", "0.1")

    body = etree.Element("tmp")
    _emit(body, BODY, _normalise(p))
    for el in list(body):
        root.append(el)

    if attachments:
        att = _sub(root, "attachments")
        for n, a in enumerate(attachments, 1):
            x = _sub(att, "attachment")
            _sub(x, "id", f"a{n}")
            _sub(x, "kind", a.get("kind") if a.get("kind") in ("evidence", "authorisation", "priorCorrespondence",
                                                               "courtDocument", "other") else "evidence")
            _sub(x, "fileName", a["file_name"][:200])
            if _val(a.get("apraksts")):
                _sub(x, "description", _val(a["apraksts"])[:200])
            if a.get("mime_type"):
                _sub(x, "mediaType", a["mime_type"])
            sha = a.get("sha256") or (hashlib.sha256(a["data"]).hexdigest() if a.get("data") is not None else None)
            if sha:
                _sub(x, "sha256", sha)
    if declarations:
        d = _sub(root, "declarations")
        _sub(d, "informationTruthful", "true" if declarations.get("informationTruthful") else "false")
        _sub(d, "dataProcessingAcknowledged", "true" if declarations.get("dataProcessingAcknowledged") else "false")
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ── Validation ──────────────────────────────────────────────────────────────
_cache: dict[str, Any] = {}


async def _validators(shema: dict):
    from opendms.uapf.learning import fetch_file
    key = f"{shema.get('xsd')}|{shema.get('noteikumi')}"
    if key not in _cache:
        xsd = etree.XMLSchema(etree.parse(io.BytesIO(await fetch_file(shema["xsd"]))))
        sch = isoschematron.Schematron(etree.parse(io.BytesIO(await fetch_file(shema["noteikumi"]))),
                                       store_report=True) if shema.get("noteikumi") else None
        _cache[key] = (xsd, sch)
    return _cache[key]


LABELS = {"givenName": "Vārds", "familyName": "Uzvārds", "legalName": "Nosaukums", "registrationNo": "Reģistrācijas numurs",
          "email": "E-pasts", "phone": "Tālrunis", "eAddress": "E-adrese", "address": "Adrese",
          "summary": "Izklāsts", "text": "Teksts", "statement": "Fakta apraksts", "date": "Datums",
          "yearMonth": "Mēnesis", "type": "Veids", "domain": "Joma", "classifierCode": "Tēmas kods",
          "replyChannel": "Atbildes veids", "partyType": "Personas veids", "basis": "Pamats"}


def _xsd_message(e) -> str:
    msg = e.message.replace("{" + NS + "}", "")
    m = re.match(r"Element '(\w+)'", msg)
    label = LABELS.get(m.group(1), m.group(1)) if m else "Lauks"
    if "minLength" in msg:
        return f"{label}: nav aizpildīts."
    if "maxLength" in msg:
        n = re.search(r"maximum length of '(\d+)'", msg)
        return f"{label}: ne vairāk kā {n.group(1) if n else ''} zīmes."
    if "Missing child element" in msg:
        miss = re.search(r"Expected is.*?\( ?(\w+)", msg)
        return f"Nav aizpildīts obligāts lauks: {LABELS.get(miss.group(1), miss.group(1)) if miss else label}."
    if "pattern" in msg or "not a valid value" in msg or "enumeration" in msg:
        return f"{label}: nederīga vērtība."
    return f"{label}: {msg}"


async def validate(xml: bytes, shema: dict, klasifikators: Optional[dict] = None, *,
                   strict_classifier: bool = True) -> dict:
    """XSD + rules + classifier. Returns {errors:[str], warnings:[{id,message}], info:{…}}.
    The classifier code is an error from the form (the person chose it) and a warning from the model."""
    xsd, sch = await _validators(shema)
    doc = etree.parse(io.BytesIO(xml))
    errors: list[str] = []
    warnings: list[dict] = []
    if not xsd.validate(doc):
        return {"errors": [_xsd_message(e) for e in xsd.error_log], "warnings": [], "info": {}}
    if sch is not None:
        sch.validate(doc)
        for node in sch.validation_report.iter(f"{{{SVRL}}}failed-assert", f"{{{SVRL}}}successful-report"):
            text = " ".join("".join(node.itertext()).split())
            if node.get("role") == "warning":
                warnings.append({"id": node.get("id") or "?", "message": text})
            else:
                errors.append(text)
    ns = {"es": NS}
    t = lambda path: doc.findtext(path, namespaces=ns)  # noqa: E731
    domains = [x.text for x in doc.findall("es:rightsAffected/es:domain", ns)]
    codes = [x.text for x in doc.findall("es:rightsAffected/es:classifierCode", ns)]
    klas_res = []
    if codes and klasifikators:
        for kods in codes:
            c = next((x for x in klasifikators["kodi"] if x["kods"] == kods), None)
            problem = (f"Tēmas kods {kods} nav klasifikatorā." if not c else
                       f"Tēmas kods {kods} nav izvēlams — izvēlieties sīkāku tēmu." if not c["izvelams"] else
                       f"Tēmas kods {kods} nepieder norādītajām jomām." if domains and c["joma"] not in domains else None)
            if problem:
                (errors.append(problem) if strict_classifier else warnings.append({"id": "W-KLAS", "message": problem}))
            else:
                klas_res.append(c)
    submitter = doc.find("es:parties/es:party[es:role='submitter']", ns)
    sname = None
    if submitter is not None:
        st = submitter.findtext("es:partyType", namespaces=ns)
        sname = (submitter.findtext("es:legalName", namespaces=ns) if st in ("legalPerson", "institution") else
                 " ".join(x for x in (submitter.findtext("es:givenName", namespaces=ns),
                                      submitter.findtext("es:familyName", namespaces=ns)) if x)) or None
    info = {
        "shema": shema.get("xsd"), "versija": "0.1",
        "joma": domains[0] if domains else None, "jomas": domains,
        "kods": codes[0] if codes else None, "kodi": codes,
        "kodaNosaukums": klas_res[0]["nosaukums"] if klas_res else None,
        "klasifikatorsVersija": (klasifikators or {}).get("versija"),
        "iestades": [p.findtext("es:legalName", namespaces=ns) for p in
                     doc.findall("es:parties/es:party[es:role='respondent']", ns) if p.findtext("es:legalName", namespaces=ns)],
        "izklasts": t("es:narrative/es:summary"),
        "fakti": len(doc.findall("es:facts/es:fact", ns)),
        "prasijumi": [{"id": c.findtext("es:id", namespaces=ns), "veids": c.findtext("es:type", namespaces=ns),
                       "teksts": c.findtext("es:text", namespaces=ns)} for c in doc.findall("es:claims/es:claim", ns)],
        "lugums": t("es:claims/es:claim/es:text"),
        "atbildesVeids": t("es:privacy/es:replyChannel"),
        "neizpaustIdentitati": t("es:privacy/es:doNotDiscloseIdentity") in ("true", "1"),
        "sender": {"name": sname,
                   "type": submitter.findtext("es:partyType", namespaces=ns) if submitter is not None else None,
                   "email": submitter.findtext("es:contact/es:email", namespaces=ns) if submitter is not None else None},
        "bridinajumi": [w["id"] for w in warnings],
    }
    return {"errors": errors, "warnings": warnings, "info": info}


async def classifier(shema: dict) -> Optional[dict]:
    if not shema.get("klasifikators"):
        return None
    from opendms.uapf.learning import fetch_file, parse_klasifikators
    return parse_klasifikators(await fetch_file(shema["klasifikators"]))


def submitter_of(xml: bytes) -> Optional[dict]:
    """Original submitter from a stored e-submission (forwarded documents keep it)."""
    try:
        doc = etree.fromstring(xml)
    except etree.XMLSyntaxError:
        return None
    if doc.tag != f"{{{NS}}}eSubmission":
        return None
    ns = {"es": NS}
    p = doc.find("es:parties/es:party[es:role='submitter']", ns)
    if p is None:
        return None
    name = (p.findtext("es:legalName", namespaces=ns) if p.findtext("es:partyType", namespaces=ns) != "naturalPerson"
            else " ".join(x for x in (p.findtext("es:givenName", namespaces=ns), p.findtext("es:familyName", namespaces=ns)) if x))
    return {"name": name or None, "email": p.findtext("es:contact/es:email", namespaces=ns)}
