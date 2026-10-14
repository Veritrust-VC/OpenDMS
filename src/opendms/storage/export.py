"""Copy this DVS into its S3 bucket — the bucket becomes the complete record.

Layout (one bucket per system):

    dokumenti/<mape>/                    <mape> = package folder (LV-DOK_…) or DVS-<id>
        metadati.xml, izsekosana.xml, SHA256SUMS, datnes/…   ← the standard package, as is
        datnes/…                         ← any document file not in a package yet
        dvs-ieraksts.json                ← the DVS record: document row (metadata incl.
                                           semantics, intake, forwarding, process results),
                                           files with ids and checksums, all events,
                                           process sessions, intake record
    ievade/<id>.json                     ← every intake item, also rejected ones
    zinasanas/precedenti/<id>.json       ← staff corrections the classifier learns from
    indekss.json                         ← manifest: documents, objects, sha256

Not copied: users, passwords, connector secrets, settings — configuration, not knowledge.

Each object carries x-amz-meta-sha256. A re-run skips objects whose content is
unchanged, so the bucket's version history only grows when something changed.
After writing, every object is read back and its SHA-256 compared.
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
from opendms.storage import get_storage

FORMAT = "opendms-bucket/1"


def _json(o: Any) -> bytes:
    def default(x):
        if isinstance(x, (datetime, date)):
            return x.isoformat()
        if isinstance(x, Decimal):
            return float(x)
        if isinstance(x, (bytes, bytearray)):
            return x.hex()
        return str(x)
    return json.dumps(o, ensure_ascii=False, indent=2, default=default).encode()


def _rows(rows) -> list[dict]:
    out = []
    for r in rows:
        d = dict(r)
        for k, v in d.items():
            if isinstance(v, str) and v[:1] in "{[":
                try:
                    d[k] = json.loads(v)
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
    """Everything to write: [{key, data, mime, src}] and the manifest."""
    st = get_storage()
    pool = await get_pool()
    async with pool.acquire() as conn:
        docs = _rows(await conn.fetch("SELECT * FROM documents ORDER BY id"))
        files = _rows(await conn.fetch("SELECT * FROM document_files ORDER BY document_id, created_at"))
        events = _rows(await conn.fetch("SELECT * FROM document_events ORDER BY document_id, id"))
        sessions = _rows(await conn.fetch("SELECT * FROM uapf_sessions ORDER BY id"))
        intake = _rows(await conn.fetch("SELECT * FROM intake_items ORDER BY id"))
        prec = _rows(await conn.fetch("SELECT * FROM uapf_precedents ORDER BY id"))
        org = dict(await conn.fetchrow("SELECT id, name, code, org_did, std_code FROM organizations WHERE is_default LIMIT 1") or {})

    by = lambda rows, k: {r[k]: [x for x in rows if x[k] == r[k]] for r in rows}  # noqa: E731
    f_by, e_by = by(files, "document_id") if files else {}, by(events, "document_id") if events else {}
    s_by = by([s for s in sessions if s.get("document_id")], "document_id") if sessions else {}
    i_by = by([i for i in intake if i.get("document_id")], "document_id") if intake else {}

    objs, manifest_docs, problems = [], [], []
    for d in docs:
        pk = (d.get("metadata") or {}).get("standartaPakotne") or {}
        folder = pk.get("pakotnesMape") or f"DVS-{d['id']}"
        base = f"dokumenti/{folder}"
        doc_objs = []
        in_pkg = set()
        if pk.get("pakotnesAtslega"):
            for k in await _walk(st, pk["pakotnesAtslega"]):
                rel = k[len(pk["pakotnesAtslega"]):].lstrip("/")
                data = await st.get(k)
                if data is None:
                    problems.append(f"{folder}: {rel} nav nolasāms")
                    continue
                doc_objs.append({"key": f"{base}/{rel}", "data": data, "src": k})
                if rel.startswith("datnes/"):
                    in_pkg.add(rel[len("datnes/"):])
        for f in f_by.get(d["id"], []):
            if f["file_name"] in in_pkg:
                continue
            data = await st.get(f["storage_key"]) if f.get("storage_key") else None
            if data is None:
                problems.append(f"{folder}: datne {f['file_name']} nav nolasāma")
                continue
            if f.get("checksum_sha256") and hashlib.sha256(data).hexdigest() != f["checksum_sha256"]:
                problems.append(f"{folder}: datne {f['file_name']} — kontrolsumma neatbilst DVS ierakstam")
            doc_objs.append({"key": f"{base}/datnes/{f['file_name']}", "data": data, "src": f["storage_key"]})
        record = {"formats": FORMAT, "dokuments": d, "datnes": f_by.get(d["id"], []),
                  "notikumi": e_by.get(d["id"], []), "procesi": s_by.get(d["id"], []),
                  "ievade": i_by.get(d["id"], [])}
        doc_objs.append({"key": f"{base}/dvs-ieraksts.json", "data": _json(record), "mime": "application/json"})
        objs += doc_objs
        manifest_docs.append({"mape": folder, "dvsId": d["id"], "registracijasNr": d.get("registration_number"),
                              "dokumentaId": d.get("doc_uid"), "registraDid": d.get("doc_did"),
                              "objekti": [{"key": o["key"][len(base) + 1:], "sha256": hashlib.sha256(o["data"]).hexdigest(),
                                           "baiti": len(o["data"])} for o in doc_objs]})
    for i in intake:
        objs.append({"key": f"ievade/{i['id']:06d}.json", "data": _json(i), "mime": "application/json"})
    for p in prec:
        objs.append({"key": f"zinasanas/precedenti/{p['id']:06d}.json", "data": _json(p), "mime": "application/json"})
    manifest = {"formats": FORMAT, "organizacija": org, "izveidots": datetime.utcnow().isoformat() + "Z",
                "dokumenti": manifest_docs, "ievade": len(intake), "precedenti": len(prec), "problemas": problems}
    objs.append({"key": "indekss.json", "data": _json(manifest), "mime": "application/json"})
    return objs, manifest


def _put_all(client, bucket: str, objs: list[dict], dry: bool) -> dict:
    written = skipped = 0
    errors = []
    for o in objs:
        sha = hashlib.sha256(o["data"]).hexdigest()
        try:
            cur = client.head_object(Bucket=bucket, Key=o["key"])
            if cur.get("Metadata", {}).get("sha256") == sha:
                skipped += 1
                continue
        except Exception:
            pass
        if dry:
            written += 1
            continue
        try:
            mime = o.get("mime") or mimetypes.guess_type(o["key"])[0] or "application/octet-stream"
            client.put_object(Bucket=bucket, Key=o["key"], Body=o["data"], ContentType=mime, Metadata={"sha256": sha})
            written += 1
        except Exception as e:
            errors.append(f"{o['key']}: {type(e).__name__}: {str(e)[:120]}")
    return {"rakstiti": written, "nemainiti": skipped, "kludas": errors}


def _verify(client, bucket: str, objs: list[dict]) -> dict:
    ok, bad = 0, []
    for o in objs:
        try:
            data = client.get_object(Bucket=bucket, Key=o["key"])["Body"].read()
            if hashlib.sha256(data).hexdigest() == hashlib.sha256(o["data"]).hexdigest():
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
    ver = None if dry_run else await asyncio.to_thread(_verify, client, cfg["bucket"], objs)
    res = {"izmēģinājums": dry_run, "spainis": cfg["bucket"], "dokumenti": len(manifest["dokumenti"]),
           "objekti": len(objs), "baiti": sum(len(o["data"]) for o in objs), **put,
           "parbaude": ver, "problemas": manifest["problemas"], "ilgums_s": round(time.perf_counter() - t, 1)}
    if not dry_run:
        await sset.ensure_schema()
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""INSERT INTO storage_settings (id, last_export) VALUES (1, $1)
                                  ON CONFLICT (id) DO UPDATE SET last_export = $1""", _json(res).decode())
    return res
