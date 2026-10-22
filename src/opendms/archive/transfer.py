"""Nodošana LNA (P6) — MK 282 46.–49., 69., 174.–176. p.; standarts 05 un 07.

Pakotni veido ar standarta rīku (archive/lna/builder.py = riki/izveidot_pakotni.py) no DVS datiem un pārbauda
ar standarta pārbaudītāju (archive/lna/validator.py = riki/validet_pakotni.py). Ar kļūdām pakotni nenodod.
Biroja datnēm pievieno PDF/A-2b atveidojumu (LibreOffice), oriģināls paliek.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from lxml import etree

from opendms.archive import cases as cs
from opendms.archive import docmeta as dmeta
from opendms.archive import finding_aid as fa
from opendms.archive import marks as mk
from opendms.archive import registration as rg
from opendms.archive.destruction import _persona
from opendms.archive.scheme import ARK, SchemeError, _xsd, get_settings
from opendms.database import get_pool

A = lambda t: f"{{{ARK}}}{t}"  # noqa: E731
STATUS_LV = {"Veidota": "Izveidota", "Deriga": "Pārbaudīta — derīga", "Nederiga": "Pārbaudīta — kļūdas", "Apstiprinata": "Apstiprināta nodošanai",
             "Nodota": "Nodota LNA", "Pienemta": "LNA pieņēma", "Noraidita": "LNA noraidīja"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS transfer_plans (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    year INTEGER NOT NULL,
    agreed_on DATE NOT NULL,
    lna_ref TEXT,
    notes TEXT,
    created_by BIGINT REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (org_id, year)
);
CREATE TABLE IF NOT EXISTS transfer_packages (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    plan_id BIGINT REFERENCES transfer_plans(id),
    list_id BIGINT REFERENCES inventory_lists(id),
    package_name TEXT,
    status TEXT NOT NULL DEFAULT 'Veidota',
    case_ids BIGINT[] NOT NULL DEFAULT '{}',
    zip_key TEXT, sha256 TEXT, size_bytes BIGINT,
    report JSONB,
    approved_by BIGINT REFERENCES users(id), approved_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ, delivery_ref TEXT,
    lna_decision TEXT, lna_ref TEXT, lna_date DATE, lna_notes TEXT,
    act_key TEXT, act_sha256 TEXT,
    session_id TEXT,
    history JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""


class TransferError(SchemeError):
    pass


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


def _j(v):
    return json.loads(v) if isinstance(v, str) else (v if v is not None else {})


# ── plāns ──

async def plan_check(org: dict, year: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        plan = await conn.fetchrow("SELECT * FROM transfer_plans WHERE org_id = $1 AND year = $2", org["id"], year)
        n = await conn.fetchval(
            """SELECT count(*) FROM standard_cases c
                WHERE c.org_id = $1 AND c.status = 'Aprakstita' AND c.retention_kind = 'Pastavigi'
                  AND EXISTS (SELECT 1 FROM inventory_lists l WHERE l.org_id = c.org_id AND l.status = 'Apstiprinats' AND c.id = ANY(l.case_ids))""",
            org["id"])
    return {"irPlans": bool(plan), "planaId": plan["id"] if plan else None, "lietuSkaits": n}


async def add_plan(org: dict, year: int, agreed_on: date, lna_ref: Optional[str], notes: Optional[str], user_id: Optional[int]) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO transfer_plans (org_id, year, agreed_on, lna_ref, notes, created_by) VALUES ($1,$2,$3,$4,$5,$6)
               ON CONFLICT (org_id, year) DO UPDATE SET agreed_on = EXCLUDED.agreed_on, lna_ref = EXCLUDED.lna_ref, notes = EXCLUDED.notes
               RETURNING id""", org["id"], year, agreed_on, lna_ref, notes, user_id)


# ── PDF/A ──

def to_pdfa(src: Path, outdir: Path) -> Optional[Path]:
    """Biroja datne → PDF/A-2b ar LibreOffice. None, ja LibreOffice nav vai konvertēšana neizdevās."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    ext = src.suffix.lower()
    flt = "calc_pdf_Export" if ext in (".xlsx", ".xls", ".ods", ".csv") else "writer_pdf_Export"
    opts = f'pdf:{flt}:{{"SelectPdfVersion":{{"type":"long","value":"2"}}}}'
    with tempfile.TemporaryDirectory() as prof:
        try:
            subprocess.run([soffice, f"-env:UserInstallation=file://{prof}", "--headless", "--convert-to", opts,
                            "--outdir", str(outdir), str(src)], check=True, timeout=180, capture_output=True)
        except Exception:
            return None
    out = outdir / (src.stem + ".pdf")
    return out if out.exists() else None


# ── pakotne ──

async def _doc_spec(conn, doc: dict, org_name: str, src: Path, fixes: list, storage) -> dict:
    meta = _j(doc["metadata"])
    rules = (meta.get("standartaPakotne") or {}).get("noteikumi") or {}
    events = [dict(r) for r in await conn.fetch("SELECT * FROM document_events WHERE document_id = $1 ORDER BY id", doc["id"])]
    marks = await mk.list_marks(doc["id"])
    files = await conn.fetch("SELECT * FROM document_files WHERE document_id = $1 AND destroyed_at IS NULL ORDER BY is_primary DESC, id", doc["id"])
    creator = await conn.fetchrow("SELECT full_name FROM users WHERE id = $1", doc["created_by"]) if doc.get("created_by") else None
    names, notes = [], []
    folder = src / f"d{doc['id']}"
    folder.mkdir(parents=True, exist_ok=True)
    for f in files:
        data = await storage.get(f["storage_key"])
        if data is None:
            fixes.append(f"{doc.get('registration_number') or doc['id']}: datne {f['file_name']} nav nolasāma glabātuvē")
            continue
        if f["checksum_sha256"] and hashlib.sha256(data).hexdigest() != f["checksum_sha256"]:
            fixes.append(f"{doc.get('registration_number') or doc['id']}: datnes {f['file_name']} kontrolsumma neatbilst")
        p = folder / f["file_name"]
        p.write_bytes(data)
        names.append(p.relative_to(src).as_posix())
        act = rg.file_action(f["mime_type"], f["file_name"], f["file_name"].lower().endswith((".edoc", ".asice", ".asics")))
        if act["riciba"] == "KonvertetPDFA":
            pdf = to_pdfa(p, folder / "pdfa")
            if pdf:
                target = folder / f"{p.stem}.pdfa.pdf"
                shutil.move(str(pdf), target)
                names.append(target.relative_to(src).as_posix())
                notes.append(f"{f['file_name']}: pievienots PDF/A-2b atveidojums (LibreOffice); oriģināls saglabāts")
            else:
                notes.append(f"{f['file_name']}: PDF/A atveidojums nav izveidots (LibreOffice nav pieejams)")
        elif not act["derigs"]:
            fixes.append(f"{doc.get('registration_number') or doc['id']}: datne {f['file_name']} nav glabājamā formātā")
    status = rules.get("infoStatus") or (meta.get("arhivs") or {}).get("infoStatus") or "IerobezotasPieejamibas"
    sign = [_j(e["details"]).get("persona", {}).get("vardsUzvards") for e in events if e["event_type"] == dmeta.EV_SIGN]
    sem = meta.get("semantika") or {}
    d = {
        "dokumenta_id": doc.get("doc_uid") or "",
        "arhiva_id": doc.get("archive_id") or "",
        "nosaukums": doc["title"],
        "datums": str(meta.get("documentDate") or doc["created_at"].date().isoformat())[:10],
        "sagatavosanas_datums": doc["created_at"].date().isoformat(),
        "nosutisanas_datums": dmeta.sent_date(events, meta),
        "registracijas_nr": doc.get("registration_number") or f"DVS-{doc['id']}",
        "sutitaja_nr": (meta.get("sender") or {}).get("reference"),
        "grupa": cs.document_group({"metadata": meta, "_sent": any(e["event_type"] == "DocumentSent" for e in events)}),
        "tips": (rules.get("documentType") or {}).get("name") or "Vispārīgs dokuments",
        "autori": [(meta.get("sender") or {}).get("name")] if (meta.get("sender") or {}).get("name") else [],
        "sagatavotaji": [creator["full_name"]] if creator else [],
        "parakstitaji": [s for s in sign if s],
        "adresati": [a["nosaukums"] for a in dmeta.addressees(meta, events)],
        "anotacija": doc.get("content_summary") or sem.get("kopsavilkums"),
        "atslegvardi": [k for k in (sem.get("atslegvardi") or []) if isinstance(k, str) and k.strip()],
        "vizas": [{"persona": v["persona"]["vardsUzvards"], "datums": str(v["datums"])[:10],
                   "piezimes": mk.VISA_RESULTS.get(v.get("rezultats"), "") + (f": {v['piezimes']}" if v.get("piezimes") else "")}
                  for v in marks["vizas"] if not v.get("aizstats")],
        "iepazisanas": [{"persona": v["persona"]["vardsUzvards"], "datums": str(v["datums"])[:10], "piezimes": v.get("piezimes") or ""}
                        for v in marks["iepazisanas"]],
        "rezolucijas": [{"atbildigais": ", ".join(p["vardsUzvards"] for p in t["atbildigie"]), "autors": v["persona"]["vardsUzvards"],
                         "uzdevums": t["apraksts"], "termins": t.get("termins") or "", "datums": str(v["datums"])[:10],
                         "piezimes": v.get("piezimes") or ""}
                        for v in marks["rezolucijas"] if not v.get("aizstats") for t in v["uzdevumi"]],
        "tehniska_informacija": "; ".join([f"{len(files)} datnes"] + notes),
        "piekluves_ierobezojums": (rules.get("legalBasis") or "Informācijas atklātības likuma 5. panta otrā daļa") if status != "Visparpieejama" else None,
        "informacijas_statuss": status,
        "datnes": names,
    }
    if not d["arhiva_id"]:
        fixes.append(f"{d['registracijas_nr']}: nav arhīva ID (dokuments nav sagatavots arhivēšanai)")
    if not names:
        fixes.append(f"{d['registracijas_nr']}: dokumentam nav datņu")
    return d


async def build(org: dict, plan_id: Optional[int], storage, who: str, package_id: Optional[int] = None,
                session_id: Optional[str] = None) -> dict:
    """transfer.build@1: viens uzskaites saraksts → viena OPEX pakotne (pastāvīgi glabājamās, aprakstītās lietas)."""
    from opendms.archive.lna import builder
    s = await get_settings(org)
    probs = fa.settings_problems(s)
    if probs:
        raise TransferError("; ".join(probs))
    pool = await get_pool()
    async with pool.acquire() as conn:
        lst = await conn.fetchrow(
            """SELECT l.id FROM inventory_lists l
                WHERE l.org_id = $1 AND l.status = 'Apstiprinats' AND l.retention_kind = 'Pastavigi'
                  AND EXISTS (SELECT 1 FROM standard_cases c WHERE c.id = ANY(l.case_ids) AND c.status = 'Aprakstita')
                ORDER BY l.number LIMIT 1""", org["id"])
        if package_id:
            p = await conn.fetchrow("SELECT list_id FROM transfer_packages WHERE id = $1", package_id)
            lst = {"id": p["list_id"]} if p else lst
    if not lst:
        raise TransferError("Nav LNA apstiprināta pastāvīgi glabājamo lietu uzskaites saraksta ar aprakstītām lietām")
    l = await fa.get_list(org["id"], lst["id"])
    cases = [c for c in l["lietas"] if c["status"] == "Aprakstita"]
    fixes: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        spec = {"izveides_datums": date.today().isoformat(),
                "arhivs": {"kods": s["archive_code"], "nosaukums": s["archive_name"]},
                "iestade": {"nosaukums": org["name"], "registracijas_nr": s.get("registration_number") or org.get("reg_number") or ""},
                "fonds": {"numurs": s["fonds_number"], "nosaukums": s["fonds_name"]},
                "saraksts": {"numurs": str(l["number"]), "nosaukums": l["title"]},
                "lietas": []}
        async with pool.acquire() as conn:
            for c in cases:
                docs = [dict(r) for r in await conn.fetch(
                    "SELECT * FROM documents WHERE case_id = $1 AND destroyed_at IS NULL ORDER BY created_at, id", c["id"])]
                spec["lietas"].append({"nr": c["kartas_numurs"], "indekss": c["case_index"], "nosaukums": c.get("case_name") or c["case_index"],
                                       "dokumenti": [await _doc_spec(conn, d, org["name"], src, fixes, storage) for d in docs]})
        empty = [x["indekss"] for x in spec["lietas"] if not x["dokumenti"]]
        if empty:
            fixes.append(f"Lietās nav dokumentu: {', '.join(empty)}")
            spec["lietas"] = [x for x in spec["lietas"] if x["dokumenti"]]
        if not spec["lietas"]:
            raise TransferError("Nav ko iekļaut pakotnē: " + "; ".join(fixes))
        for x in spec["lietas"]:
            for dd in x["dokumenti"]:
                if not dd["datnes"]:
                    dd["datnes"] = []
            x["dokumenti"] = [dd for dd in x["dokumenti"] if dd["datnes"]]
        root = builder.build(spec, Path(tmp) / "out", src)
        zpath = Path(str(root) + ".zip")
        data = zpath.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        name = root.name
    zip_key = f"arhivs/nodosana/{name}.zip"
    await storage.put(zip_key, data, "application/zip")
    await storage.put(zip_key + ".sha256", f"{sha}  {name}.zip\n".encode(), "text/plain")
    async with pool.acquire() as conn:
        if package_id:
            await conn.execute("""UPDATE transfer_packages SET package_name = $2, status = 'Veidota', case_ids = $3, zip_key = $4, sha256 = $5,
                                         size_bytes = $6, report = $7, history = history || $8::jsonb WHERE id = $1""",
                               package_id, name, [c["id"] for c in cases], zip_key, sha, len(data),
                               json.dumps({"labojumi": fixes}, ensure_ascii=False), cs._hist("Parveidota", who, sha256=sha))
        else:
            package_id = await conn.fetchval(
                """INSERT INTO transfer_packages (org_id, plan_id, list_id, package_name, case_ids, zip_key, sha256, size_bytes, report, session_id, history)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id""",
                org["id"], plan_id, l["id"], name, [c["id"] for c in cases], zip_key, sha, len(data),
                json.dumps({"labojumi": fixes}, ensure_ascii=False), session_id, cs._hist("Veidota", who, sha256=sha))
    return {"pakotnesId": package_id, "pakotne": name, "sha256": sha, "baiti": len(data), "labojumi": fixes}


async def validate(org: dict, package_id: int, storage) -> dict:
    """transfer.validate@1: standarta pārbaudītājs + DVS labojumu saraksts."""
    from opendms.archive.lna import validator
    p = await get_package(org["id"], package_id)
    data = await storage.get(p["zip_key"])
    if data is None:
        raise TransferError("Pakotne nav atrodama glabātuvē")
    with tempfile.TemporaryDirectory() as tmp:
        z = Path(tmp) / f"{p['package_name']}.zip"
        z.write_bytes(data)
        Path(str(z) + ".sha256").write_text(f"{p['sha256']}  {z.name}\n")
        rep = validator.validate_path(z)
    fixes = (_j(p.get("report")) or {}).get("labojumi") or []
    errors = [f"{i['vieta']}: {i['zinojums']}" for i in rep["ieraksti"] if i["limenis"] == "kluda"] + fixes
    warnings = [f"{i['vieta']}: {i['zinojums']}" for i in rep["ieraksti"] if i["limenis"] != "kluda"]
    ok = not errors
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE transfer_packages SET status = $2, report = $3, history = history || $4::jsonb WHERE id = $1",
                           package_id, "Deriga" if ok else "Nederiga",
                           json.dumps({"labojumi": fixes, "kludas": errors, "bridinajumi": warnings, "dokumenti": rep.get("dokumenti")}, ensure_ascii=False),
                           cs._hist("Parbaudita", "riki/validet_pakotni.py", kludas=len(errors), bridinajumi=len(warnings)))
    return {"pakotneDeriga": ok, "kludas": errors[:50], "bridinajumi": warnings[:50], "dokumenti": rep.get("dokumenti")}


async def get_package(org_id: int, package_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM transfer_packages WHERE id = $1 AND org_id = $2", package_id, org_id)
    if not p:
        raise TransferError("Nodošanas pakotne nav atrasta")
    out = dict(p)
    out["history"] = _j(out["history"]) or []
    out["report"] = _j(out["report"])
    out["status_lv"] = STATUS_LV.get(out["status"], out["status"])
    return out


async def list_packages(org_id: int) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id, package_name, status, cardinality(case_ids) AS lietas, size_bytes, sha256, created_at, session_id
                                     FROM transfer_packages WHERE org_id = $1 ORDER BY id DESC""", org_id)
    return [dict(r) | {"status_lv": STATUS_LV.get(r["status"], r["status"])} for r in rows]


async def set_package(org_id: int, package_id: int, who: str, **fields) -> dict:
    allowed = {"status", "approved_by", "approved_at", "delivered_at", "delivery_ref", "lna_decision", "lna_ref", "lna_date", "lna_notes"}
    vals = {k: v for k, v in fields.items() if k in allowed}
    pool = await get_pool()
    async with pool.acquire() as conn:
        sets = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(vals))
        await conn.execute(f"UPDATE transfer_packages SET {sets}, history = history || $2::jsonb WHERE id = $1",
                           package_id, cs._hist(vals.get("status") or "Atjaunots", who, **{k: str(v) for k, v in vals.items()}), *vals.values())
    return await get_package(org_id, package_id)


def transfer_act_xml(org: dict, settings: dict, p: dict, lst: dict, cases: list[dict], responsible: dict) -> bytes:
    """ark:NodosanasAkts (MK 282 176. p.)."""
    root = etree.Element(A("NodosanasAkts"), nsmap={"ark": ARK})
    etree.SubElement(root, A("Numurs")).text = f"N-{p['id']}"
    etree.SubElement(root, A("Datums")).text = (p.get("lna_date") or date.today()).isoformat()
    etree.SubElement(root, A("Iemesls")).text = "Pastāvīgi glabājamo dokumentu nodošana valsts glabāšanā (MK 282 46. p.)"
    nd = etree.SubElement(root, A("NododosaIestade"))
    ie = etree.SubElement(nd, A("Iestade"))
    etree.SubElement(ie, A("OrgKods")).text = org["std_code"]
    etree.SubElement(ie, A("Nosaukums")).text = org["name"]
    if settings.get("registration_number") or org.get("reg_number"):
        etree.SubElement(ie, A("RegistracijasNr")).text = settings.get("registration_number") or org.get("reg_number")
    _persona(nd, "Atbildigais", responsible)
    pn = etree.SubElement(root, A("PienemosaStrukturvieniba"))
    etree.SubElement(pn, A("Nosaukums")).text = settings.get("archive_name") or "Latvijas Nacionālais arhīvs"
    _persona(pn, "Atbildigais", {"vardsUzvards": p.get("lna_notes") or "LNA atbildīgā persona (norāda LNA)"})
    f = etree.SubElement(root, A("Fonds"))
    etree.SubElement(f, A("Numurs")).text = settings["fonds_number"]
    etree.SubElement(f, A("Nosaukums")).text = settings["fonds_name"]
    dr = etree.SubElement(f, A("DatumuRobezas"))
    froms = [c.get("date_from") or date(c["case_year"], 1, 1) for c in cases]
    tos = [c.get("date_to") or date(c["case_year"], 12, 31) for c in cases]
    etree.SubElement(dr, A("No")).text = min(froms).isoformat()
    etree.SubElement(dr, A("Lidz")).text = max(tos).isoformat()
    u = etree.SubElement(root, A("UzzinuSistema"))
    etree.SubElement(u, A("Veids")).text = "Uzskaites saraksts"
    etree.SubElement(u, A("Nosaukums")).text = lst["title"]
    etree.SubElement(u, A("Numurs")).text = str(lst["number"])
    etree.SubElement(u, A("VienibuSkaits")).text = str(len(lst["lietas"]))
    etree.SubElement(root, A("NodotoVienibuSkaits")).text = str(len(cases))
    pk = etree.SubElement(root, A("Pakotne"))
    etree.SubElement(pk, A("PakotnesID")).text = p["package_name"]
    etree.SubElement(pk, A("Kontrolsumma")).text = p["sha256"]
    etree.SubElement(pk, A("IzmersBaitos")).text = str(p["size_bytes"])
    rep = p.get("report") or {}
    etree.SubElement(root, A("ParbaudesRezultati")).text = (
        f"DVS pārbaude (riki/validet_pakotni.py): {rep.get('dokumenti')} dokumenti, {len(rep.get('kludas') or [])} kļūdas, "
        f"{len(rep.get('bridinajumi') or [])} brīdinājumi. LNA: {p.get('lna_decision')} {p.get('lna_ref') or ''}".strip())
    data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", pretty_print=True)
    if not _xsd().validate(etree.fromstring(data).getroottree()):
        raise TransferError("Nodošanas akts neatbilst XSD: " + "; ".join(e.message for e in list(_xsd().error_log)[:3]))
    return data


async def record(org: dict, package_id: int, storage, who: str) -> dict:
    """transfer.record@1: nodošanas un pieņemšanas akts; lietas NodotaLNA; dokumentiem DokumentsNodotsArhivam."""
    p = await get_package(org["id"], package_id)
    if p["status"] != "Pienemta":
        raise TransferError("Aktu reģistrē pēc LNA pieņemšanas")
    s = await get_settings(org)
    lst = await fa.get_list(org["id"], p["list_id"])
    cases = [c for c in lst["lietas"] if c["id"] in p["case_ids"]]
    pool = await get_pool()
    async with pool.acquire() as conn:
        resp = await mk._person(conn, p["approved_by"]) if p.get("approved_by") else {"vardsUzvards": "—"}
    data = transfer_act_xml(org, s, p, lst, cases, resp)
    key = f"arhivs/nodosana/{p['package_name']}.nodosanas-akts.xml"
    await storage.put(key, data, "application/xml")
    sha = hashlib.sha256(data).hexdigest()
    today = date.today().isoformat()
    n_docs = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("UPDATE transfer_packages SET act_key = $2, act_sha256 = $3, history = history || $4::jsonb WHERE id = $1",
                               package_id, key, sha, cs._hist("AktsRegistrets", who, sha256=sha))
            for c in cases:
                await conn.execute("UPDATE standard_cases SET status = 'NodotaLNA', history = history || $2::jsonb WHERE id = $1",
                                   c["id"], cs._hist("NodotaLNA", who, pakotne=p["package_name"]))
                for d in await conn.fetch("SELECT id FROM documents WHERE case_id = $1 AND destroyed_at IS NULL", c["id"]):
                    n_docs += 1
                    await conn.execute(
                        """UPDATE documents SET metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object('arhivs',
                                  COALESCE(metadata->'arhivs', '{}'::jsonb) || jsonb_build_object('nodots', $2::jsonb)) WHERE id = $1""", d["id"],
                        json.dumps({"pakotne": p["package_name"], "datums": today, "plans": p.get("plan_id")}))
                    await conn.execute("INSERT INTO document_events (document_id, event_type, details) VALUES ($1, 'DokumentsNodotsArhivam', $2)",
                                       d["id"], json.dumps({"pakotne": p["package_name"], "akts": key, "kas": who}, ensure_ascii=False))
    return {"aktaId": key, "nodotieDokumenti": n_docs, "sha256": sha}
