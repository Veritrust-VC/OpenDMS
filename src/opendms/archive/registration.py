"""Dokumenta sagatavošana arhivēšanai reģistrācijā — UAPF P2 (kisc/dokumentu-arhivesana), standarts 01, 1.3.

Spējas: case.resolve@1, case.attach@1, files.check@1, archive.assign-id@1;
lēmumi: registracijas-minimums, datnu-formati (pārnesti 1:1; 5. solī tos izpildīs UAPF dzinējs).
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from opendms.archive import cases as cs
from opendms.database import get_pool

RIGA = ZoneInfo("Europe/Riga")

# ── lēmums datnu-formati (FIRST) ──
PDF = {"application/pdf"}
ASIC = {"application/vnd.etsi.asic-e+zip", "application/vnd.etsi.asic-s+zip"}
DATA = {"application/xml", "text/xml", "application/json", "text/csv", "text/plain"}
IMAGE = {"image/tiff", "image/png", "image/jpeg"}
AV = {"audio/wav", "audio/x-wav", "audio/flac", "video/mp4"}
OFFICE = {"application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/msword",
          "application/vnd.oasis.opendocument.text", "application/rtf",
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.oasis.opendocument.spreadsheet"}
EXT_MIME = {"pdf": "application/pdf", "edoc": "application/vnd.etsi.asic-e+zip", "asice": "application/vnd.etsi.asic-e+zip",
            "asics": "application/vnd.etsi.asic-s+zip", "xml": "application/xml", "json": "application/json", "csv": "text/csv",
            "txt": "text/plain", "tif": "image/tiff", "tiff": "image/tiff", "png": "image/png", "jpg": "image/jpeg",
            "jpeg": "image/jpeg", "wav": "audio/wav", "flac": "audio/flac", "mp4": "video/mp4", "rtf": "application/rtf",
            "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "doc": "application/msword",
            "odt": "application/vnd.oasis.opendocument.text", "ods": "application/vnd.oasis.opendocument.spreadsheet",
            "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
INFO_STATUS = {"Visparpieejama", "IerobezotasPieejamibas", "DienestaVajadzibam"}


def file_action(mime: Optional[str], file_name: str = "", signed: bool = False) -> dict:
    m = (mime or "").split(";")[0].strip().lower()
    if not m or m == "application/octet-stream":
        m = EXT_MIME.get(file_name.rsplit(".", 1)[-1].lower(), m) if "." in file_name else m
    if m in PDF:
        return {"mime": m, "derigs": True, "riciba": "Saglabat", "piezime": "PDF; slēdzot lietu pārbauda PDF/A atbilstību"}
    if m in ASIC:
        return {"mime": m, "derigs": True, "riciba": "Saglabat", "piezime": "eDoc/ASiC paraksta konteiners"}
    if m in DATA:
        return {"mime": m, "derigs": True, "riciba": "Saglabat", "piezime": "Strukturēti dati vai teksts"}
    if m in IMAGE:
        return {"mime": m, "derigs": True, "riciba": "Saglabat", "piezime": "Attēls"}
    if m in AV:
        return {"mime": m, "derigs": True, "riciba": "Saglabat", "piezime": "Audio vai video"}
    if m in OFFICE and signed:
        return {"mime": m, "derigs": True, "riciba": "Saglabat",
                "piezime": "Parakstīts biroja dokuments: saglabā kā ir, pievieno PDF/A atveidojumu"}
    if m in OFFICE:
        return {"mime": m, "derigs": True, "riciba": "KonvertetPDFA", "piezime": "Biroja dokuments: slēdzot lietu konvertē uz PDF/A; oriģināls paliek"}
    return {"mime": m or None, "derigs": False, "riciba": "Noraidit",
            "piezime": "Nezināms formāts: jānosaka formāts vai jāpievieno PDF/A versija"}


# ── lēmums registracijas-minimums ──
def check_minimum(v: dict) -> list[str]:
    """Visi trūkumi (DMN ir FIRST — šeit tos parāda visus uzreiz, secība tā pati)."""
    out = []
    if not v.get("irLieta"):
        out.append("Nav lietas no spēkā esošās klasifikācijas shēmas")
    elif not v.get("lietaAtverta"):
        out.append("Lieta slēgta — izvēlieties šā perioda lietu")
    if v.get("irLieta") and not v.get("irTermins"):
        out.append("Nav glabāšanas termiņa")
    if not v.get("irStatuss"):
        out.append("Nav informācijas statusa")
    elif v.get("statuss") != "Visparpieejama" and not v.get("irPamatojums"):
        out.append("Ierobežotas pieejamības informācijai nav tiesiskā pamatojuma")
    if not v.get("irDatums"):
        out.append("Nav dokumenta datuma")
    if not v.get("irVeids"):
        out.append("Nav dokumenta veida")
    if not v.get("datnuFormatiDerigi"):
        out.append("Datne nav glabājamā vai konvertējamā formātā")
    return out


def _meta(d: dict) -> dict:
    m = d.get("metadata")
    return json.loads(m) if isinstance(m, str) else (m or {})


def inputs(doc: dict, case: Optional[dict], entry: Optional[dict], files: list[dict]) -> tuple[dict, list[dict]]:
    meta = _meta(doc)
    rules = (meta.get("standartaPakotne") or {}).get("noteikumi") or {}
    ark = meta.get("arhivs") or {}
    status = ark.get("infoStatus") or rules.get("infoStatus") or (entry or {}).get("default_info_status")
    basis = ark.get("accessBasis") or rules.get("legalBasis") or (entry or {}).get("access_basis")
    dtype = (rules.get("documentType") or {}).get("code") or meta.get("documentType") or doc.get("classification_id")
    checked = []
    for f in files:
        name = f.get("file_name") or ""
        signed = name.lower().endswith((".edoc", ".asice", ".asics")) or bool(f.get("signed"))
        checked.append({"datne": name, **file_action(f.get("mime_type"), name, signed)})
    v = {"irLieta": bool(case and case.get("scheme_entry_id")),
         "lietaAtverta": bool(case and case.get("status") == "Atverta"),
         "irTermins": bool(case and case.get("retention_kind")),
         "irStatuss": status in INFO_STATUS, "statuss": status,
         "irPamatojums": bool(basis),
         "irDatums": bool(meta.get("documentDate") or doc.get("created_at")),
         "irVeids": bool(dtype),
         "datnuFormatiDerigi": all(c["derigs"] for c in checked)}
    return v, checked


async def _load(conn, doc_id: int):
    doc = await conn.fetchrow("SELECT * FROM documents WHERE id = $1", doc_id)
    if not doc:
        raise cs.CaseError("Dokuments nav atrasts")
    doc = dict(doc)
    case = entry = None
    if doc.get("case_id"):
        case = dict(await conn.fetchrow("SELECT * FROM standard_cases WHERE id = $1", doc["case_id"]))
        if case.get("scheme_entry_id"):
            e = await conn.fetchrow("SELECT * FROM scheme_entries WHERE id = $1", case["scheme_entry_id"])
            entry = dict(e) if e else None
    files = [dict(r) for r in await conn.fetch(
        "SELECT file_name, mime_type FROM document_files WHERE document_id = $1 ORDER BY id", doc_id)]
    if not files and doc.get("file_name"):
        files = [{"file_name": doc["file_name"], "mime_type": doc.get("mime_type")}]
    return doc, case, entry, files


def _year(doc: dict) -> int:
    return doc["created_at"].astimezone(RIGA).year


async def suggest_cases(conn, org_id: int, doc: dict) -> dict:
    """case.resolve@1: atvērtās šā gada lietas un, ja nosakāma, ieteiktā (pēc procesa noteikumu indeksa)."""
    year = _year(doc)
    rows = await conn.fetch(
        """SELECT id, case_index, case_name, scheme_entry_id FROM standard_cases
            WHERE org_id = $1 AND case_year = $2 AND status = 'Atverta' ORDER BY case_index""", org_id, year)
    idx = ((_meta(doc).get("standartaPakotne") or {}).get("noteikumi") or {}).get("caseIndex")
    hit = next((r for r in rows if idx and r["case_index"] == idx and r["scheme_entry_id"]), None)
    return {"gads": year, "ieteikta": hit["id"] if hit else None,
            "iespejas": [dict(r) for r in rows if r["scheme_entry_id"]]}


def _view(doc, case, v, trukumi, checked, sugg=None) -> dict:
    return {"dokuments": doc["id"], "registracijasNr": doc.get("registration_number"),
            "lieta": {"id": case["id"], "indekss": case["case_index"], "nosaukums": case.get("case_name"),
                      "gads": case["case_year"], "statuss": case["status"]} if case else None,
            "parbaude": v, "trukumi": trukumi, "datnes": checked, "gatavs": not trukumi,
            "arhivaId": doc.get("archive_id"), "sagatavotsUz": doc.get("archive_ready_at"),
            **({"lietuIeteikums": sugg} if sugg is not None else {})}


async def readiness(org_id: int, doc_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc, case, entry, files = await _load(conn, doc_id)
        v, checked = inputs(doc, case, entry, files)
        sugg = await suggest_cases(conn, org_id, doc) if not case or case["status"] != "Atverta" else None
    return _view(doc, case, v, check_minimum(v), checked, sugg)


async def prepare(org: dict, doc_id: int, who: str, actor_id: Optional[int] = None,
                  case_pk: Optional[int] = None, info_status: Optional[str] = None,
                  access_basis: Optional[str] = None) -> dict:
    """P2: lieta (izvēlēta vai ieteiktā) → mantotie dati → minimums → arhīva ID."""
    if info_status and info_status not in INFO_STATUS:
        raise cs.CaseError(f"Nederīgs informācijas statuss: {info_status}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc, case, _e, _f = await _load(conn, doc_id)
        if case_pk is None and not doc.get("case_id"):
            case_pk = (await suggest_cases(conn, org["id"], doc))["ieteikta"]
    if case_pk and case_pk != doc.get("case_id"):
        await cs.attach_document(org, case_pk, doc_id, who, actor_id)
    async with pool.acquire() as conn:
        async with conn.transaction():
            doc, case, entry, files = await _load(conn, doc_id)
            meta = _meta(doc)
            ark = dict(meta.get("arhivs") or {})
            if info_status:
                ark["infoStatus"] = info_status
            if access_basis:
                ark["accessBasis"] = access_basis
            if ark != (meta.get("arhivs") or {}):
                await conn.execute("UPDATE documents SET metadata = jsonb_set(COALESCE(metadata, '{}'::jsonb), '{arhivs}', $2::jsonb) WHERE id = $1",
                                   doc_id, json.dumps(ark, ensure_ascii=False))
                doc["metadata"] = {**meta, "arhivs": ark}
            v, checked = inputs(doc, case, entry, files)
            trukumi = check_minimum(v)
            if not trukumi and not doc.get("archive_id"):
                aid = secrets.token_hex(20)                       # LNA "Identifikācijas Nr." — 40 hex
                await conn.execute("UPDATE documents SET archive_id = $2, archive_ready_at = NOW() WHERE id = $1", doc_id, aid)
                await conn.execute(
                    "INSERT INTO document_events (document_id, event_type, actor_id, details) VALUES ($1, 'SagatavotsArhivesanai', $2, $3)",
                    doc_id, actor_id, json.dumps({"arhivaId": aid, "lieta": case["case_id"], "statuss": v["statuss"],
                                                  "datnes": checked, "kas": who}, ensure_ascii=False))
                doc["archive_id"], doc["archive_ready_at"] = aid, datetime.now(RIGA)
            sugg = await suggest_cases(conn, org["id"], doc) if not case else None
    return _view(doc, case, v, trukumi, checked, sugg)


async def unfiled(org_id: int, year: Optional[int] = None, limit: int = 200) -> list[dict]:
    """Dokumenti bez lietas vai bez arhīva ID (darba saraksts lietvedim)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT d.id, d.registration_number, d.title, d.status, d.created_at, d.archive_id,
                      c.case_index, c.status AS case_status
                 FROM documents d LEFT JOIN standard_cases c ON c.id = d.case_id
                WHERE d.org_id = $1 AND (d.case_id IS NULL OR d.archive_id IS NULL)
                  AND ($2::int IS NULL OR EXTRACT(YEAR FROM d.created_at AT TIME ZONE 'Europe/Riga')::int = $2)
                ORDER BY d.created_at DESC LIMIT $3""", org_id, year, limit)
    return [dict(r) for r in rows]


async def require_case_for_new(conn, org_id: int, case_pk: Optional[int]) -> Optional[dict]:
    """Ja P2 ieslēgts, jaunu dokumentu reģistrē tikai atvērtā shēmas lietā."""
    if case_pk is None:
        if await conn.fetchval("SELECT enforce_registration_minimum FROM archive_settings WHERE org_id = $1", org_id):
            raise cs.CaseError("Reģistrējot jānorāda lieta no spēkā esošās klasifikācijas shēmas (Arhīvs → Iestatījumi: P2 ieslēgts)")
        return None
    c = await conn.fetchrow("SELECT * FROM standard_cases WHERE id = $1 AND org_id = $2", case_pk, org_id)
    if not c or c["status"] != "Atverta" or not c["scheme_entry_id"]:
        raise cs.CaseError("Lietai jābūt atvērtai un no klasifikācijas shēmas")
    return dict(c)
