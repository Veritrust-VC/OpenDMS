"""Aprakstīšana: uzskaites saraksts un uzskaites kodi (P5) — MK 282 71.–97. p.; standarts 04.

Saraksts aptver lietas ar vienādu glabāšanas termiņa veidu, nesēju un satura veidu (84. p.).
Uzskaites kodu (LV_LNA_<Arh>_F<Fonds>_<US>_<GV>) piešķir tikai, kad LNA saraksts apstiprinājis.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from typing import Optional

from lxml import etree

from opendms.archive import cases as cs
from opendms.archive import marks as mk
from opendms.archive.destruction import _persona
from opendms.archive.scheme import ARK, SchemeError, _xsd, get_settings
from opendms.database import get_pool

A = lambda t: f"{{{ARK}}}{t}"  # noqa: E731
STATUS_LV = {"Projekts": "Projekts", "Derigs": "Pārbaudīts", "Parakstits": "Parakstīts", "IesniegtsLNA": "Iesniegts LNA",
             "Apstiprinats": "LNA apstiprināja", "NoraiditsLNA": "LNA noraidīja"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS inventory_lists (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    retention_kind TEXT NOT NULL,
    medium TEXT NOT NULL DEFAULT 'E',
    content_type TEXT NOT NULL DEFAULT 'Teksts',
    transfer_year INTEGER,
    status TEXT NOT NULL DEFAULT 'Projekts',
    case_ids BIGINT[] NOT NULL DEFAULT '{}',
    created_by BIGINT REFERENCES users(id),
    signed_by BIGINT[] NOT NULL DEFAULT '{}', signed_at TIMESTAMPTZ,
    lna_ref TEXT, lna_date DATE,
    xml_key TEXT, xml_sha256 TEXT,
    session_id TEXT,
    history JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (org_id, number)
);
"""


class ListError(SchemeError):
    pass


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


def code(settings: dict, us: Optional[int] = None, gv: Optional[int] = None, doc: Optional[int] = None) -> str:
    c = f"LV_LNA_{settings['archive_code']}_F{settings['fonds_number']}"
    for part in (us, gv, doc):
        if part is None:
            break
        c += f"_{part}"
    return c


def settings_problems(s: dict) -> list[str]:
    out = []
    if not s.get("archive_code") or not re.fullmatch(r"[A-Z]{2,10}", s["archive_code"] or ""):
        out.append("Arhīva kods (piem. LVA) nav iestatīts — Arhīvs → Iestatījumi")
    if not s.get("fonds_number") or not re.fullmatch(r"[0-9A-Z]+", s["fonds_number"] or ""):
        out.append("Fonda numurs nav iestatīts — Arhīvs → Iestatījumi")
    for k, n in (("archive_name", "arhīva nosaukums"), ("fonds_name", "fonda nosaukums")):
        if not s.get(k):
            out.append(f"Nav norādīts {n} — Arhīvs → Iestatījumi")
    return out


async def draft(org: dict, who: str, user_id: Optional[int], list_id: Optional[int] = None,
                session_id: Optional[str] = None) -> dict:
    """finding-aid.draft@1: lietas statusā Izverteta (aprakstīšanai), vēl nevienā sarakstā; viena grupa (84. p.)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = [dict(r) for r in await conn.fetch(
                """SELECT c.id, c.retention_kind, c.case_year, c.case_index,
                          COALESCE((SELECT string_agg(DISTINCT v.medium, '') FROM case_volumes v WHERE v.case_id = c.id), 'E') AS media
                     FROM standard_cases c
                    WHERE c.org_id = $1 AND c.status = 'Izverteta'
                      AND NOT EXISTS (SELECT 1 FROM inventory_lists l WHERE l.org_id = c.org_id AND c.id = ANY(l.case_ids)
                                      AND ($2::bigint IS NULL OR l.id <> $2))
                    ORDER BY c.case_year, c.case_index""", org["id"], list_id)]
            for r in rows:
                r["medium"] = "H" if len(set(r["media"])) > 1 else r["media"][:1]
            groups: dict = {}
            for r in rows:
                groups.setdefault((r["retention_kind"] or "Gadi", r["medium"]), []).append(r)
            if list_id:
                lst = await conn.fetchrow("SELECT * FROM inventory_lists WHERE id = $1 AND org_id = $2", list_id, org["id"])
                if not lst or lst["status"] == "Apstiprinats":
                    raise ListError("Apstiprinātu sarakstu labot nevar")
                key = (lst["retention_kind"], lst["medium"])
                sel = groups.get(key, [])
                await conn.execute("UPDATE inventory_lists SET case_ids = $2, status = 'Projekts', history = history || $3::jsonb WHERE id = $1",
                                   list_id, [r["id"] for r in sel], cs._hist("Labots", who, vienibas=len(sel)))
            else:
                if not groups:
                    raise ListError("Nav lietu aprakstīšanai (izvērtēšanā: aprakstīt un nodot LNA)")
                key = sorted(groups, key=lambda k: (k[0] != "Pastavigi", k[1] != "E"))[0]
                sel = groups[key]
                n = (await conn.fetchval("SELECT COALESCE(MAX(number), 0) FROM inventory_lists WHERE org_id = $1", org["id"])) + 1
                kind = "Pastāvīgi" if key[0] == "Pastavigi" else "Ilgstoši"
                nes = {"E": "elektronisko", "P": "papīra", "H": "hibrīdo", "C": "citu"}[key[1]]
                list_id = await conn.fetchval(
                    """INSERT INTO inventory_lists (org_id, number, title, retention_kind, medium, case_ids, created_by, session_id, history)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id""",
                    org["id"], n, f"{kind} glabājamo {nes} lietu uzskaites saraksts Nr. {n}", key[0], key[1],
                    [r["id"] for r in sel], user_id, session_id, cs._hist("Projekts", who, vienibas=len(sel)))
    return await get_list(org["id"], list_id)


async def get_list(org_id: int, list_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        l = await conn.fetchrow("SELECT * FROM inventory_lists WHERE id = $1 AND org_id = $2", list_id, org_id)
        if not l:
            raise ListError("Uzskaites saraksts nav atrasts")
        rows = await conn.fetch(
            """SELECT c.*, e.access_basis, e.access_until, e.default_info_status, p.idx AS series_idx, p.name AS series_name
                 FROM standard_cases c
                 LEFT JOIN scheme_entries e ON e.id = c.scheme_entry_id
                 LEFT JOIN scheme_entries p ON p.id = e.parent_id
                WHERE c.id = ANY($1::bigint[])""", list(l["case_ids"]))
        by = {r["id"]: dict(r) for r in rows}
        vols = await conn.fetch("SELECT * FROM case_volumes WHERE case_id = ANY($1::bigint[]) ORDER BY case_id, number", list(l["case_ids"]))
    out = dict(l)
    out["history"] = json.loads(out["history"]) if isinstance(out["history"], str) else out["history"]
    out["status_lv"] = STATUS_LV.get(out["status"], out["status"])
    out["lietas"] = []
    for n, cid in enumerate(l["case_ids"], 1):
        c = by.get(cid)
        if c:
            c["kartas_numurs"] = n
            c["sejumi"] = [dict(v) for v in vols if v["case_id"] == cid]
            out["lietas"].append(c)
    return out


async def list_lists(org_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id, number, title, status, cardinality(case_ids) AS vienibas, created_at, session_id
                                     FROM inventory_lists WHERE org_id = $1 ORDER BY number DESC""", org_id)
    return [dict(r) | {"status_lv": STATUS_LV.get(r["status"], r["status"])} for r in rows]


def list_xml(org: dict, settings: dict, l: dict, authors: list[dict], with_codes: bool = True) -> bytes:
    root = etree.Element(A("UzskaitesSaraksts"), nsmap={"ark": ARK}, numurs=str(l["number"]))
    ie = etree.SubElement(root, A("Iestade"))
    etree.SubElement(ie, A("OrgKods")).text = org["std_code"]
    etree.SubElement(ie, A("Nosaukums")).text = org["name"]
    if settings.get("registration_number") or org.get("reg_number"):
        etree.SubElement(ie, A("RegistracijasNr")).text = settings.get("registration_number") or org.get("reg_number")
    ar = etree.SubElement(root, A("Arhivs"))
    etree.SubElement(ar, A("Kods")).text = settings.get("archive_code") or "—"
    etree.SubElement(ar, A("Nosaukums")).text = settings.get("archive_name") or "—"
    etree.SubElement(root, A("FondaNumurs")).text = settings.get("fonds_number") or "—"
    etree.SubElement(root, A("FondaNosaukums")).text = settings.get("fonds_name") or "—"
    gt = etree.SubElement(root, A("GlabasanasTermins"), veids="Pastavigi" if l["retention_kind"] == "Pastavigi" else "Gadi")
    if l["retention_kind"] != "Pastavigi":
        yrs = sorted({c.get("retention_years") for c in l["lietas"] if c.get("retention_years")})
        gt.text = str(yrs[-1]) if yrs else ""
    etree.SubElement(root, A("Nesejs")).text = l["medium"]
    etree.SubElement(root, A("SaturaVeids")).text = l["content_type"]
    if l.get("transfer_year"):
        etree.SubElement(root, A("ParedzetaisNodosanasGads")).text = str(l["transfer_year"])
    for c in l["lietas"]:
        v = etree.SubElement(root, A("Vieniba"), kartasNumurs=str(c["kartas_numurs"]))
        etree.SubElement(v, A("SerijasKods")).text = c.get("series_idx") or c["case_index"].replace("-", ".").split(".")[0]
        etree.SubElement(v, A("Nosaukums")).text = c.get("case_name") or c["case_index"]
        dr = etree.SubElement(v, A("DatumuRobezas"))
        etree.SubElement(dr, A("No")).text = (c.get("date_from") or date(c["case_year"], 1, 1)).isoformat()
        etree.SubElement(dr, A("Lidz")).text = (c.get("date_to") or date(c["case_year"], 12, 31)).isoformat()
        etree.SubElement(v, A("Apjoms"), mervieniba="dokumenti").text = str(c.get("document_count") or 0)
        etree.SubElement(v, A("Apjoms"), mervieniba="datnes").text = str(c.get("file_count") or 0)
        pages = sum(x.get("page_count") or 0 for x in c["sejumi"])
        if pages:
            etree.SubElement(v, A("Apjoms"), mervieniba="lapas").text = str(pages)
        if len({x["medium"] for x in c["sejumi"]}) > 1:
            etree.SubElement(v, A("HibridasNorades")).text = "; ".join(
                f"{x['number']}. sējums: {x['medium']}" + (f", {x['notes']}" if x.get("notes") else "") for x in c["sejumi"])
        etree.SubElement(v, A("Valoda")).text = "lv"
        if (c.get("default_info_status") or "Visparpieejama") != "Visparpieejama":
            pi = etree.SubElement(v, A("PiekluvesIerobezojums"))
            etree.SubElement(pi, A("TiesiskaisPamatojums")).text = c.get("access_basis") or "Informācijas atklātības likuma 5. panta otrā daļa"
            if c.get("access_until"):
                etree.SubElement(pi, A("IerobezojumsLidz")).text = c["access_until"].isoformat()
        etree.SubElement(v, A("LietasID")).text = c["case_id"]
        etree.SubElement(v, A("UzskaitesKods")).text = (code(settings, l["number"], c["kartas_numurs"])
                                                       if with_codes and settings.get("archive_code") and settings.get("fonds_number")
                                                       else f"LV_LNA_{settings.get('archive_code') or 'XX'}")
    k = etree.SubElement(root, A("Kopsavilkums"))
    etree.SubElement(k, A("VienibuSkaits")).text = str(len(l["lietas"]))
    for p in authors or [{"vardsUzvards": "DVS"}]:
        _persona(root, "Sastadija", p)
    hist = [h for h in l["history"] if h.get("darbiba") in ("Projekts", "IesniegtsLNA", "Apstiprinats", "NoraiditsLNA")]
    for h in hist or [{"darbiba": "Projekts", "kad": date.today().isoformat()}]:
        s = etree.SubElement(root, A("Saskanosana"))
        etree.SubElement(s, A("Statuss")).text = {"NoraiditsLNA": "NoraiditsLNA"}.get(h["darbiba"], h["darbiba"])
        etree.SubElement(s, A("Datums")).text = str(h.get("kad"))[:10]
        if h.get("lna_ref"):
            etree.SubElement(s, A("Atsauce")).text = h["lna_ref"]
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)


async def _authors(conn, l: dict) -> list[dict]:
    out = []
    for uid in [l.get("created_by")] + list(l.get("signed_by") or []):
        if uid and uid not in [p.get("id") for p in out]:
            out.append(await mk._person(conn, uid))
    return out


async def validate(org: dict, list_id: int) -> dict:
    """finding-aid.validate@1: iestatījumi, XSD, vienības (86.–88. p.)."""
    s = await get_settings(org)
    l = await get_list(org["id"], list_id)
    errors = settings_problems(s)
    if not l["lietas"]:
        errors.append("Sarakstā nav vienību")
    for c in l["lietas"]:
        if c["status"] != "Izverteta":
            errors.append(f"{c['case_index']}/{c['case_year']}: lieta nav statusā Izvērtēta ({c['status']})")
        if not c.get("date_from"):
            errors.append(f"{c['case_index']}/{c['case_year']}: nav datumu robežu (lieta nav slēgta ar procesu)")
        if not c.get("register_sha256"):
            errors.append(f"{c['case_index']}/{c['case_year']}: nav lietas dokumentu reģistra")
    pool = await get_pool()
    async with pool.acquire() as conn:
        data = list_xml(org, s, l, await _authors(conn, l))
    if not _xsd().validate(etree.fromstring(data).getroottree()):
        errors += [f"XSD: {e.message}" for e in list(_xsd().error_log)[:10]]
    async with pool.acquire() as conn:
        if not errors and l["status"] == "Projekts":
            await conn.execute("UPDATE inventory_lists SET status = 'Derigs', history = history || $2::jsonb WHERE id = $1",
                               list_id, cs._hist("Parbaudits", "DVS"))
        elif errors:
            await conn.execute("UPDATE inventory_lists SET history = history || $2::jsonb WHERE id = $1",
                               list_id, cs._hist("PārbaudesKļūdas", "DVS", kludas=errors[:30]))
    return {"sarakstsDerigs": not errors, "kludas": errors}


async def store_xml(org: dict, list_id: int, storage) -> dict:
    s = await get_settings(org)
    l = await get_list(org["id"], list_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        data = list_xml(org, s, l, await _authors(conn, l))
        key = f"arhivs/uzskaites-saraksti/{list_id:06d}.xml"
        await storage.put(key, data, "application/xml")
        sha = hashlib.sha256(data).hexdigest()
        await conn.execute("UPDATE inventory_lists SET xml_key = $2, xml_sha256 = $3 WHERE id = $1", list_id, key, sha)
    return {"key": key, "sha256": sha}


async def set_list(org_id: int, list_id: int, who: str, **fields) -> dict:
    allowed = {"status", "lna_ref", "lna_date", "signed_at", "transfer_year"}
    vals = {k: v for k, v in fields.items() if k in allowed}
    pool = await get_pool()
    async with pool.acquire() as conn:
        sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(vals))
        await conn.execute(f"UPDATE inventory_lists SET {sets}, history = history || $2::jsonb WHERE id = $1",
                           list_id, cs._hist(vals.get("status") or "Atjaunots", who, **{k: str(v) for k, v in vals.items()}),
                           *vals.values())
    return await get_list(org_id, list_id)


async def sign(org: dict, list_id: int, user_id: int, who: str) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""UPDATE inventory_lists SET signed_by = array_append(signed_by, $2), signed_at = NOW(), status = 'Parakstits',
                                     history = history || $3::jsonb WHERE id = $1 AND NOT ($2 = ANY(signed_by))""",
                           list_id, user_id, cs._hist("Parakstits", who))
    return await get_list(org["id"], list_id)


async def approve(org: dict, list_id: int, who: str, storage) -> dict:
    """finding-aid.approve@1: uzskaites kodi lietām, lietas Aprakstita (tikai pēc LNA apstiprinājuma)."""
    s = await get_settings(org)
    l = await get_list(org["id"], list_id)
    if l["status"] != "Apstiprinats":
        raise ListError("Uzskaites kodus piešķir pēc LNA apstiprinājuma")
    probs = settings_problems(s)
    if probs:
        raise ListError("; ".join(probs))
    codes = {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for c in l["lietas"]:
                kods = code(s, l["number"], c["kartas_numurs"])
                codes[c["case_index"]] = kods
                await conn.execute("UPDATE standard_cases SET status = 'Aprakstita', uzskaites_kods = $2, history = history || $3::jsonb WHERE id = $1",
                                   c["id"], kods, cs._hist("Aprakstita", who, uzskaitesKods=kods, saraksts=l["number"]))
    await store_xml(org, list_id, storage)
    return {"uzskaitesKodi": codes}
