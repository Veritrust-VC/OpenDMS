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
from typing import Any

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

# Knowledge not tied to one document: (table, key prefix, object naming)
SHARED = [
    ("intake_items", "ievade", "id"),
    ("uapf_precedents", "zinasanas/precedenti", "id"),
    ("standard_cases", "lietas", "id"),
    ("archive_batches", "arhivs/partijas", "id"),          # + archive_batch_documents inside
    ("integration_audit_log", "vesture/integracijas", "month"),
]

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


async def collect() -> tuple[list[dict], dict]:
    """Everything to write: [{key, data, mime}] and the manifest."""
    st = get_storage()
    pool = await get_pool()
    objs, manifest_docs, problems, counts = [], [], [], {}
    async with pool.acquire() as conn:
        jc = await _jsonb_cols(conn)
        docs = _rows(await conn.fetch("SELECT * FROM documents ORDER BY id"), jc.get("documents", set()))
        org = dict(await conn.fetchrow("SELECT id, name, code, org_did, std_code FROM organizations WHERE is_default LIMIT 1") or {})
        counts["documents"] = len(docs)

        for d in docs:
            tabulas = {}
            for t, where in DOC_TABLES:
                tabulas[t] = _rows(await conn.fetch(f"SELECT * FROM {t} WHERE {where} ORDER BY id", d["id"]),
                                   jc.get(t, set()))
                counts[t] = counts.get(t, 0) + len(tabulas[t])
            pk = (d.get("metadata") or {}).get("standartaPakotne") or {}
            folder = layout.folder(d["id"], d.get("doc_uid"))
            base = f"dokumenti/{folder}"
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
            record = {"formats": FORMAT, "dokuments": d, "tabulas": tabulas}
            doc_objs.append({"key": f"{base}/dvs-ieraksts.json", "data": _json(record), "mime": "application/json"})
            objs += doc_objs
            manifest_docs.append({"mape": folder, "dvsId": d["id"], "registracijasNr": d.get("registration_number"),
                                  "dokumentaId": d.get("doc_uid"), "registraDid": d.get("doc_did"),
                                  "objekti": [{"key": o["key"][len(base) + 1:], "sha256": hashlib.sha256(o["data"]).hexdigest(),
                                               "baiti": len(o["data"])} for o in doc_objs]})

        for t, prefix, naming in SHARED:
            rows = _rows(await conn.fetch(f"SELECT * FROM {t} ORDER BY id"), jc.get(t, set()))
            counts[t] = len(rows)
            if t == "archive_batches":
                links = await conn.fetch("SELECT batch_id, document_id FROM archive_batch_documents ORDER BY batch_id, document_id")
                counts["archive_batch_documents"] = len(links)
                for r in rows:
                    r["dokumenti"] = [ln["document_id"] for ln in links if ln["batch_id"] == r["id"]]
            if naming == "month":
                by: dict[str, list] = {}
                for r in rows:
                    by.setdefault(r["created_at"].strftime("%Y-%m"), []).append(r)
                for m, rs in by.items():
                    objs.append({"key": f"{prefix}/{m}.json", "data": _json({"formats": FORMAT, "tabula": t, "rindas": rs}),
                                 "mime": "application/json"})
            else:
                for r in rows:
                    objs.append({"key": f"{prefix}/{r['id']:06d}.json", "data": _json(r), "mime": "application/json"})

        # agent conversations without a document: run + steps + messages in one object
        runs = _rows(await conn.fetch("SELECT * FROM agent_runs WHERE document_id IS NULL ORDER BY id"), jc.get("agent_runs", set()))
        for r in runs:
            steps = _rows(await conn.fetch("SELECT * FROM agent_steps WHERE run_id = $1 ORDER BY id", r["id"]), jc.get("agent_steps", set()))
            msgs = _rows(await conn.fetch("SELECT * FROM agent_messages WHERE run_id = $1 ORDER BY id", r["id"]), jc.get("agent_messages", set()))
            for t, n in (("agent_runs", 1), ("agent_steps", len(steps)), ("agent_messages", len(msgs))):
                counts[t] = counts.get(t, 0) + n
            objs.append({"key": f"agenti/{r['id']:06d}.json", "mime": "application/json",
                         "data": _json({"formats": FORMAT, "tabulas": {"agent_runs": [r], "agent_steps": steps, "agent_messages": msgs}})})

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
