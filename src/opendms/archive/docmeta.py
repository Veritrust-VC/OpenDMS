"""Dokumenta arhīva metadati pakotnē (standarts 08) un parakstīšanas pierādījumi (MK 282 30. p.; standarts 8.1.).

- ark:DokumentaArhivaMetadati → LV-DOK metadati.xml sadaļa 14 Paplasinajumi (kad dokumentam ir arhīva ID)
- dm:Adresati (LV-DOK 9.) — no nosūtīšanas / pārsūtīšanas / metadatiem
- dm:Paraksti (LV-DOK 12.) un parakstisana.xml (ark:ParakstisanasPieradijumi) pakotnē
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from lxml import etree

from opendms.archive import cases as cs
from opendms.archive import marks as mk
from opendms.archive import registration as rg
from opendms.archive.scheme import ARK, SchemeError, _xsd
from opendms.database import get_pool

EV_SIGN = "ParakstitsDVS"
SIGN_METHOD = "Apstiprināts DVS: lietotājs autentificēts iestādes identitātes sistēmā (OIDC); bez droša elektroniskā paraksta"
A = lambda t: f"{{{ARK}}}{t}"  # noqa: E731


class SignError(SchemeError):
    pass


def _j(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


# ── adresāti ──

def addressees(meta: dict, events: list[dict]) -> list[dict]:
    """[{tips, nosaukums, eAdrese?, did?}] bez dublikātiem."""
    out, seen = [], set()

    def add(name, tips="ValstsIestade", e=None, did=None):
        key = (e or did or name or "").lower()
        if not name and not e and not did or key in seen:
            return
        seen.add(key)
        out.append({"tips": tips, "nosaukums": name or e or did, "eAdrese": e, "did": did})

    for r in meta.get("recipients") or []:
        if isinstance(r, dict):
            add(r.get("name"), r.get("type") or "ValstsIestade", r.get("eAddress"), r.get("did"))
        else:
            add(str(r))
    p = meta.get("parsutisana") or {}
    for x in [p] + list(p.get("vesture") or []):
        if x.get("adresats") and x.get("statuss") not in (None, "pieprasits", "kluda"):
            add(x.get("adresataNosaukums"), "ValstsIestade", x.get("adresats"))
    for ev in events:
        if ev.get("event_type") == "DocumentSent":
            d = _j(ev.get("details"))
            did = d.get("recipient") or d.get("recipient_org_did")
            if did:
                add(d.get("recipient_name"), "ValstsIestade", None, did)
    return out


def sent_date(events: list[dict], meta: dict) -> Optional[str]:
    ds = [ev["created_at"] for ev in events if ev.get("event_type") == "DocumentSent"]
    if ds:
        return min(ds).astimezone(timezone.utc).date().isoformat()
    p = meta.get("parsutisana") or {}
    return str(p["nosutits"])[:10] if p.get("nosutits") else None


# ── ark:DokumentaArhivaMetadati ──

def _persona(parent, tag, p):
    el = etree.SubElement(parent, A(tag))
    if p.get("lietotajaId"):
        etree.SubElement(el, A("LietotajaID")).text = str(p["lietotajaId"])
    etree.SubElement(el, A("VardsUzvards")).text = p.get("vardsUzvards") or "—"
    if p.get("amats"):
        etree.SubElement(el, A("Amats")).text = p["amats"]
    if p.get("strukturvieniba"):
        etree.SubElement(el, A("Strukturvieniba")).text = p["strukturvieniba"]
    return el


def archive_metadata(doc: dict, events: list[dict], marks: dict, files: list[dict]) -> etree._Element:
    meta = _j(doc.get("metadata"))
    root = etree.Element(A("DokumentaArhivaMetadati"), nsmap={"ark": ARK})
    etree.SubElement(root, A("ArhivaID")).text = doc["archive_id"]
    authors = meta.get("authors") or []
    if authors:
        g = etree.SubElement(root, A("Autori"))
        for a in authors:
            _persona(g, "Autors", a if isinstance(a, dict) else {"vardsUzvards": str(a)})
    sd = sent_date(events, meta)
    if sd:
        etree.SubElement(root, A("NosutisanasDatums")).text = sd
    if (meta.get("sender") or {}).get("reference"):
        etree.SubElement(root, A("NosutitajaDokumentaNr")).text = meta["sender"]["reference"]
    sent = any(ev.get("event_type") == "DocumentSent" for ev in events) or bool(sd)
    etree.SubElement(root, A("DokumentuGrupa")).text = cs.document_group({"metadata": meta, "_sent": sent})
    sem = meta.get("semantika") or {}
    abstract = doc.get("content_summary") or sem.get("kopsavilkums") or sem.get("summary")
    if abstract:
        etree.SubElement(root, A("Anotacija")).text = str(abstract)[:4000]
    kw = [k for k in (sem.get("atslegvardi") or sem.get("keywords") or []) if isinstance(k, str) and k.strip()]
    if kw:
        g = etree.SubElement(root, A("Atslegvardi"))
        for k in kw[:30]:
            etree.SubElement(g, A("Atslegvards")).text = k.strip()
    mk.append_marks(root, marks)
    use = (meta.get("arhivs") or {}).get("lietosanasIerobezojums")
    if use and use.get("teksts"):
        g = etree.SubElement(root, A("LietosanasIerobezojums"))
        etree.SubElement(g, A("Teksts")).text = use["teksts"]
        if use.get("lidz"):
            etree.SubElement(g, A("Lidz")).text = use["lidz"]
    tech = []
    for f in files:
        fa = rg.file_action(f.get("mime_type"), f.get("file_name") or "",
                            (f.get("file_name") or "").lower().endswith((".edoc", ".asice", ".asics")))
        tech.append(f"{f.get('file_name')}: {fa['mime'] or 'nezināms'}; {fa['piezime']}")
    if any(ev.get("event_type") == EV_SIGN for ev in events):
        tech.append("Parakstīts DVS bez droša elektroniskā paraksta — pierādījumi parakstisana.xml (MK 282 30. p.)")
    if tech:
        etree.SubElement(root, A("TehniskaInformacija")).text = "\n".join(tech)
    if not _xsd().validate(root.getroottree()):
        raise SchemeError("ark:DokumentaArhivaMetadati neatbilst XSD: " + "; ".join(e.message for e in list(_xsd().error_log)[:3]))
    return root


# ── parakstīšanas pierādījumi ──

def signing_xml(doc_uid: str, sign_events: list[dict]) -> bytes:
    root = etree.Element(A("ParakstisanasPieradijumi"), nsmap={"ark": ARK})
    etree.SubElement(root, A("DokumentaID")).text = doc_uid
    for nr, ev in enumerate(sign_events, start=1):
        d = _j(ev.get("details"))
        p = etree.SubElement(root, A("Pieradijums"), nr=str(nr))
        _persona(p, "Parakstitajs", d["persona"])
        etree.SubElement(p, A("ParakstitsUz")).text = ev["created_at"].astimezone(timezone.utc).isoformat()
        etree.SubElement(p, A("Metode")).text = d.get("metode") or SIGN_METHOD
        for f in d["datnes"]:
            x = etree.SubElement(p, A("Datne"))
            etree.SubElement(x, A("DatnesID")).text = f["datnesId"]
            etree.SubElement(x, A("DatnesNosaukums")).text = f["nosaukums"]
            etree.SubElement(x, A("Sha256")).text = f["sha256"]
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    if not _xsd().validate(etree.fromstring(data).getroottree()):
        raise SignError("parakstisana.xml neatbilst XSD: " + "; ".join(e.message for e in list(_xsd().error_log)[:3]))
    return data


async def sign(doc_id: int, user_id: int, storage, position: Optional[str] = None,
               note: Optional[str] = None) -> dict:
    """Parakstīt DVS (MK 282 30. p.): parakstītājs, laiks un katras datnes SHA-256 parakstīšanas brīdī."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT id, doc_uid, metadata FROM documents WHERE id = $1", doc_id)
        if not doc:
            raise SignError("Dokuments nav atrasts")
        files = await conn.fetch(
            "SELECT id, std_id, file_name, storage_key, checksum_sha256 FROM document_files WHERE document_id = $1 ORDER BY is_primary DESC, id", doc_id)
        if not files:
            raise SignError("Dokumentam nav datņu, ko parakstīt")
        persona = await mk._person(conn, user_id, position)
    out = []
    for f in files:
        data = await storage.get(f["storage_key"])
        if data is None:
            raise SignError(f"Datne nav nolasāma: {f['file_name']}")
        sha = hashlib.sha256(data).hexdigest()
        if f["checksum_sha256"] and f["checksum_sha256"] != sha:
            raise SignError(f"Datnes {f['file_name']} kontrolsumma neatbilst DVS ierakstam — parakstīt nevar")
        out.append({"datnesId": f["std_id"] or f"DVS-DATNE-{f['id']}", "nosaukums": f["file_name"], "sha256": sha})
    details = {"persona": persona, "metode": SIGN_METHOD, "datnes": out, "piezimes": note}
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "INSERT INTO document_events (document_id, event_type, actor_id, details) VALUES ($1, $2, $3, $4) RETURNING id, created_at",
            doc_id, EV_SIGN, user_id, json.dumps(details, ensure_ascii=False))
    return {"id": row["id"], "parakstitsUz": row["created_at"], **details}


async def package_extras(conn, doc: dict, files: list[dict], events: list[dict]) -> dict:
    """Ko build_package pievieno: adresāti, paraksti, paplašinājums, parakstisana.xml, fonds."""
    meta = _j(doc.get("metadata"))
    settings = await conn.fetchrow("SELECT fonds_number FROM archive_settings WHERE org_id = $1", doc["org_id"])
    signs = [ev for ev in events if ev.get("event_type") == EV_SIGN]
    extras = {"addressees": addressees(meta, events), "fonds": settings["fonds_number"] if settings else None,
              "signatures": [{"persona": _j(ev["details"])["persona"], "laiks": ev["created_at"],
                              "datnes": [f["datnesId"] for f in _j(ev["details"])["datnes"]]} for ev in signs],
              "extension": None, "technical": {}}
    if doc.get("archive_id"):
        marks = await mk.list_marks(doc["id"])
        extras["extension"] = archive_metadata(doc, events, marks, files)
    if signs and doc.get("doc_uid"):
        extras["technical"]["parakstisana.xml"] = signing_xml(doc["doc_uid"], signs)
    return extras
