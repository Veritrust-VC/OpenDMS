"""Copy this DVS into its S3 bucket (konteiners) — the container becomes the complete record.

Layout (one container per system):

    dokumenti/<mape>/                    <mape> = package folder (LV-DOK_…) or DVS-<id>
        metadati.xml, izsekosana.xml, SHA256SUMS, datnes/…   ← the standard package, as is
        datnes/…                         ← any document file not in a package yet
        dvs-ieraksts.json                ← the DVS record of the document: its row
                                           (metadata incl. semantics, intake, forwarding,
                                           process results) and every row that belongs
                                           to it — files, events, process sessions,
                                           classifications, agent runs, AI log
    ievade/<id>.json                     ← every intake item, also rejected ones
    zinasanas/precedenti/<id>.json       ← staff corrections the classifier learns from
    agenti/<id>.json                     ← agent conversations not tied to a document
                                           (run with its steps and messages)
    lietas/<id>.json                     ← case nomenclature (lietas)
    arhivs/partijas/<id>.json            ← archive batches with their documents
    vesture/integracijas/<YYYY-MM>.json  ← integration audit log
    indekss.json                         ← manifest: documents, objects, sha256

Not copied — configuration, restored from deployment: users, organisation and
structure, classifiers, templates, process triggers and sources, AI instructions,
connections and secrets, settings.

Each object carries x-amz-meta-sha256. A re-run skips unchanged objects, so the
version history only grows when something changed. After writing, every object
is read back and its SHA-256 compared. rebuild.py reads the same layout back.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import time
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from opendms.database import get_pool
from opendms.storage import get_storage, layout

FORMAT = "opendms-konteiners/1"

# Rows that belong to one document, stored in its dvs-ieraksts.json under "tabulas".
DOC_TABLES = [
    ("document_files", "document_id = $1"),
    ("document_events", "document_id = $1"),
    ("uapf_sessions", "document_id = $1"),
    ("complaint_classifications", "document_id = $1"),
    ("ai_processing_log", "document_id = $1"),
    ("agent_runs", "document_id = $1"),
    ("agent_steps", "run_id IN (SELECT id FROM agent_runs WHERE document_id = $1)"),
    ("agent_messages", "run_id IN (SELECT id FROM agent_runs WHERE document_id = $1)"),
]

# Tables counted in the manifest besides the per-document ones
SHARED_COUNTS = ["intake_items", "uapf_precedents", "standard_cases", "archive_batches",
                 "archive_batch_documents", "integration_audit_log", "agent_runs", "agent_steps", "agent_messages"]

# Everything rebuild.py restores, in an order that satisfies foreign keys.
KNOWLEDGE_TABLES = ["standard_cases", "documents", "uapf_sessions", "document_files", "document_events",
                    "complaint_classifications", "ai_processing_log", "agent_runs", "agent_steps",
                    "agent_messages", "archive_batches", "archive_batch_documents", "intake_items",
                    "uapf_precedents", "integration_audit_log"]


def _json(o: Any) -> bytes:
    def default(x):
        if isinstance(x, (datetime, date)):
            return x.isoformat()
        if isinstance(x, Decimal):
            return str(x)            # exact; rebuild casts back to numeric
        if isinstance(x, (bytes, bytearray)):
            return x.hex()
        return str(x)
    return json.dumps(o, ensure_ascii=False, indent=2, default=default).encode()


async def _jsonb_cols(conn) -> dict[str, set]:
    rows = await conn.fetch("""SELECT table_name, column_name FROM information_schema.columns
                               WHERE table_schema = 'public' AND data_type IN ('jsonb', 'json')""")
    out: dict[str, set] = {}
    for r in rows:
        out.setdefault(r["table_name"], set()).add(r["column_name"])
    return out


def _rows(rows, jcols: set) -> list[dict]:
    """Rows as dicts; json/jsonb columns decoded (asyncpg returns them as text)."""
    out = []
    for r in rows:
        d = dict(r)
        for k in jcols & d.keys():
            if isinstance(d[k], str):
                try:
                    d[k] = json.loads(d[k])
                except Exception:
                    pass
        out.append(d)
    return out


async def _walk(storage, prefix: str) -> list[str]:
    keys, stack = [], [prefix.rstrip("/")]
    while stack:
        p = stack.pop()
        try:
            lst = await storage.list(p)
        except Exception:
            continue
        keys += [f"{p}/{f['name']}" for f in lst.get("files", [])]
        stack += [f"{p}/{d}" for d in lst.get("folders", [])]
    return keys


# ── builders shared by the export and the record sync (storage/sync.py) ──

KINDS = {  # kind → (table, key prefix)
    "ievade": ("intake_items", "ievade"),
    "precedents": ("uapf_precedents", "zinasanas/precedenti"),
    "lieta": ("standard_cases", "lietas"),
    "arhivs": ("archive_batches", "arhivs/partijas"),
}


async def doc_record(conn, jc: dict, doc_id: int) -> Optional[tuple[str, dict, dict]]:
    """(folder, document row, rows by table) — or None if the document no longer exists."""
    rows = _rows(await conn.fetch("SELECT * FROM documents WHERE id = $1", doc_id), jc.get("documents", set()))
    if not rows:
        return None
    d = rows[0]
    tabulas = {t: _rows(await conn.fetch(f"SELECT * FROM {t} WHERE {where} ORDER BY id", doc_id), jc.get(t, set()))
               for t, where in DOC_TABLES}
    return layout.folder(d["id"], d.get("doc_uid")), d, tabulas


def record_bytes(d: dict, tabulas: dict) -> bytes:
    return _json({"formats": FORMAT, "dokuments": d, "tabulas": tabulas})


async def shared_object(conn, jc: dict, kind: str, ref: int) -> tuple[str, Optional[bytes]]:
    """(key, bytes) of one shared object; bytes None = the source rows are gone (delete the object)."""
    if kind == "integracijas":                        # ref = YYYYMM
        y, m = divmod(ref, 100)
        rows = _rows(await conn.fetch(
            """SELECT * FROM integration_audit_log WHERE created_at >= make_timestamptz($1, $2, 1, 0, 0, 0, 'UTC')
                 AND created_at < make_timestamptz($1, $2, 1, 0, 0, 0, 'UTC') + interval '1 month' ORDER BY id""", y, m),
            jc.get("integration_audit_log", set()))
        return f"vesture/integracijas/{y:04d}-{m:02d}.json", (
            _json({"formats": FORMAT, "tabula": "integration_audit_log", "rindas": rows}) if rows else None)
    if kind == "agents":                              # agent conversation without a document
        key = f"agenti/{ref:06d}.json"
        r = _rows(await conn.fetch("SELECT * FROM agent_runs WHERE id = $1 AND document_id IS NULL", ref), jc.get("agent_runs", set()))
        if not r:
            return key, None
        steps = _rows(await conn.fetch("SELECT * FROM agent_steps WHERE run_id = $1 ORDER BY id", ref), jc.get("agent_steps", set()))
        msgs = _rows(await conn.fetch("SELECT * FROM agent_messages WHERE run_id = $1 ORDER BY id", ref), jc.get("agent_messages", set()))
        return key, _json({"formats": FORMAT, "tabulas": {"agent_runs": r, "agent_steps": steps, "agent_messages": msgs}})
    table, prefix = KINDS[kind]
    key = f"{prefix}/{ref:06d}.json"
    r = _rows(await conn.fetch(f"SELECT * FROM {table} WHERE id = $1", ref), jc.get(table, set()))
    if not r:
        return key, None
    if kind == "arhivs":
        r[0]["dokumenti"] = [x["document_id"] for x in await conn.fetch(
            "SELECT document_id FROM archive_batch_documents WHERE batch_id = $1 ORDER BY document_id", ref)]
    return key, _json(r[0])


async def shared_refs(conn) -> list[tuple[str, int]]:
    """Every shared object that should exist now."""
    refs = []
    for kind, (table, _p) in KINDS.items():
        refs += [(kind, r["id"]) for r in await conn.fetch(f"SELECT id FROM {table} ORDER BY id")]
    refs += [("integracijas", int(r["m"])) for r in await conn.fetch(
        "SELECT DISTINCT to_char(created_at AT TIME ZONE 'UTC', 'YYYYMM') m FROM integration_audit_log ORDER BY 1")]
    refs += [("agents", r["id"]) for r in await conn.fetch("SELECT id FROM agent_runs WHERE document_id IS NULL ORDER BY id")]
    return refs


async def collect() -> tuple[list[dict], dict]:
    """Everything to write: [{key, data, mime}] and the manifest."""
    st = get_storage()
    pool = await get_pool()
    objs, manifest_docs, problems, counts = [], [], [], {}
    async with pool.acquire() as conn:
        jc = await _jsonb_cols(conn)
        org = dict(await conn.fetchrow("SELECT id, name, code, org_did, std_code FROM organizations WHERE is_default LIMIT 1") or {})
        for (doc_id,) in await conn.fetch("SELECT id FROM documents ORDER BY id"):
            folder, d, tabulas = await doc_record(conn, jc, doc_id)
            counts["documents"] = counts.get("documents", 0) + 1
            for t, rows in tabulas.items():
                counts[t] = counts.get(t, 0) + len(rows)
            pk = (d.get("metadata") or {}).get("standartaPakotne") or {}
            base = f"{layout.ROOT}/{folder}"
            doc_objs, in_pkg = [], set()
            if pk.get("pakotnesAtslega"):
                for k in await _walk(st, pk["pakotnesAtslega"]):
                    rel = k[len(pk["pakotnesAtslega"]):].lstrip("/")
                    if rel == "dvs-ieraksts.json":
                        continue
                    data = await st.get(k)
                    if data is None:
                        problems.append(f"{folder}: {rel} nav nolasāms")
                        continue
                    doc_objs.append({"key": f"{base}/{rel}", "data": data})
                    if rel.startswith("datnes/"):
                        in_pkg.add(rel[len("datnes/"):])
            for f in tabulas["document_files"]:
                if f["file_name"] in in_pkg:
                    continue
                data = await st.get(f["storage_key"]) if f.get("storage_key") else None
                if data is None:
                    problems.append(f"{folder}: datne {f['file_name']} nav nolasāma")
                    continue
                if f.get("checksum_sha256") and hashlib.sha256(data).hexdigest() != f["checksum_sha256"]:
                    problems.append(f"{folder}: datne {f['file_name']} — kontrolsumma neatbilst DVS ierakstam")
                doc_objs.append({"key": f"{base}/datnes/{f['file_name']}", "data": data})
            doc_objs.append({"key": f"{base}/dvs-ieraksts.json", "data": record_bytes(d, tabulas), "mime": "application/json"})
            objs += doc_objs
            manifest_docs.append({"mape": folder, "dvsId": d["id"], "registracijasNr": d.get("registration_number"),
                                  "dokumentaId": d.get("doc_uid"), "registraDid": d.get("doc_did"),
                                  "objekti": [{"key": o["key"][len(base) + 1:], "sha256": hashlib.sha256(o["data"]).hexdigest(),
                                               "baiti": len(o["data"])} for o in doc_objs]})
        for kind, ref in await shared_refs(conn):
            key, data = await shared_object(conn, jc, kind, ref)
            if data is not None:
                objs.append({"key": key, "data": data, "mime": "application/json"})
        for t in SHARED_COUNTS:
            counts[t] = await conn.fetchval(f"SELECT COUNT(*) FROM {t}")

    manifest = {"formats": FORMAT, "organizacija": org, "izveidots": datetime.utcnow().isoformat() + "Z",
                "rindas": counts, "dokumenti": manifest_docs, "problemas": problems}
    objs.append({"key": "indekss.json", "data": _json(manifest), "mime": "application/json"})
    return objs, manifest


def _content_sha(o: dict) -> str:
    """SHA-256 used to decide 'unchanged'. The manifest is compared without its creation time."""
    if o["key"] == "indekss.json":
        return hashlib.sha256(_json({**json.loads(o["data"]), "izveidots": None})).hexdigest()
    return hashlib.sha256(o["data"]).hexdigest()


def _put_all(client, bucket: str, objs: list[dict], dry: bool) -> dict:
    written = skipped = 0
    errors = []
    for o in objs:
        sha, cmp = hashlib.sha256(o["data"]).hexdigest(), _content_sha(o)
        o["_written"] = False
        try:
            cur = client.head_object(Bucket=bucket, Key=o["key"]).get("Metadata", {})
            if cur.get("sha256-saturs", cur.get("sha256")) == cmp:
                skipped += 1
                continue
        except Exception:
            pass
        if dry:
            written += 1
            continue
        try:
            mime = o.get("mime") or mimetypes.guess_type(o["key"])[0] or "application/octet-stream"
            client.put_object(Bucket=bucket, Key=o["key"], Body=o["data"], ContentType=mime,
                              Metadata={"sha256": sha, "sha256-saturs": cmp})
            o["_written"] = True
            written += 1
        except Exception as e:
            errors.append(f"{o['key']}: {type(e).__name__}: {str(e)[:120]}")
    return {"rakstiti": written, "nemainiti": skipped, "kludas": errors}


def _prune(client, bucket: str, objs: list[dict], dry: bool) -> list[str]:
    """Objects under dokumenti/ that belong to no document any more (e.g. a folder renamed when
    the document got its LV-DOK identifier). Deleted with versioning on, so history stays."""
    want = {o["key"] for o in objs}
    stale = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix="dokumenti/"):
        stale += [o["Key"] for o in page.get("Contents", []) if o["Key"] not in want]
    if not dry:
        for k in stale:
            client.delete_object(Bucket=bucket, Key=k)
    return stale


def _verify(client, bucket: str, objs: list[dict]) -> dict:
    ok, bad = 0, []
    for o in objs:
        try:
            data = client.get_object(Bucket=bucket, Key=o["key"])["Body"].read()
            same = (hashlib.sha256(data).hexdigest() == hashlib.sha256(o["data"]).hexdigest()
                    if o["_written"] else _content_sha({"key": o["key"], "data": data}) == _content_sha(o))
            if same:
                ok += 1
            else:
                bad.append(o["key"])
        except Exception as e:
            bad.append(f"{o['key']} ({type(e).__name__})")
    return {"sakrit": ok, "nesakrit": bad}


async def run(dry_run: bool = True) -> dict:
    from opendms.storage import settings as sset
    cfg = await sset.s3_config(with_secret=True)
    if not (cfg.get("endpoint") and cfg.get("bucket") and cfg.get("accessKey") and cfg.get("secretKey")):
        raise ValueError("S3 savienojums nav iestatīts")
    t = time.perf_counter()
    objs, manifest = await collect()
    client = sset._client(cfg)
    put = await asyncio.to_thread(_put_all, client, cfg["bucket"], objs, dry_run)
    from opendms.config import get_settings
    copy_only = get_settings().storage_backend != "s3"     # never prune the active storage
    stale = await asyncio.to_thread(_prune, client, cfg["bucket"], objs, dry_run or not copy_only)
    ver = None if dry_run else await asyncio.to_thread(_verify, client, cfg["bucket"], objs)
    res = {"izmēģinājums": dry_run, "konteiners": cfg["bucket"], "dokumenti": len(manifest["dokumenti"]),
           "rindas": manifest["rindas"], "objekti": len(objs), "baiti": sum(len(o["data"]) for o in objs), **put,
           "parbaude": ver, "lieki": {"skaits": len(stale), "dzesti": not dry_run and copy_only, "piemeri": stale[:10]},
           "problemas": manifest["problemas"], "ilgums_s": round(time.perf_counter() - t, 1)}
    if not dry_run:
        await sset.ensure_schema()
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""INSERT INTO storage_settings (id, last_export) VALUES (1, $1)
                                  ON CONFLICT (id) DO UPDATE SET last_export = $1""", _json(res).decode())
    return res
