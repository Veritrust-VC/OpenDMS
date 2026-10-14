"""Rebuild the DVS database from its S3 container — proof that the DB is only an index.

Reads only the container (layout in export.py) and writes the knowledge tables of a
target database that already holds the configuration (schema, users, structure,
classifiers, settings). Then compares the target row by row with a reference database.

    python -m opendms.storage.rebuild --target <database name>   # rebuild + compare with live

The target must not be the live database; the command refuses that.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import time
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlparse, urlunparse

import asyncpg

from opendms.storage.export import KNOWLEDGE_TABLES

PREFIXES = {"ievade/": "intake_items", "zinasanas/precedenti/": "uapf_precedents",
            "lietas/": "standard_cases", "arhivs/partijas/": "archive_batches",
            "vesture/integracijas/": "integration_audit_log"}


def read_container(client, bucket: str) -> dict:
    """All knowledge rows by table, plus file checks, from the container alone."""
    keys = []
    for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
        keys += [o["Key"] for o in page.get("Contents", [])]
    get = lambda k: client.get_object(Bucket=bucket, Key=k)["Body"].read()  # noqa: E731
    tables: dict[str, list] = {t: [] for t in KNOWLEDGE_TABLES}
    files_ok, files_bad = 0, []
    keyset = set(keys)
    for k in sorted(keys):
        if k.startswith("dokumenti/") and k.endswith("/dvs-ieraksts.json"):
            rec = json.loads(get(k))
            base = k[: -len("dvs-ieraksts.json")]
            tables["documents"].append(rec["dokuments"])
            for t, rows in rec["tabulas"].items():
                tables[t] += rows
            for f in rec["tabulas"].get("document_files", []):
                fk = f"{base}datnes/{f['file_name']}"
                if fk not in keyset:
                    files_bad.append(f"{fk}: nav konteinerā")
                elif f.get("checksum_sha256") and hashlib.sha256(get(fk)).hexdigest() != f["checksum_sha256"]:
                    files_bad.append(f"{fk}: kontrolsumma neatbilst")
                else:
                    files_ok += 1
            continue
        for p, t in PREFIXES.items():
            if k.startswith(p) and k.endswith(".json"):
                obj = json.loads(get(k))
                if t == "integration_audit_log":
                    tables[t] += obj["rindas"]
                elif t == "archive_batches":
                    for d in obj.pop("dokumenti", []):
                        tables["archive_batch_documents"].append({"batch_id": obj["id"], "document_id": d})
                    tables[t].append(obj)
                else:
                    tables[t].append(obj)
    return {"tabulas": tables, "objekti": len(keys), "datnes_ok": files_ok, "datnes_kludas": files_bad}


async def _types(conn, table: str) -> dict[str, str]:
    rows = await conn.fetch("""SELECT column_name, data_type FROM information_schema.columns
                               WHERE table_schema = 'public' AND table_name = $1""", table)
    return {r["column_name"]: r["data_type"] for r in rows}


def _val(v, typ: str):
    if v is None:
        return None
    if typ in ("jsonb", "json"):
        return json.dumps(v, ensure_ascii=False)
    if typ.startswith("timestamp"):
        return datetime.fromisoformat(v)
    if typ == "date":
        return date.fromisoformat(v)
    if typ == "numeric":
        return Decimal(str(v))
    if typ == "bytea":
        return bytes.fromhex(v)
    return v


async def load(target_dsn: str, tables: dict[str, list]) -> dict:
    conn = await asyncpg.connect(target_dsn)
    counts = {}
    try:
        async with conn.transaction():
            await conn.execute("SET LOCAL session_replication_role = replica")   # order-independent load
            await conn.execute("TRUNCATE " + ", ".join(KNOWLEDGE_TABLES))
            for t in KNOWLEDGE_TABLES:
                rows = tables.get(t) or []
                counts[t] = len(rows)
                if not rows:
                    continue
                types = await _types(conn, t)
                cols = [c for c in rows[0] if c in types]
                await conn.executemany(
                    f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({', '.join(f'${i + 1}' for i in range(len(cols)))})",
                    [[_val(r.get(c), types[c]) for c in cols] for r in rows])
                if "id" in types:
                    await conn.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), GREATEST((SELECT MAX(id) FROM {t}), 1))")
    finally:
        await conn.close()
    return counts


async def fingerprint(dsn: str) -> dict[str, dict]:
    """Per table: row count and md5 over every column of every row."""
    conn = await asyncpg.connect(dsn)
    out = {}
    try:
        for t in KNOWLEDGE_TABLES:
            r = await conn.fetchrow(f"SELECT COUNT(*) n, md5(COALESCE(string_agg(x::text, E'\\n' ORDER BY x::text), '')) h FROM {t} x")
            out[t] = {"rindas": r["n"], "md5": r["h"]}
    finally:
        await conn.close()
    return out


async def diff_rows(dsn_a: str, dsn_b: str, table: str, limit: int = 5) -> list[str]:
    a, b = await asyncpg.connect(dsn_a), await asyncpg.connect(dsn_b)
    try:
        q = f"SELECT x::text t FROM {table} x"
        ra = {r["t"] for r in await a.fetch(q)}
        rb = {r["t"] for r in await b.fetch(q)}
    finally:
        await a.close()
        await b.close()
    return [f"tikai dzīvajā: {x[:300]}" for x in sorted(ra - rb)[:limit]] + \
           [f"tikai atjaunotajā: {x[:300]}" for x in sorted(rb - ra)[:limit]]


def _dsn_for(dsn: str, dbname: str) -> str:
    u = urlparse(dsn)
    return urlunparse(u._replace(path="/" + dbname))


async def run(target_db: str) -> dict:
    from opendms.config import get_settings
    from opendms.database import init_db
    from opendms.storage import settings as sset
    live = get_settings().database_url
    if urlparse(live).path.lstrip("/") == target_db:
        raise SystemExit("mērķis nedrīkst būt dzīvā datubāze")
    target = _dsn_for(live, target_db)
    await init_db()
    cfg = await sset.s3_config(with_secret=True)
    t0 = time.perf_counter()
    c = await asyncio.to_thread(read_container, sset._client(cfg), cfg["bucket"])
    loaded = await load(target, c["tabulas"])
    fa, fb = await fingerprint(live), await fingerprint(target)
    tabulas, diffs = {}, {}
    for t in KNOWLEDGE_TABLES:
        same = fa[t] == fb[t]
        tabulas[t] = {"dzivaja": fa[t]["rindas"], "atjaunota": fb[t]["rindas"], "sakrit": same}
        if not same:
            diffs[t] = await diff_rows(live, target, t)
    return {"konteiners": cfg["bucket"], "objekti": c["objekti"], "ielādēts": loaded,
            "datnes": {"ok": c["datnes_ok"], "kludas": c["datnes_kludas"]},
            "tabulas": tabulas, "atskirības": diffs,
            "viss_sakrit": not diffs and not c["datnes_kludas"],
            "ilgums_s": round(time.perf_counter() - t0, 1)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, help="database name to rebuild into (same server)")
    res = asyncio.run(run(ap.parse_args().target))
    print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
