"""Izvērtēšana (P4a) un iznīcināšanas akts (P4b) — MK 282 39.–40., 104.–109. p.; standarts 06.

Drošības principi:
- iznīcina tikai lietas statusā AtlasitaIznicinasanai, bez juridiska aizlieguma, ar beigušos termiņu
  (pārbauda vēlreiz izpildes brīdī);
- iznīcināšanu izpilda tikai pēc akta apstiprināšanas, ko DVS lietotājs (admin) apstiprina ar savu kontu;
- iznīcina datņu saturu visās glabātuvēs (S3 — visas versijas), reģistra ieraksts un akts paliek.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from typing import Optional

from lxml import etree

from opendms.archive import cases as cs
from opendms.archive import marks as mk
from opendms.archive.scheme import ARK, SchemeError, _xsd
from opendms.database import get_pool

A = lambda t: f"{{{ARK}}}{t}"  # noqa: E731
APPRAISAL_STATUSES = {"GlabaIestade", "AtlasitaIznicinasanai", "Izverteta"}
ACT_STATUS_LV = {"Projekts": "Projekts", "IzskatitsEK": "EK pārbaudīja", "IesniegtsLNA": "Iesniegts LNA",
                 "SaskanotsLNA": "LNA saskaņoja", "NoraiditsLNA": "LNA noraidīja", "NavJasaskano": "Nav jāsaskaņo",
                 "Apstiprinats": "Apstiprināts", "Iznicinats": "Iznīcināts", "Labojams": "Jālabo"}

SCHEMA = """
ALTER TABLE archive_settings ADD COLUMN IF NOT EXISTS auto_destruction_agreed BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE IF NOT EXISTS destruction_acts (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    number TEXT NOT NULL,
    act_date DATE NOT NULL DEFAULT CURRENT_DATE,
    status TEXT NOT NULL DEFAULT 'Projekts',
    case_ids BIGINT[] NOT NULL DEFAULT '{}',
    ek_protocol_no TEXT, ek_date DATE,
    lna_ref TEXT, lna_decision TEXT, lna_date DATE,
    created_by BIGINT REFERENCES users(id),
    approved_by BIGINT REFERENCES users(id), approved_at TIMESTAMPTZ,
    destroyed_at TIMESTAMPTZ, destroyed_by BIGINT REFERENCES users(id),
    xml_key TEXT, xml_sha256 TEXT,
    session_id TEXT,
    history JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS destroyed_at TIMESTAMPTZ;
ALTER TABLE document_files ADD COLUMN IF NOT EXISTS destroyed_at TIMESTAMPTZ;
"""


class ActError(SchemeError):
    pass


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


# ── P4a ──

async def mark_case(org: dict, case_pk: int, status: str, reason: str, who: str, rules: Optional[list] = None) -> dict:
    if status not in APPRAISAL_STATUSES:
        raise ActError(f"Nederīgs izvērtēšanas stāvoklis: {status}")
    c = await cs.get_case(org["id"], case_pk)
    if c["status"] not in ("Slegta", "Izverteta", "GlabaIestade"):
        raise ActError(f"Izvērtēt var slēgtu lietu (tagad: {c['status_lv']})")
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE standard_cases SET status = $2, history = history || $3::jsonb WHERE id = $1",
                           case_pk, status, cs._hist("Izverteta", who, rezultats=status, iemesls=reason, noteikumi=rules or []))
    return await cs.get_case(org["id"], case_pk)


# ── P4b: akts ──

async def _selected(conn, org_id: int, exclude_act: Optional[int]) -> list[dict]:
    rows = await conn.fetch(
        """SELECT c.*, e.retention_legal_basis FROM standard_cases c LEFT JOIN scheme_entries e ON e.id = c.scheme_entry_id
            WHERE c.org_id = $1 AND c.status = 'AtlasitaIznicinasanai'
              AND NOT EXISTS (SELECT 1 FROM destruction_acts a WHERE a.org_id = c.org_id AND c.id = ANY(a.case_ids)
                              AND a.status NOT IN ('Iznicinats') AND ($2::bigint IS NULL OR a.id <> $2))
            ORDER BY c.case_year, c.case_index""", org_id, exclude_act)
    return [dict(r) for r in rows]


async def draft_act(org: dict, who: str, user_id: Optional[int], act_id: Optional[int] = None,
                    session_id: Optional[str] = None) -> dict:
    """act.draft@1: visas lietas statusā AtlasitaIznicinasanai, kas vēl nav citā aktā."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            sel = await _selected(conn, org["id"], act_id)
            if act_id:
                a = await conn.fetchrow("SELECT * FROM destruction_acts WHERE id = $1 AND org_id = $2", act_id, org["id"])
                if not a or a["status"] in ("Apstiprinats", "Iznicinats"):
                    raise ActError("Apstiprinātu vai izpildītu aktu labot nevar")
                await conn.execute("""UPDATE destruction_acts SET case_ids = $2, status = 'Projekts', history = history || $3::jsonb
                                       WHERE id = $1""", act_id, [c["id"] for c in sel],
                                   cs._hist("Labots", who, lietas=len(sel)))
            else:
                if not sel:
                    raise ActError("Nav lietu, kas atlasītas iznīcināšanai (izvērtēšanas process)")
                n = await conn.fetchval("SELECT count(*) FROM destruction_acts WHERE org_id = $1 AND EXTRACT(YEAR FROM act_date) = $2",
                                        org["id"], date.today().year)
                act_id = await conn.fetchval(
                    """INSERT INTO destruction_acts (org_id, number, case_ids, created_by, session_id, history)
                       VALUES ($1, $2, $3, $4, $5, $6) RETURNING id""",
                    org["id"], f"{date.today().year}/{n + 1}", [c["id"] for c in sel], user_id, session_id,
                    cs._hist("Projekts", who, lietas=len(sel)))
    act = await get_act(org["id"], act_id)
    permanent = any(c["retention_kind"] == "Pastavigi" or c["disposition"] == "NodotArhivam" or c["legal_hold"]
                    for c in act["lietas"])
    s = await conn_settings(org["id"])
    return {**act, "irPastavigiVaiIlgstosi": permanent, "automatiskaIznicinasanaSaskanota": bool(s.get("auto_destruction_agreed"))}


async def conn_settings(org_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT * FROM archive_settings WHERE org_id = $1", org_id)
    return dict(r) if r else {}


async def get_act(org_id: int, act_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        a = await conn.fetchrow("SELECT * FROM destruction_acts WHERE id = $1 AND org_id = $2", act_id, org_id)
        if not a:
            raise ActError("Akts nav atrasts")
        rows = await conn.fetch(
            """SELECT c.*, e.retention_legal_basis,
                      (SELECT count(*) FROM documents d WHERE d.case_id = c.id) AS dokumenti,
                      (SELECT count(*) FROM document_files f JOIN documents d ON d.id = f.document_id WHERE d.case_id = c.id) AS datnes
                 FROM standard_cases c LEFT JOIN scheme_entries e ON e.id = c.scheme_entry_id
                WHERE c.id = ANY($1::bigint[]) ORDER BY c.case_year, c.case_index""", list(a["case_ids"]))
    out = dict(a)
    out["history"] = json.loads(out["history"]) if isinstance(out["history"], str) else out["history"]
    out["status_lv"] = ACT_STATUS_LV.get(out["status"], out["status"])
    out["lietas"] = [dict(r) for r in rows]
    return out


async def list_acts(org_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id, number, act_date, status, cardinality(case_ids) AS lietas, approved_at, destroyed_at, session_id
                                     FROM destruction_acts WHERE org_id = $1 ORDER BY id DESC""", org_id)
    return [dict(r) | {"status_lv": ACT_STATUS_LV.get(r["status"], r["status"])} for r in rows]


async def set_act(org_id: int, act_id: int, who: str, **fields) -> dict:
    allowed = {"status", "ek_protocol_no", "ek_date", "lna_ref", "lna_decision", "lna_date", "approved_by", "approved_at",
               "destroyed_at", "destroyed_by"}
    vals = {k: v for k, v in fields.items() if k in allowed}
    pool = await get_pool()
    async with pool.acquire() as conn:
        sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(vals))
        await conn.execute(f"UPDATE destruction_acts SET {sets}, history = history || $2::jsonb WHERE id = $1",
                           act_id, cs._hist(vals.get("status") or "Atjaunots", who, **{k: str(v) for k, v in vals.items()}),
                           *vals.values())
    return await get_act(org_id, act_id)


def act_xml(org: dict, settings: dict, act: dict, evaluators: list[dict]) -> bytes:
    """ark:IznicinasanasAkts (MK 282 5. pielikums), pārbaudīts pret XSD."""
    root = etree.Element(A("IznicinasanasAkts"), nsmap={"ark": ARK})
    etree.SubElement(root, A("Numurs")).text = act["number"]
    etree.SubElement(root, A("Datums")).text = act["act_date"].isoformat()
    ie = etree.SubElement(root, A("Iestade"))
    etree.SubElement(ie, A("OrgKods")).text = org["std_code"]
    etree.SubElement(ie, A("Nosaukums")).text = org["name"]
    if settings.get("registration_number") or org.get("reg_number"):
        etree.SubElement(ie, A("RegistracijasNr")).text = settings.get("registration_number") or org.get("reg_number")
    if settings.get("fonds_number"):
        etree.SubElement(root, A("FondaNumurs")).text = settings["fonds_number"]
    tot_docs = tot_files = 0
    for c in act["lietas"]:
        r = etree.SubElement(root, A("Ieraksts"))
        etree.SubElement(r, A("Nosaukums")).text = c.get("case_name") or c["case_index"]
        etree.SubElement(r, A("ShemasIndekss")).text = c["case_index"]
        dr = etree.SubElement(r, A("DatumuRobezas"))
        etree.SubElement(dr, A("No")).text = (c.get("date_from") or date(c["case_year"], 1, 1)).isoformat()
        etree.SubElement(dr, A("Lidz")).text = (c.get("date_to") or date(c["case_year"], 12, 31)).isoformat()
        etree.SubElement(r, A("Apjoms"), mervieniba="dokumenti").text = str(c["dokumenti"])
        etree.SubElement(r, A("Apjoms"), mervieniba="datnes").text = str(c["datnes"])
        gt = etree.SubElement(r, A("GlabasanasTermins"), veids=c.get("retention_kind") or "Gadi")
        gt.text = str(c["retention_years"]) if c.get("retention_kind") != "Pastavigi" and c.get("retention_years") else ""
        if c.get("retention_legal_basis"):
            etree.SubElement(r, A("Pamatojums")).text = c["retention_legal_basis"]
        etree.SubElement(r, A("LietasID")).text = c["case_id"]
        tot_docs += c["dokumenti"]
        tot_files += c["datnes"]
    etree.SubElement(root, A("Kopskaits"), mervieniba="dokumenti").text = str(tot_docs)
    etree.SubElement(root, A("Kopskaits"), mervieniba="datnes").text = str(tot_files)
    iz = etree.SubElement(root, A("Izvertetaji"))
    if act.get("ek_protocol_no"):
        ek = etree.SubElement(iz, A("EkspertuKomisija"))
        etree.SubElement(ek, A("ProtokolaNr")).text = act["ek_protocol_no"]
        etree.SubElement(ek, A("Datums")).text = (act.get("ek_date") or act["act_date"]).isoformat()
    for p in evaluators or [{"vardsUzvards": "DVS"}]:
        _persona(iz, "Persona", p)
    hist = [h for h in act["history"] if h.get("darbiba") in ("Projekts", "IzskatitsEK", "IesniegtsLNA", "SaskanotsLNA",
                                                                  "NoraiditsLNA", "NavJasaskano", "Apstiprinats")]
    for h in hist or [{"darbiba": "Projekts", "kad": act["created_at"].isoformat()}]:
        s = etree.SubElement(root, A("Saskanosana"))
        etree.SubElement(s, A("Statuss")).text = h["darbiba"]
        etree.SubElement(s, A("Datums")).text = str(h.get("kad"))[:10]
        if h.get("lna_ref") or h.get("ek_protocol_no"):
            etree.SubElement(s, A("Atsauce")).text = h.get("lna_ref") or h.get("ek_protocol_no")
    if act.get("destroyed_at"):
        za = etree.SubElement(root, A("IznicinasanasAtzime"))
        etree.SubElement(za, A("Datums")).text = act["destroyed_at"].date().isoformat()
        etree.SubElement(za, A("Veids")).text = "Elektronisko datņu dzēšana visās glabātuvēs, ieskaitot versijas"
        _persona(za, "Atbildigais", act.get("_destroyer") or {"vardsUzvards": "DVS"})
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    if not _xsd().validate(etree.fromstring(data).getroottree()):
        raise ActError("Akts neatbilst arhivesana-v1.xsd: " + "; ".join(e.message for e in list(_xsd().error_log)[:3]))
    return data


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


async def store_act_xml(org: dict, act_id: int, storage) -> dict:
    from opendms.archive.scheme import get_settings
    act = await get_act(org["id"], act_id)
    pool = await get_pool()
    people = []
    async with pool.acquire() as conn:
        for uid in {act.get("created_by"), act.get("approved_by")} - {None}:
            people.append(await mk._person(conn, uid))
        if act.get("destroyed_by"):
            act["_destroyer"] = await mk._person(conn, act["destroyed_by"])
    data = act_xml(org, await get_settings(org), act, people)
    key = f"arhivs/iznicinasanas-akti/{act_id:06d}.xml"
    await storage.put(key, data, "application/xml")
    sha = hashlib.sha256(data).hexdigest()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE destruction_acts SET xml_key = $2, xml_sha256 = $3 WHERE id = $1", act_id, key, sha)
    return {"key": key, "sha256": sha}


# ── izpilde ──

async def _purge(storage, key: str) -> int:
    """Dzēst objektu; S3 ar versijām — visas versijas un dzēšanas marķierus."""
    client = getattr(storage, "client", None)
    bucket = getattr(storage, "bucket", None)
    if client is None or bucket is None:
        return 1 if await storage.delete(key) else 0
    import asyncio

    def _all():
        n = 0
        try:
            vs = client.list_object_versions(Bucket=bucket, Prefix=key)
            items = [(v["Key"], v["VersionId"]) for v in vs.get("Versions", []) + vs.get("DeleteMarkers", []) if v["Key"] == key]
        except Exception:
            items = []
        for k, vid in items:
            client.delete_object(Bucket=bucket, Key=k, VersionId=vid)
            n += 1
        if not items:
            client.delete_object(Bucket=bucket, Key=key)
            n += 1
        return n
    return await asyncio.to_thread(_all)


async def execute(org: dict, act_id: int, storage, who: str) -> dict:
    """destruction.execute@1 — tikai apstiprinātam aktam; lietas pārbauda vēlreiz."""
    act = await get_act(org["id"], act_id)
    if act["status"] != "Apstiprinats" or not act.get("approved_by"):
        raise ActError("Iznīcināt var tikai pēc tam, kad akts apstiprināts DVS (iestādes vadītājs vai pilnvarotā persona)")
    today = date.today()
    for c in act["lietas"]:
        if c["status"] != "AtlasitaIznicinasanai":
            raise ActError(f"Lieta {c['case_index']}/{c['case_year']} vairs nav atlasīta iznīcināšanai ({c['status']})")
        if c["legal_hold"]:
            raise ActError(f"Lietai {c['case_index']}/{c['case_year']} ir juridisks aizliegums")
        if c["retention_kind"] == "Pastavigi" or c["disposition"] == "NodotArhivam":
            raise ActError(f"Lieta {c['case_index']}/{c['case_year']} ir pastāvīgi vai ilgstoši glabājama")
        if c.get("retention_end") and c["retention_end"] > today:
            raise ActError(f"Lietas {c['case_index']}/{c['case_year']} glabāšanas termiņš vēl nav beidzies")
    pool = await get_pool()
    removed = 0
    files_done = 0
    async with pool.acquire() as conn:
        docs = await conn.fetch("SELECT id, metadata FROM documents WHERE case_id = ANY($1::bigint[]) AND destroyed_at IS NULL",
                                [c["id"] for c in act["lietas"]])
        for d in docs:
            meta = json.loads(d["metadata"]) if isinstance(d["metadata"], str) else (d["metadata"] or {})
            keys = [r["storage_key"] for r in await conn.fetch("SELECT storage_key FROM document_files WHERE document_id = $1", d["id"])]
            pref = (meta.get("standartaPakotne") or {}).get("pakotnesAtslega")
            if pref:
                keys += [f"{pref}/{p}" for p in (meta.get("standartaPakotne") or {}).get("datnes", []) if p.startswith("datnes/")]
            for k in dict.fromkeys(k for k in keys if k):
                removed += await _purge(storage, k)
            files_done += await conn.fetchval(
                "WITH u AS (UPDATE document_files SET destroyed_at = NOW() WHERE document_id = $1 AND destroyed_at IS NULL RETURNING 1) SELECT count(*) FROM u", d["id"])
            await conn.execute(
                """UPDATE documents SET destroyed_at = NOW(), content_summary = NULL, semantic_summary = NULL,
                          metadata = (metadata - 'semantika' - 'teksts' - 'text') || $2::jsonb WHERE id = $1""",
                d["id"], json.dumps({"iznicinats": {"akts": act["number"], "kad": datetime.now(timezone.utc).isoformat()}}, ensure_ascii=False))
            await conn.execute(
                "INSERT INTO document_events (document_id, event_type, details) VALUES ($1, 'DokumentsIznicinats', $2)",
                d["id"], json.dumps({"akts": act["number"], "kas": who}, ensure_ascii=False))
    return {"iznicinatasDatnes": files_done, "dzestiObjekti": removed, "dokumenti": len(docs)}


async def record_destruction(org: dict, act_id: int, who: str, user_id: Optional[int], storage) -> dict:
    """act.record-destruction@1 — atzīme aktā, lietas Iznicinata, akta XML konteinerā."""
    prev = await get_act(org["id"], act_id)
    act = await set_act(org["id"], act_id, who, status="Iznicinats", destroyed_at=datetime.now(timezone.utc),
                        destroyed_by=user_id or prev.get("approved_by"))
    pool = await get_pool()
    async with pool.acquire() as conn:
        for c in act["lietas"]:
            await conn.execute("UPDATE standard_cases SET status = 'Iznicinata', history = history || $2::jsonb WHERE id = $1",
                               c["id"], cs._hist("Iznicinata", who, akts=act["number"]))
    x = await store_act_xml(org, act_id, storage)
    return {"atzimesDatums": date.today().isoformat(), "aktaXml": x["key"], "sha256": x["sha256"]}

