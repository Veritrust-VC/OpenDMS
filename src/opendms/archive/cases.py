"""Lietas dzīves cikls — kisc/dokumentu-arhivesanas-standarts 03; UAPF P3 spējas case.* (MK 282 20.–26., 47. p.).

Lieta = klasifikācijas shēmas lietas ieraksts konkrētā periodā (gadā); ID LV-LIETA (kā LV-DOK standartā).
Stāvokļi: Atverta → Slegta → (ekspertīze, 4. solis) …
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Optional

from lxml import etree

from opendms.archive.scheme import ARK, SchemeError, _xsd, active_scheme
from opendms.database import get_pool
from opendms.standard.ids import PREFIX_CASE, make_id

CLOSED_DOC_STATUSES = ("decided", "sent", "archived")
STATUS_LV = {"Atverta": "Atvērta", "Slegta": "Slēgta", "Izverteta": "Izvērtēta", "GlabaIestade": "Glabā iestādē",
             "AtlasitaIznicinasanai": "Atlasīta iznīcināšanai", "Iznicinata": "Iznīcināta", "Aprakstita": "Aprakstīta",
             "NodosanaiSagatavota": "Sagatavota nodošanai", "NodotaLNA": "Nodota LNA"}


class CaseError(SchemeError):
    pass


def _j(v):
    return json.loads(v) if isinstance(v, str) else (v if v is not None else [])


def _hist(action: str, who: str, **extra) -> str:
    return json.dumps([{"darbiba": action, "kas": who, "kad": datetime.now(timezone.utc).isoformat(), **extra}],
                      ensure_ascii=False, default=str)


def retention_end(kind: Optional[str], years: Optional[int], trigger: Optional[str],
                  closed: date, date_to: Optional[date]) -> Optional[date]:
    """Glabāšanas termiņa beigas (standarts 06, 6.1.). Pastāvīgi → None."""
    if kind == "Pastavigi" or not years:
        return None
    if trigger == "NoDokumentaDatuma" and date_to:
        start = date_to
    else:   # NoLietasSlegsanas; NoIzpildes/NoNotikuma — konservatīvi no slēgšanas
        start = date(closed.year + 1, 1, 1)
    try:
        return start.replace(year=start.year + years)
    except ValueError:      # 29. februāris
        return start.replace(year=start.year + years, day=28)


def document_group(d: dict) -> str:
    """Saņemtais / Nosūtāmais / Iekšējais (standarts 08)."""
    meta = d.get("metadata") or {}
    if d.get("_sent"):
        return "Nosutamais"
    if meta.get("sender") or meta.get("ievade") or meta.get("channel"):
        return "Sanemtais"
    return "Ieksejais"


def doc_date(d: dict) -> date:
    meta = d.get("metadata") or {}
    v = meta.get("documentDate")
    if v:
        try:
            return date.fromisoformat(str(v)[:10])
        except ValueError:
            pass
    c = d["created_at"]
    return c.date() if isinstance(c, datetime) else date.fromisoformat(str(c)[:10])


def register_xml(org: dict, settings: dict, case: dict, docs: list[dict], files: dict[int, list[str]],
                 related: dict[int, list[str]]) -> bytes:
    """ark:LietasDokumentuRegistrs (LNA dokumentu reģistra paraugs), pārbaudīts pret XSD."""
    A = lambda t: f"{{{ARK}}}{t}"
    root = etree.Element(A("LietasDokumentuRegistrs"), nsmap={"ark": ARK})
    ie = etree.SubElement(root, A("Iestade"))
    etree.SubElement(ie, A("OrgKods")).text = org.get("std_code")
    etree.SubElement(ie, A("Nosaukums")).text = org.get("name")
    reg = settings.get("registration_number") or org.get("reg_number")
    if reg:
        etree.SubElement(ie, A("RegistracijasNr")).text = reg
    etree.SubElement(root, A("LietasID")).text = case["case_id"]
    etree.SubElement(root, A("LietasIndekss")).text = case["case_index"]
    etree.SubElement(root, A("LietasNosaukums")).text = case.get("case_name") or case["case_index"]
    for d in docs:
        meta = d.get("metadata") or {}
        r = etree.SubElement(root, A("Ieraksts"))
        etree.SubElement(r, A("RegistracijasNumurs")).text = d.get("registration_number") or f"DVS-{d['id']}"
        etree.SubElement(r, A("RegistracijasDatums")).text = d["created_at"].date().isoformat()
        etree.SubElement(r, A("InformacijasVide")).text = "E" if files.get(d["id"]) else "P"
        author = (meta.get("sender") or {}).get("name") or d.get("creator_name") or org.get("name")
        etree.SubElement(r, A("Autors")).text = author
        for a in (meta.get("recipients") or []):
            etree.SubElement(r, A("Adresats")).text = a.get("name") if isinstance(a, dict) else str(a)
        etree.SubElement(r, A("DokumentaNosaukums")).text = d["title"]
        for fn in files.get(d["id"], []):
            etree.SubElement(r, A("DatnesNosaukums")).text = fn
        etree.SubElement(r, A("Veids")).text = document_group(d)
        for rel in related.get(d["id"], []):
            etree.SubElement(r, A("SaistitaisDokuments")).text = rel
        if d.get("doc_uid"):
            etree.SubElement(r, A("DokumentaID")).text = d["doc_uid"]
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    if not _xsd().validate(etree.fromstring(data).getroottree()):
        raise CaseError("Lietas dokumentu reģistrs neatbilst arhivesana-v1.xsd: " +
                        "; ".join(e.message for e in list(_xsd().error_log)[:3]))
    return data


# ───────────────────────── DB ─────────────────────────

async def list_cases(org_id: int, year: Optional[int] = None, status: Optional[str] = None) -> list[dict]:
    pool = await get_pool()
    where, params = ["c.org_id = $1"], [org_id]
    if year:
        params.append(year); where.append(f"c.case_year = ${len(params)}")
    if status:
        params.append(status); where.append(f"c.status = ${len(params)}")
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"""
            SELECT c.id, c.case_id, c.case_index, c.case_year, c.case_name, c.status, c.retention_kind, c.retention_years,
                   c.disposition, c.long_running, c.closed_at, c.retention_end, c.scheme_entry_id,
                   count(d.id) AS dokumenti,
                   count(d.id) FILTER (WHERE d.finished_at IS NULL AND d.status NOT IN {CLOSED_DOC_STATUSES!r}) AS nepabeigti
              FROM standard_cases c LEFT JOIN documents d ON d.case_id = c.id
             WHERE {' AND '.join(where)}
             GROUP BY c.id ORDER BY c.case_year DESC, c.case_index""", *params)
    return [dict(r) | {"status_lv": STATUS_LV.get(r["status"])} for r in rows]


async def get_case(org_id: int, case_pk: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        c = await conn.fetchrow("SELECT * FROM standard_cases WHERE id = $1 AND org_id = $2", case_pk, org_id)
        if not c:
            raise CaseError("Lieta nav atrasta")
        docs = await conn.fetch(f"""
            SELECT d.id, d.registration_number, d.title, d.status, d.doc_uid, d.created_at, d.finished_at,
                   (d.finished_at IS NULL AND d.status NOT IN {CLOSED_DOC_STATUSES!r}) AS nepabeigts,
                   (SELECT count(*) FROM document_files f WHERE f.document_id = d.id) AS datnes
              FROM documents d WHERE d.case_id = $1 ORDER BY d.created_at, d.id""", case_pk)
        vols = await conn.fetch("SELECT * FROM case_volumes WHERE case_id = $1 ORDER BY number", case_pk)
        entry = await conn.fetchrow(
            """SELECT e.idx, e.name, s.id AS scheme_id, s.period_from, s.period_to, s.status FROM scheme_entries e
                 JOIN classification_schemes s ON s.id = e.scheme_id WHERE e.id = $1""", c["scheme_entry_id"]) \
            if c["scheme_entry_id"] else None
    out = dict(c)
    out["history"] = _j(out["history"])
    out["status_lv"] = STATUS_LV.get(out["status"])
    out["dokumenti"] = [dict(r) for r in docs]
    out["sejumi"] = [dict(r) for r in vols]
    out["shemas_ieraksts"] = dict(entry) if entry else None
    out["nepabeigti"] = sum(1 for r in docs if r["nepabeigts"])
    return out


async def open_case(org: dict, entry_id: int, year: int, who: str) -> dict:
    """Atvērt lietu no apstiprinātas shēmas ieraksta gadam (vai sasaistīt esošo)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        e = await conn.fetchrow(
            """SELECT e.*, s.status AS scheme_status, s.period_from, s.period_to FROM scheme_entries e
                 JOIN classification_schemes s ON s.id = e.scheme_id WHERE e.id = $1 AND s.org_id = $2""", entry_id, org["id"])
        if not e or e["kind"] != "lieta":
            raise CaseError("Shēmas lietas ieraksts nav atrasts")
        if e["scheme_status"] != "Apstiprinats":
            raise CaseError("Lietu var atvērt tikai no apstiprinātas shēmas")
        if not (e["period_from"].year <= year <= e["period_to"].year):
            raise CaseError(f"Gads {year} nav shēmas periodā")
        row = await conn.fetchrow("SELECT * FROM standard_cases WHERE org_id = $1 AND case_index = $2 AND case_year = $3",
                                  org["id"], e["idx"], year)
        vals = (entry_id, e["retention_kind"], e["retention_years"], e["retention_trigger"], e["disposition"], e["long_running"])
        if row:
            if row["status"] != "Atverta":
                raise CaseError("Šī lieta jau ir slēgta")
            await conn.execute(
                """UPDATE standard_cases SET scheme_entry_id = $2, retention_kind = $3, retention_years = $4,
                          retention_trigger = $5, disposition = $6, long_running = $7, case_name = $8,
                          history = history || $9::jsonb WHERE id = $1""",
                row["id"], *vals, e["name"], _hist("SasaistitaArShemu", who, shema=entry_id))
            pk = row["id"]
        else:
            pk = await conn.fetchval(
                """INSERT INTO standard_cases (org_id, case_index, case_year, case_id, case_name, scheme_entry_id,
                          retention_kind, retention_years, retention_trigger, disposition, long_running, opened_at, history)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,NOW(),$12) RETURNING id""",
                org["id"], e["idx"], year, make_id(PREFIX_CASE, org["std_code"], datetime.now(timezone.utc)), e["name"],
                *vals, _hist("Atverta", who))
    return await get_case(org["id"], pk)


async def open_period(org: dict, year: int, who: str) -> dict:
    s = await active_scheme(org["id"], date(year, 6, 30))
    if not s:
        raise CaseError(f"{year}. gadam nav apstiprinātas klasifikācijas shēmas")
    pool = await get_pool()
    async with pool.acquire() as conn:
        ids = [r["id"] for r in await conn.fetch(
            "SELECT id FROM scheme_entries WHERE scheme_id = $1 AND kind = 'lieta' ORDER BY sort_order", s["id"])]
    opened = 0
    for i in ids:
        try:
            await open_case(org, i, year, who)
            opened += 1
        except CaseError:
            pass
    return {"shema": s["id"], "gads": year, "lietas": len(ids), "atvertas": opened}


async def attach_document(org: dict, case_pk: int, doc_id: int, who: str, actor_id: Optional[int]) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            c = await conn.fetchrow("SELECT * FROM standard_cases WHERE id = $1 AND org_id = $2", case_pk, org["id"])
            if not c:
                raise CaseError("Lieta nav atrasta")
            if c["status"] != "Atverta":
                raise CaseError("Slēgtā lietā dokumentus nepievieno (standarts 03, 3.5.)")
            d = await conn.fetchrow("SELECT id, case_id FROM documents WHERE id = $1", doc_id)
            if not d:
                raise CaseError("Dokuments nav atrasts")
            if d["case_id"] == case_pk:
                return {"ok": True, "nemainits": True}
            if d["case_id"]:
                old = await conn.fetchval("SELECT status FROM standard_cases WHERE id = $1", d["case_id"])
                if old != "Atverta":
                    raise CaseError("Dokuments ir slēgtā lietā — to pārvietot nevar")
            await conn.execute("UPDATE documents SET case_id = $2 WHERE id = $1", doc_id, case_pk)
            await conn.execute(
                "INSERT INTO document_events (document_id, event_type, actor_id, details) VALUES ($1, 'LietaPieskirta', $2, $3)",
                doc_id, actor_id, json.dumps({"lieta": c["case_id"], "indekss": c["case_index"], "gads": c["case_year"],
                                              "iepriekseja": d["case_id"], "kas": who}, ensure_ascii=False))
    return {"ok": True}


async def finish_document(doc_id: int, who: str, actor_id: Optional[int], note: Optional[str]) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("UPDATE documents SET finished_at = NOW() WHERE id = $1 AND finished_at IS NULL RETURNING id", doc_id)
        if r:
            await conn.execute(
                "INSERT INTO document_events (document_id, event_type, actor_id, details) VALUES ($1, 'Pabeigts', $2, $3)",
                doc_id, actor_id, json.dumps({"kas": who, "piezime": note}, ensure_ascii=False))
    return {"ok": True, "jau_bija": r is None}


async def close_case(org: dict, settings: dict, case_pk: int, who: str, storage) -> dict:
    """case.close@1: nepabeigti dokumenti bloķē; datumu robežas, apjoms, termiņa beigas, reģistrs ar SHA-256."""
    c = await get_case(org["id"], case_pk)
    if c["status"] != "Atverta":
        raise CaseError(f"Lieta jau ir statusā '{c['status_lv']}'")
    if c["nepabeigti"]:
        nr = [d["registration_number"] or f"#{d['id']}" for d in c["dokumenti"] if d["nepabeigts"]]
        raise CaseError(f"Lietā ir {len(nr)} nepabeigti dokumenti: {', '.join(nr[:10])}")
    if not c.get("retention_kind"):
        raise CaseError("Lietai nav glabāšanas termiņa — sasaistiet to ar shēmas ierakstu")
    pool = await get_pool()
    async with pool.acquire() as conn:
        docs = [dict(r) for r in await conn.fetch(
            """SELECT d.*, u.full_name AS creator_name,
                      EXISTS (SELECT 1 FROM document_events e WHERE e.document_id = d.id AND e.event_type = 'DocumentSent') AS _sent
                 FROM documents d LEFT JOIN users u ON u.id = d.created_by WHERE d.case_id = $1 ORDER BY d.created_at, d.id""", case_pk)]
        for d in docs:
            d["metadata"] = json.loads(d["metadata"]) if isinstance(d["metadata"], str) else (d["metadata"] or {})
        files: dict[int, list[str]] = {}
        for f in await conn.fetch("SELECT document_id, file_name FROM document_files WHERE document_id = ANY($1::bigint[]) ORDER BY id",
                                  [d["id"] for d in docs]):
            files.setdefault(f["document_id"], []).append(f["file_name"])
    related: dict[int, list[str]] = {}
    xml = register_xml(org, settings, c, docs, files, related)
    sha = hashlib.sha256(xml).hexdigest()
    key = f"arhivs/lietu-registri/{case_pk:06d}.xml"
    await storage.put(key, xml, "application/xml")
    today = datetime.now(timezone.utc)
    dates = [doc_date(d) for d in docs]
    dfrom, dto = (min(dates), max(dates)) if dates else (None, None)
    end = retention_end(c["retention_kind"], c["retention_years"], c["retention_trigger"], today.date(), dto)
    n_files = sum(len(v) for v in files.values())
    async with pool.acquire() as conn:
        async with conn.transaction():
            if not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM case_volumes WHERE case_id = $1 AND medium = 'E')", case_pk):
                nr = (await conn.fetchval("SELECT COALESCE(MAX(number), 0) FROM case_volumes WHERE case_id = $1", case_pk)) + 1
                await conn.execute(
                    """INSERT INTO case_volumes (case_id, number, medium, content_type, document_count, file_count)
                       VALUES ($1, $2, 'E', 'Teksts', $3, $4)""", case_pk, nr, len(docs), n_files)
            else:
                await conn.execute("UPDATE case_volumes SET document_count = $2, file_count = $3 WHERE case_id = $1 AND medium = 'E'",
                                   case_pk, len(docs), n_files)
            await conn.execute(
                """UPDATE standard_cases SET status = 'Slegta', closed_at = $2, date_from = $3, date_to = $4, retention_end = $5,
                          document_count = $6, file_count = $7, register_key = $8, register_sha256 = $9,
                          history = history || $10::jsonb WHERE id = $1""",
                case_pk, today, dfrom, dto, end, len(docs), n_files, key, sha,
                _hist("Slegta", who, dokumenti=len(docs), datnes=n_files, registraSha256=sha))
            for d in docs:
                await conn.execute(
                    "INSERT INTO document_events (document_id, event_type, details) VALUES ($1, 'LietaSlegta', $2)",
                    d["id"], json.dumps({"lieta": c["case_id"], "kas": who}, ensure_ascii=False))
    return await get_case(org["id"], case_pk)


async def mark_long_running(org: dict, case_pk: int, who: str) -> dict:
    """case.carry-over@1: ilgstoša lieta turpinās nākamajā periodā (MK 282 20., 43. p.)."""
    c = await get_case(org["id"], case_pk)
    if c["status"] != "Atverta":
        raise CaseError("Turpināt var tikai atvērtu lietu")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE standard_cases SET long_running = TRUE, history = history || $2::jsonb WHERE id = $1",
                           case_pk, _hist("Turpinas", who, nakamaisPeriods=c["case_year"] + 1))
    return await get_case(org["id"], case_pk)


async def add_volume(org: dict, case_pk: int, medium: str, content_type: str, document_count: Optional[int],
                     page_count: Optional[int], notes: Optional[str], who: str) -> dict:
    c = await get_case(org["id"], case_pk)
    pool = await get_pool()
    async with pool.acquire() as conn:
        nr = (await conn.fetchval("SELECT COALESCE(MAX(number), 0) FROM case_volumes WHERE case_id = $1", case_pk)) + 1
        await conn.execute(
            """INSERT INTO case_volumes (case_id, number, medium, content_type, document_count, page_count, notes)
               VALUES ($1,$2,$3,$4,$5,$6,$7)""", case_pk, nr, medium, content_type, document_count, page_count, notes)
        await conn.execute("UPDATE standard_cases SET history = history || $2::jsonb WHERE id = $1",
                           case_pk, _hist("SejumsPievienots", who, numurs=nr, nesejs=medium))
    return await get_case(org["id"], c["id"])


def case_xml(org: dict, c: dict) -> bytes:
    """ark:Lieta, pārbaudīts pret XSD."""
    A = lambda t: f"{{{ARK}}}{t}"
    if not c.get("shemas_ieraksts"):
        raise CaseError("Lieta nav sasaistīta ar klasifikācijas shēmu")
    root = etree.Element(A("Lieta"), nsmap={"ark": ARK})
    etree.SubElement(root, A("LietasID")).text = c["case_id"]
    sa = etree.SubElement(root, A("ShemasAtsauce"))
    etree.SubElement(sa, A("ShemasID")).text = f"shema-{c['shemas_ieraksts']['scheme_id']}"
    etree.SubElement(sa, A("Indekss")).text = c["case_index"]
    etree.SubElement(root, A("Gads")).text = str(c["case_year"])
    etree.SubElement(root, A("Nosaukums")).text = c.get("case_name") or c["case_index"]
    etree.SubElement(root, A("Statuss")).text = c["status"]
    etree.SubElement(root, A("AtvertaUz")).text = (c.get("opened_at") or c["created_at"]).isoformat()
    if c.get("closed_at"):
        etree.SubElement(root, A("SlegtaUz")).text = c["closed_at"].isoformat()
    if c.get("date_from"):
        dr = etree.SubElement(root, A("DatumuRobezas"))
        etree.SubElement(dr, A("No")).text = c["date_from"].isoformat()
        etree.SubElement(dr, A("Lidz")).text = c["date_to"].isoformat()
    vols = c["sejumi"] or [{"number": 1, "medium": "E", "content_type": "Teksts", "document_count": len(c["dokumenti"]),
                            "file_count": sum(d["datnes"] for d in c["dokumenti"])}]
    for v in vols:
        s = etree.SubElement(root, A("Sejums"))
        etree.SubElement(s, A("Numurs")).text = str(v["number"])
        etree.SubElement(s, A("Nesejs")).text = v["medium"]
        etree.SubElement(s, A("SaturaVeids")).text = v["content_type"]
        etree.SubElement(s, A("Apjoms"), mervieniba="dokumenti").text = str(v.get("document_count") or 0)
        if v.get("file_count") is not None:
            etree.SubElement(s, A("Apjoms"), mervieniba="datnes").text = str(v["file_count"])
        if v.get("page_count"):
            etree.SubElement(s, A("Apjoms"), mervieniba="lapas").text = str(v["page_count"])
    if c.get("retention_end"):
        etree.SubElement(root, A("GlabasanasBeigas")).text = c["retention_end"].isoformat()
    if c.get("disposition"):
        etree.SubElement(root, A("Riciba")).text = c["disposition"]
    if c.get("register_sha256"):
        etree.SubElement(root, A("RegistraKontrolsumma")).text = c["register_sha256"]
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    if not _xsd().validate(etree.fromstring(data).getroottree()):
        raise CaseError("Lieta neatbilst arhivesana-v1.xsd: " + "; ".join(e.message for e in list(_xsd().error_log)[:3]))
    return data
