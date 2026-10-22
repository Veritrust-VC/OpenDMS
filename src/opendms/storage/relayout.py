"""Move existing data into the document-folder layout (storage/layout.py), on the active storage.

    org/<org>/<YYYY>/<MM>/<uid>/<file>   →  dokumenti/<mape>/datnes/<file>
    pakotnes/<mape>/…                    →  dokumenti/<mape>/…

Copies first and checks every copy against the recorded SHA-256, then repoints the
database (document_files.storage_key, documents.storage_key,
metadata.standartaPakotne.pakotnesAtslega). The old copies stay until the switch is
verified; `cleanup` lists them for removal later.

    python -m opendms.storage.relayout            # dry run
    python -m opendms.storage.relayout --run
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json

from opendms.storage import get_storage, layout

OLD_PACKAGE_ROOT = "pakotnes"


async def _walk(storage, prefix: str) -> list[str]:
    keys, stack = [], [prefix.rstrip("/")]
    while stack:
        p = stack.pop()
        lst = await storage.list(p)
        keys += [f"{p}/{f['name']}" for f in lst.get("files", [])]
        stack += [f"{p}/{d}" for d in lst.get("folders", [])]
    return keys


async def run(dry_run: bool = True) -> dict:
    from opendms.database import get_pool
    st = get_storage()
    pool = await get_pool()
    copied = repointed = pkgs = 0
    old_keys, problems = [], []
    async with pool.acquire() as conn:
        docs = await conn.fetch("SELECT id, doc_uid, storage_key, file_name, metadata FROM documents ORDER BY id")
        for d in docs:
            base = layout.prefix(d["id"], d["doc_uid"])
            meta = d["metadata"] if isinstance(d["metadata"], dict) else json.loads(d["metadata"] or "{}")
            pk = meta.get("standartaPakotne") or {}

            # 1. the package: pakotnes/<mape>/… → dokumenti/<mape>/…
            old_pk = pk.get("pakotnesAtslega") or ""
            if old_pk.startswith(OLD_PACKAGE_ROOT + "/"):
                if old_pk.split("/", 1)[1] != base.split("/", 1)[1]:
                    problems.append(f"dok. {d['id']}: pakotnes mape {old_pk} neatbilst {base}")
                    continue
                for k in await _walk(st, old_pk):
                    target = base + k[len(old_pk):]
                    data = await st.get(k)
                    if await st.exists(target):
                        if hashlib.sha256(await st.get(target)).digest() != hashlib.sha256(data).digest():
                            problems.append(f"dok. {d['id']}: {target} jau ir ar citu saturu")
                            continue
                    elif not dry_run:
                        await st.put(target, data)
                        if hashlib.sha256(await st.get(target)).digest() != hashlib.sha256(data).digest():
                            problems.append(f"dok. {d['id']}: {target} kopija neatbilst")
                            continue
                    copied += 1
                    old_keys.append(k)
                pkgs += 1
                if not dry_run:
                    await conn.execute(
                        """UPDATE documents SET metadata = jsonb_set(metadata, '{standartaPakotne,pakotnesAtslega}', to_jsonb($1::text))
                           WHERE id = $2""", base, d["id"])

            # 2. the files: org/… → dokumenti/<mape>/datnes/<file>
            files = await conn.fetch("SELECT id, file_name, storage_key, checksum_sha256 FROM document_files WHERE document_id = $1",
                                     d["id"])
            rows = [dict(f) for f in files]
            if d["storage_key"] and not any(f["storage_key"] == d["storage_key"] for f in rows):
                rows.append({"id": None, "file_name": d["file_name"], "storage_key": d["storage_key"], "checksum_sha256": None})
            for f in rows:
                if f["storage_key"].startswith(base + "/"):
                    continue
                target = f"{base}/datnes/{f['file_name']}"
                data = await st.get(f["storage_key"])
                if data is None:
                    problems.append(f"dok. {d['id']}: {f['storage_key']} nav nolasāms")
                    continue
                sha = hashlib.sha256(data).hexdigest()
                if f["checksum_sha256"] and sha != f["checksum_sha256"]:
                    problems.append(f"dok. {d['id']}: {f['file_name']} kontrolsumma neatbilst ierakstam")
                    continue
                if await st.exists(target):
                    if hashlib.sha256(await st.get(target)).hexdigest() != sha:
                        problems.append(f"dok. {d['id']}: {target} jau ir ar citu saturu")
                        continue
                elif not dry_run:
                    await st.put(target, data)
                    if hashlib.sha256(await st.get(target)).hexdigest() != sha:
                        problems.append(f"dok. {d['id']}: {target} kopija neatbilst")
                        continue
                    copied += 1
                else:
                    copied += 1
                old_keys.append(f["storage_key"])
                repointed += 1
                if not dry_run:
                    if f["id"]:
                        await conn.execute("UPDATE document_files SET storage_key = $1 WHERE id = $2", target, f["id"])
                    await conn.execute("UPDATE documents SET storage_key = $1 WHERE id = $2 AND storage_key = $3",
                                       target, d["id"], f["storage_key"])
    left = sorted(set(old_keys))
    return {"izmēģinājums": dry_run, "pakotnes": pkgs, "kopētas_datnes": copied, "pārvirzīti_ieraksti": repointed,
            "vecās_kopijas": len(left), "problemas": problems}


async def cleanup_candidates() -> list[str]:
    """Old-layout objects no record points to any more (for removal after the switch is verified)."""
    from opendms.database import get_pool
    st = get_storage()
    pool = await get_pool()
    async with pool.acquire() as conn:
        used = {r["k"] for r in await conn.fetch(
            "SELECT storage_key k FROM document_files UNION SELECT storage_key FROM documents WHERE storage_key IS NOT NULL")}
    keys = []
    for root in ("org", OLD_PACKAGE_ROOT):
        try:
            keys += await _walk(st, root)
        except Exception:
            pass
    return [k for k in keys if k not in used]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="store_true")

    async def _main(do_run: bool):
        from opendms.database import init_db
        await init_db()
        res = await run(dry_run=not do_run)
        res["vecās_kopijas_bez_ieraksta"] = len(await cleanup_candidates()) if do_run else None
        print(json.dumps(res, ensure_ascii=False, indent=1))
    asyncio.run(_main(ap.parse_args().run))
