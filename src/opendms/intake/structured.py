"""Structured iesniegums — the form IS the data schema.

The web form submits field values; this module writes them, in schema order,
into an instance of the channel's XSD, checks it with the XSD, the Schematron
rules and the published classifier, and returns the XML. Nothing is
interpreted: no text recognition, no model. The XML becomes the document's
primary file; the chosen joma/kods go straight into classification.

Channel config (ievade.yaml):
    shema:
      xsd: tiesibsargs/iesnieguma-virzisana/ievade/iesniegums-1.0.xsd
      noteikumi: tiesibsargs/iesnieguma-virzisana/ievade/iesniegums-1.0.sch
      klasifikators: tiesibsargs/temu-klasifikators/klasifikators.xml
"""

from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from typing import Any, Optional

from lxml import etree, isoschematron

NS = "urn:lv:tiesibsargs:iesniegums:1.0"
SVRL = {"svrl": "http://purl.oclc.org/dsdl/svrl"}

# Schema order of iesniegums-1.0.xsd. Values come only from these paths.
ORDER: list[tuple[str, Any]] = [
    ("Galvene", [("FormasVersija", None), ("Kanals", None), ("Valoda", None), ("SagatavotsUz", None)]),
    ("Iesniedzejs", [("PusesTips", None), ("Vards", None), ("Uzvards", None), ("Nosaukums", None),
                     ("RegistracijasNr", None),
                     ("Kontakti", [("Epasts", None), ("Talrunis", None), ("EAdrese", None), ("PastaAdrese", None)]),
                     ("AtbildesVeids", None)]),
    ("Parstavis", [("ParstavamaPersona", [("PusesTips", None), ("Vards", None), ("Uzvards", None),
                                          ("Nosaukums", None), ("RegistracijasNr", None)]),
                   ("Pamats", None), ("PamatsApraksts", None)]),
    ("Jautajums", [("Joma", None), ("Kods", None),
                   ("Iestade*", [("Nosaukums", None), ("Kods", None)]),
                   ("NotikumaDatums", None), ("NotikumaMenesis", None),
                   ("Apraksts", None), ("Lugums", None)]),
    ("IeprieksejieSoli", [("VersiesIestade", None), ("VersanasDatums", None), ("AtbildeSanemta", None),
                          ("AtbildesKopsavilkums", None), ("Tiesvediba", None)]),
    ("Pielikumi", [("Pielikums*", [("DatnesNosaukums", None), ("Apraksts", None), ("Sha256", None)])]),
    ("Apliecinajumi", [("InformacijaPatiesa", None), ("IepaziniesArDatuApstradi", None)]),
]


ALWAYS = {"Kontakti"}  # required container whose children are all optional

LABELS = {
    "Vards": "Vārds", "Uzvards": "Uzvārds", "Nosaukums": "Nosaukums", "RegistracijasNr": "Reģistrācijas numurs",
    "Epasts": "E-pasts", "Talrunis": "Tālrunis", "EAdrese": "E-adrese", "PastaAdrese": "Pasta adrese",
    "AtbildesVeids": "Atbildes veids", "PusesTips": "Iesniedzēja veids", "Pamats": "Pārstāvības pamats",
    "PamatsApraksts": "Pārstāvības pamata apraksts", "Joma": "Joma", "Kods": "Tēmas kods",
    "NotikumaDatums": "Notikuma datums", "NotikumaMenesis": "Notikuma mēnesis", "Apraksts": "Apraksts",
    "Lugums": "Lūgums", "VersiesIestade": "Vai vērsāties iestādē", "VersanasDatums": "Vēršanās datums",
    "AtbildeSanemta": "Vai saņēmāt atbildi", "AtbildesKopsavilkums": "Atbildes kopsavilkums",
    "Tiesvediba": "Tiesvedība", "InformacijaPatiesa": "Apliecinājums par patiesu informāciju",
    "IepaziniesArDatuApstradi": "Apliecinājums par datu apstrādi", "DatnesNosaukums": "Datnes nosaukums",
}


class InvalidSubmission(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def _val(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v).strip()
    return s or None


def _emit(parent, spec, data: dict) -> None:
    for name, children in spec:
        many = name.endswith("*")
        name = name.rstrip("*")
        value = data.get(name)
        items = value if many and isinstance(value, list) else [value]
        for item in items:
            if children:
                if not isinstance(item, dict):
                    continue
                el = etree.Element(f"{{{NS}}}{name}")
                _emit(el, children, item)
                if len(el) or name in ALWAYS:
                    parent.append(el)
            else:
                s = _val(item)
                if s is not None:
                    etree.SubElement(parent, f"{{{NS}}}{name}").text = s


def build(fields: dict, *, kanals: str, attachments: list[dict]) -> bytes:
    """Field values (JSON, same names as the schema) -> iesniegums XML.

    Header and attachment list are set here, not taken from the browser."""
    data = {k: v for k, v in (fields or {}).items() if k in {n for n, _ in ORDER}}
    data["Galvene"] = {"FormasVersija": "1.0", "Kanals": kanals,
                       "Valoda": ((fields or {}).get("Galvene") or {}).get("Valoda") or "lv",
                       "SagatavotsUz": datetime.now(timezone.utc).replace(microsecond=0).isoformat()}
    if attachments:
        data["Pielikumi"] = {"Pielikums": [
            {"DatnesNosaukums": a["file_name"][:200], "Apraksts": (a.get("apraksts") or "")[:200] or None,
             "Sha256": hashlib.sha256(a["data"]).hexdigest()} for a in attachments]}
    else:
        data.pop("Pielikumi", None)
    root = etree.Element(f"{{{NS}}}Iesniegums", nsmap={None: NS})
    root.set("versija", "1.0")
    _emit(root, ORDER, data)
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


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


def _xsd_message(e) -> str:
    """lxml XSD error -> a sentence a person can act on."""
    import re
    msg = e.message.replace("{" + NS + "}", "")
    m = re.match(r"Element '(\w+)'", msg)
    label = LABELS.get(m.group(1), m.group(1)) if m else "Lauks"
    if "minLength" in msg:
        n = re.search(r"minimum length of '(\d+)'", msg)
        return f"{label}: jābūt vismaz {n.group(1) if n else ''} zīmēm."
    if "maxLength" in msg:
        n = re.search(r"maximum length of '(\d+)'", msg)
        return f"{label}: ne vairāk kā {n.group(1) if n else ''} zīmes."
    if "Missing child element" in msg:
        miss = re.search(r"Expected is.*?\( ?(\w+)", msg)
        return f"Nav aizpildīts obligāts lauks: {LABELS.get(miss.group(1), miss.group(1)) if miss else label}."
    if "is not expected" in msg:
        return f"{label}: lauks šajā vietā nav paredzēts."
    return f"{label}: nederīga vērtība."


async def validate(xml: bytes, shema: dict, klasifikators: Optional[dict]) -> dict:
    """XSD, rules, classifier. Raises InvalidSubmission with Latvian/plain messages."""
    xsd, sch = await _validators(shema)
    doc = etree.parse(io.BytesIO(xml))
    errors: list[str] = []
    if not xsd.validate(doc):
        errors += [_xsd_message(e) for e in xsd.error_log]
    if sch is not None and not sch.validate(doc):
        errors += [" ".join(t.split()) for t in sch.validation_report.xpath("//svrl:failed-assert/svrl:text/text()", namespaces=SVRL)]
    ns = {"i": NS}
    joma = doc.findtext("i:Jautajums/i:Joma", namespaces=ns)
    kods = doc.findtext("i:Jautajums/i:Kods", namespaces=ns)
    klas_res = None
    if kods and klasifikators:
        c = next((x for x in klasifikators["kodi"] if x["kods"] == kods), None)
        if not c:
            errors.append(f"Tēmas kods {kods} nav klasifikatorā.")
        elif not c["izvelams"]:
            errors.append(f"Tēmas kods {kods} nav izvēlams — izvēlieties sīkāku tēmu.")
        elif c["joma"] != joma:
            errors.append(f"Tēmas kods {kods} nepieder izvēlētajai jomai {joma}.")
        else:
            klas_res = c
    if errors:
        raise InvalidSubmission(errors)
    t = lambda p: doc.findtext(p, namespaces=ns)  # noqa: E731
    puse = t("i:Iesniedzejs/i:PusesTips")
    name = (t("i:Iesniedzejs/i:Nosaukums") if puse == "JuridiskaPersona"
            else " ".join(x for x in (t("i:Iesniedzejs/i:Vards"), t("i:Iesniedzejs/i:Uzvards")) if x))
    return {
        "joma": joma, "kods": kods,
        "kodaNosaukums": klas_res["nosaukums"] if klas_res else None,
        "klasifikatorsVersija": (klasifikators or {}).get("versija"),
        "iestades": [x.text for x in doc.findall("i:Jautajums/i:Iestade/i:Nosaukums", ns)],
        "lugums": t("i:Jautajums/i:Lugums"),
        "atbildesVeids": t("i:Iesniedzejs/i:AtbildesVeids"),
        "sender": {"name": name, "type": puse, "email": t("i:Iesniedzejs/i:Kontakti/i:Epasts")},
        "shema": shema.get("xsd"),
    }


async def classifier(shema: dict) -> Optional[dict]:
    if not shema.get("klasifikators"):
        return None
    from opendms.uapf.learning import fetch_file, parse_klasifikators
    return parse_klasifikators(await fetch_file(shema["klasifikators"]))
