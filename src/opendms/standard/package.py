"""
Builds a document package of the Dokumentu metadatu standarts v2.0:

    <LV-DOK_...>/
        metadati.xml      DokumentaPakotne  (dokumenta-metadati-v2.xsd)
        izsekosana.xml    Izsekosana        (dokumenta-izsekosana-v2.xsd)
        datnes/<name>     the document's files
        SHA256SUMS        checksums of every other file in the package

Pure functions: plain dicts in, bytes out. Loading from the database and
writing to storage is done by opendms.standard.service.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from lxml import etree

from opendms.standard.ids import (
    ORG_DID_RE,
    RIGA,
    document_did,
    package_folder,
)

NS_META = "urn:lv:vdvc:dokumentu-metadati:2.0"
NS_TRACK = "urn:lv:vdvc:dokumentu-izsekosana:2.0"
SCHEMA_DIR = Path(__file__).parent / "schemas"
META_XSD = SCHEMA_DIR / "dokumenta-metadati-v2.xsd"
TRACK_XSD = SCHEMA_DIR / "dokumenta-izsekosana-v2.xsd"

# OpenDMS lifecycle event -> standard event type and the status it leads to
EVENT_MAP = {
    "DocumentCreated":  ("DokumentsIzveidots", "Projekts"),
    "DocumentSent":     ("DokumentsNosutits", None),
    "DocumentReceived": ("DokumentsSanemts", "Registrets"),
    "DocumentAssigned": ("DokumentsPieskirtsIzpildei", "Izpilde"),
    "DocumentDecided":  ("DokumentsLemums", None),
    "DocumentArchived": ("DokumentsNodotsArhivam", "NodotsArhivam"),
}
STANDARD_EVENTS = {
    "DokumentsIzveidots": "Projekts", "DokumentsRegistrets": "Registrets",
    "PavadvestuleIzveidota": "Projekts", "DokumentsNosutits": None,
    "DokumentsSanemts": "Registrets", "DokumentsParsutits": None,
    "DokumentsPieskirtsIzpildei": "Izpilde", "DokumentsIzskatisana": "Izskatisana",
    "DokumentsVizets": None, "DokumentsParakstits": None, "DokumentsLemums": None,
    "DokumentsIzpildits": "Izpildits", "DokumentsAtgriezts": None,
    "DokumentsSlegts": "Slegts", "DokumentsNodotsArhivam": "NodotsArhivam",
    "DokumentsArhivets": "Arhivets", "DokumentsIznicinats": "Iznicinats",
}

PRONOM = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "fmt/412",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "fmt/214",
    "application/vnd.oasis.opendocument.text": "fmt/291",
    "text/plain": "x-fmt/111",
    "application/xml": "fmt/101",
    "text/xml": "fmt/101",
}

CHANNELS = {"EAdrese", "EPasts", "DVSIntegracija", "API", "Portals", "Klatiene", "Pasts", "DVSLietotajs"}
PARTY_TYPES = {"ValstsIestade", "Pasvaldiba", "JuridiskaPersona", "FiziskaPersona", "Cits"}
INFO_STATUS = {"Visparpieejama", "IerobezotasPieejamibas", "DienestaVajadzibam"}
DISPOSITIONS = {"Iznicinat", "NodotArhivam", "Parskatit"}
TRIGGERS = {"NoDokumentaDatuma", "NoLietasSlegsanas", "NoIzpildes", "NoNotikuma"}


# ── helpers ────────────────────────────────────────────────────────────────

def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _riga(value: Any) -> str:
    return _ts(value).astimezone(RIGA).isoformat(timespec="seconds")


def _el(parent, ns: str, name: str, text: Any = None, **attrs) -> etree._Element:
    e = etree.SubElement(parent, f"{{{ns}}}{name}")
    for k, v in attrs.items():
        if v is not None:
            e.set(k, str(v))
    if text is not None:
        e.text = str(text)
    return e


def _opt(parent, ns: str, name: str, text: Any) -> None:
    if text not in (None, ""):
        _el(parent, ns, name, text)


def _pick(value: Optional[str], allowed: set, default: str) -> str:
    return value if value in allowed else default


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── metadati.xml ───────────────────────────────────────────────────────────

def build_metadata_xml(
    *,
    org: dict,
    document: dict,
    files: list[dict],
    rules: dict,
    creator: Optional[dict] = None,
    system: Optional[dict] = None,
    generated_at: Optional[datetime] = None,
) -> bytes:
    """
    org       {std_code, name, org_did?, reg_number?, e_address?}
    document  {doc_uid, title, content_summary?, created_at, registration_number?,
               id, sdk_did?, metadata{}}
    files     [{std_id, file_name, mime_type?, file_size, checksum_sha256,
                is_primary, storage_key}]
    rules     process decisions: documentType{code,name}, case{id,index,name,year},
              schemeId, schemeVersion?, retention{years|permanent, trigger,
              disposition}, infoStatus, personalData, legalBasis?, archiveLevel?
    creator   {id, full_name, department?, email?}
    """
    M = NS_META
    root = etree.Element(f"{{{M}}}DokumentaPakotne", nsmap={"dm": M})
    root.set("shemasVersija", "2.0")
    root.set("izveidotsUz", _riga(generated_at))

    system = system or {}
    ctx = _el(root, M, "SistemasKonteksts")
    _el(ctx, M, "SistemasNosaukums", system.get("name") or "OpenDMS")
    _opt(ctx, M, "SistemasInstance", system.get("instance"))
    _el(ctx, M, "Vide", _pick(system.get("environment"), {"PROD", "TEST", "DEV"}, "TEST"))

    o = _el(root, M, "IpasniekaOrganizacija")
    _el(o, M, "OrgKods", org["std_code"])
    _el(o, M, "OrgNosaukums", org["name"])
    if org.get("org_did") and ORG_DID_RE.match(org["org_did"]):
        _el(o, M, "OrgDID", org["org_did"])
    _opt(o, M, "RegistracijasNumurs", org.get("reg_number"))
    if org.get("e_address"):
        k = _el(o, M, "Kontakti")
        _el(k, M, "EAdrese", org["e_address"])

    meta = document.get("metadata") or {}
    d = _el(root, M, "Dokuments")
    _el(d, M, "DokumentaID", document["doc_uid"])
    did = document_did(org.get("org_did"), document["doc_uid"])
    if did:
        _el(d, M, "DokumentaDID", did)

    ext = _el(d, M, "ArejieIdentifikatori")
    if document.get("registration_number"):
        _el(ext, M, "Identifikators", document["registration_number"],
            tips="RegistracijasNumurs", avots=system.get("instance") or "OpenDMS")
    _el(ext, M, "Identifikators", str(document["id"]), tips="DVSIeksejaisID",
        avots=system.get("instance") or "OpenDMS")
    if document.get("sdk_did"):
        _el(ext, M, "Identifikators", document["sdk_did"], tips="Cits", avots="VeriDocs SDK")

    _el(d, M, "Virsraksts", document["title"])
    _opt(d, M, "Apraksts", document.get("content_summary"))
    created = _ts(document.get("created_at"))
    _el(d, M, "DokumentaDatums", meta.get("documentDate") or created.astimezone(RIGA).date().isoformat())
    _el(d, M, "RegistretsUz", _riga(created))
    _el(d, M, "Valoda", meta.get("language") or "lv")

    dt = rules.get("documentType") or {}
    v = _el(d, M, "DokumentaVeids")
    _el(v, M, "VeidaKods", dt.get("code") or "VISP")
    _el(v, M, "VeidaNosaukums", dt.get("name") or "Vispārīgs dokuments")
    _opt(v, M, "KlasifikatoraVersija", dt.get("version"))

    case = rules.get("case") or {}
    k = _el(d, M, "Klasifikacija")
    _el(k, M, "ShemasID", rules.get("schemeId") or f"urn:lv:vdvc:nomenklatura:{org['std_code']}")
    _opt(k, M, "ShemasVersija", rules.get("schemeVersion"))
    kl = _el(k, M, "KlasifikacijasLieta")
    _el(kl, M, "LietasID", case["id"])
    _el(kl, M, "LietasIndekss", case.get("index") or "0")
    _el(kl, M, "LietasNosaukums", case.get("name") or "Nenoteikta lieta")
    _opt(kl, M, "LietasGads", case.get("year"))

    ret = rules.get("retention") or {}
    g = _el(d, M, "Glabasana")
    if ret.get("permanent"):
        _el(g, M, "GlabasanasTermins", "", veids="Pastavigi")
    else:
        _el(g, M, "GlabasanasTermins", int(ret.get("years") or 5), veids="Gadi")
    _el(g, M, "GlabasanasTriggeris", _pick(ret.get("trigger"), TRIGGERS, "NoLietasSlegsanas"))
    _el(g, M, "IznicinasanasDarbiba", _pick(ret.get("disposition"), DISPOSITIONS, "Iznicinat"))
    _el(g, M, "JuridiskaisAizliegums", "true" if ret.get("legalHold") else "false")
    _opt(g, M, "NomenklaturasKods", case.get("index"))

    a = _el(d, M, "Arhivs")
    _el(a, M, "AprakstaLimenis", "dokuments")

    s = _el(d, M, "Drosiba")
    status = _pick(rules.get("infoStatus"), INFO_STATUS, "IerobezotasPieejamibas")
    _el(s, M, "InformacijasStatuss", status)
    _el(s, M, "SaturPersonasDatus", "true" if rules.get("personalData", True) else "false")
    if status != "Visparpieejama":
        p = _el(s, M, "PiekluvesIerobezojums")
        _el(p, M, "TiesiskaisPamatojums", rules.get("legalBasis")
            or "Informācijas atklātības likuma 5. panta otrā daļa")

    dn = _el(d, M, "Datnes")
    for n, f in enumerate(files, start=1):
        x = _el(dn, M, "Datne", loma="Pamatdatne" if f.get("is_primary") else "Pielikums",
                kartasNumurs=n)
        _el(x, M, "DatnesID", f["std_id"])
        _el(x, M, "DatnesNosaukums", f["file_name"])
        mime = f.get("mime_type") or "application/octet-stream"
        _el(x, M, "MimeVeids", mime)
        _opt(x, M, "FormataID", PRONOM.get(mime))
        _el(x, M, "IzmersBaitos", int(f.get("file_size") or 0))
        _el(x, M, "Kontrolsumma", f["checksum_sha256"], algoritms="SHA-256", kodejums="hex")
        _el(x, M, "GlabasanasAtsauce", f"datnes/{f['file_name']}", tips="Pakotne")

    i = _el(d, M, "Izcelsme")
    _el(i, M, "IzveidotsUz", _riga(created))
    c = _el(i, M, "Izveidotajs")
    creator = creator or {}
    _opt(c, M, "LietotajaID", creator.get("email") or (creator.get("id") and f"user-{creator['id']}"))
    _el(c, M, "VardsUzvards", creator.get("full_name") or "OpenDMS")
    _opt(c, M, "Strukturvieniba", creator.get("department"))
    sender = meta.get("sender") or {}
    if sender.get("name"):
        ie = _el(i, M, "Iesniedzejs")
        _el(ie, M, "PusesTips", _pick(sender.get("type"), PARTY_TYPES, "FiziskaPersona"))
        _el(ie, M, "Nosaukums", sender["name"])
        if sender.get("email"):
            kk = _el(ie, M, "Kontakti")
            _el(kk, M, "Epasts", sender["email"])
    if meta.get("receivedAt"):
        _el(i, M, "SanemtsUz", _riga(meta["receivedAt"]))
    if meta.get("channel"):
        _el(i, M, "SanemsanasKanals", _pick(meta["channel"], CHANNELS, "DVSLietotajs"))

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ── izsekosana.xml ─────────────────────────────────────────────────────────

def standard_events(events: Iterable[dict]) -> list[dict]:
    """Map OpenDMS document_events rows to standard events, dropping domain events."""
    out = []
    previous_status = None
    for ev in events:
        etype = ev.get("event_type")
        if etype in EVENT_MAP:
            std, status = EVENT_MAP[etype]
        elif etype in STANDARD_EVENTS:
            std, status = etype, STANDARD_EVENTS[etype]
        else:
            continue
        out.append({**ev, "std_type": std, "status_from": previous_status if status else None,
                    "status_to": status})
        if status:
            previous_status = status
    return out


def build_tracking_xml(
    *,
    org: dict,
    document: dict,
    events: list[dict],
    users: dict[int, dict],
    generated_at: Optional[datetime] = None,
) -> bytes:
    """events: output of standard_events(), each with a persisted std_id."""
    T = NS_TRACK
    root = etree.Element(f"{{{T}}}Izsekosana", nsmap={"di": T})
    root.set("shemasVersija", "2.0")
    root.set("izveidotsUz", _riga(generated_at))

    h = _el(root, T, "DokumentaVesture")
    ref = _el(h, T, "DokumentaAtsauce")
    _el(ref, T, "DokumentaID", document["doc_uid"])
    did = document_did(org.get("org_did"), document["doc_uid"])
    if did:
        _el(ref, T, "DokumentaDID", did)
    _el(ref, T, "Virsraksts", document["title"])

    for ev in events:
        details = ev.get("details") or {}
        n = _el(h, T, "Notikums")
        _el(n, T, "NotikumaID", ev["std_id"])
        _el(n, T, "NotikumaTips", ev["std_type"])
        _el(n, T, "NotikumaLaiks", _riga(ev.get("created_at")))
        iz = _el(n, T, "Izdevejs")
        _el(iz, T, "OrgKods", org["std_code"])
        _el(iz, T, "OrgNosaukums", org["name"])
        if org.get("org_did") and ORG_DID_RE.match(org["org_did"]):
            _el(iz, T, "OrgDID", org["org_did"])
        actor = users.get(ev.get("actor_id")) if ev.get("actor_id") else None
        if actor:
            w = _el(n, T, "Darbinieks")
            _opt(w, T, "LietotajaID", actor.get("email"))
            _el(w, T, "VardsUzvards", actor.get("full_name") or actor.get("email"))
            _opt(w, T, "Strukturvieniba", actor.get("department"))
        else:
            w = _el(n, T, "Darbinieks", veids="Sistema")
            _el(w, T, "VardsUzvards", details.get("performedBy") or "OpenDMS process")
        if ev["std_type"] in ("DokumentsRegistrets", "DokumentsSanemts") and details.get("registration_number"):
            _el(n, T, "LokalaisRegistracijasNumurs", details["registration_number"])
        if ev.get("status_to"):
            sm = _el(n, T, "StatusaMaina")
            _opt(sm, T, "NoStatusa", ev.get("status_from"))
            _el(sm, T, "UzStatusu", ev["status_to"])
        note = details.get("note") or details.get("recipient_org_did")
        _opt(n, T, "Piezime", note)

    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


# ── assembling and checking ────────────────────────────────────────────────

def assemble(metadata_xml: bytes, tracking_xml: bytes, files: dict[str, bytes]) -> dict[str, bytes]:
    """Return {relative path: bytes} for the whole package, SHA256SUMS included."""
    out: dict[str, bytes] = {"metadati.xml": metadata_xml, "izsekosana.xml": tracking_xml}
    for name, data in files.items():
        out[f"datnes/{name}"] = data
    lines = [f"{sha256_hex(data)}  {path}" for path, data in out.items()]
    out["SHA256SUMS"] = ("\n".join(lines) + "\n").encode("utf-8")
    return out


_schemas: dict[str, etree.XMLSchema] = {}


def _schema(path: Path) -> etree.XMLSchema:
    key = str(path)
    if key not in _schemas:
        _schemas[key] = etree.XMLSchema(etree.parse(str(path)))
    return _schemas[key]


def validate(package: dict[str, bytes]) -> list[str]:
    """Check a package against the standard. Returns a list of problems (empty = valid)."""
    problems: list[str] = []
    for name, xsd in (("metadati.xml", META_XSD), ("izsekosana.xml", TRACK_XSD)):
        if name not in package:
            problems.append(f"{name}: missing")
            continue
        try:
            doc = etree.fromstring(package[name])
        except etree.XMLSyntaxError as e:
            problems.append(f"{name}: not well-formed: {e}")
            continue
        schema = _schema(xsd)
        if not schema.validate(doc):
            problems.extend(f"{name}: line {err.line}: {err.message}" for err in schema.error_log)

    if "metadati.xml" in package:
        try:
            meta = etree.fromstring(package["metadati.xml"])
            ns = {"dm": NS_META}
            for datne in meta.iterfind(".//dm:Datne", ns):
                name = datne.findtext("dm:DatnesNosaukums", namespaces=ns)
                size = int(datne.findtext("dm:IzmersBaitos", namespaces=ns) or -1)
                digest = datne.findtext("dm:Kontrolsumma", namespaces=ns)
                data = package.get(f"datnes/{name}")
                if data is None:
                    problems.append(f"datnes/{name}: listed in metadati.xml but missing")
                    continue
                if len(data) != size:
                    problems.append(f"datnes/{name}: size {len(data)} != IzmersBaitos {size}")
                if sha256_hex(data) != digest:
                    problems.append(f"datnes/{name}: checksum does not match metadati.xml")
        except Exception as e:  # noqa: BLE001
            problems.append(f"metadati.xml: could not check files: {e}")

    sums = package.get("SHA256SUMS", b"").decode("utf-8").splitlines()
    listed = {}
    for line in sums:
        if "  " in line:
            digest, path = line.split("  ", 1)
            listed[path] = digest
    for path, data in package.items():
        if path == "SHA256SUMS":
            continue
        if listed.get(path) != sha256_hex(data):
            problems.append(f"SHA256SUMS: wrong or missing entry for {path}")
    return problems


def folder_name(doc_uid: str) -> str:
    return package_folder(doc_uid)
