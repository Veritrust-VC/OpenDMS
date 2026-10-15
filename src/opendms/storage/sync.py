"""Keep the knowledge in storage current — each document's dvs-ieraksts.json and the shared objects.

Database triggers on every knowledge table note what changed (storage_dirty: kind + ref).
A background worker drains those notes every few seconds and rewrites only the affected
objects in the ACTIVE storage (disk or S3), using the same builders as the export, so a
record written here is byte-identical to one written by the export.

    kind      ref        object
    doc       doc id     dokumenti/<mape>/dvs-ieraksts.json
    ievade    id         ievade/<id>.json
    precedents id        zinasanas/precedenti/<id>.json
    lieta     id         lietas/<id>.json
    arhivs    id         arhivs/partijas/<id>.json
    integracijas YYYYMM  vesture/integracijas/<YYYY-MM>.json
    agents    run id     agenti/<id>.json

storage_records remembers what was written (key, sha256), so an unchanged object is not
written again and a record that moved (DVS-<id> → LV-DOK folder) leaves no copy behind.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Optional

from opendms.database import get_pool
from opendms.storage import export, get_storage, layout

logger = logging.getLogger(__name__)

INTERVAL_S = 5
_state = {"last_run": None, "last_error": None, "written": 0, "deleted": 0}

DOC_CHILDREN = ("document_files", "document_events", "uapf_sessions", "complaint_classifications", "ai_processing_log")
TRIGGERED = ("documents",) + DOC_CHILDREN + ("agent_runs", "agent_steps", "agent_messages", "intake_items",
                                             "uapf_precedents", "standard_cases", "archive_batches",
                                             "archive_batch_documents", "integration_audit_log",
                                             "case_volumes", "classification_schemes", "scheme_entries", "archive_settings")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS storage_dirty (
    id BIGSERIAL PRIMARY KEY, kind TEXT NOT NULL, ref BIGINT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW());
CREATE TABLE IF NOT EXISTS storage_records (
    kind TEXT NOT NULL, ref BIGINT NOT NULL, key TEXT NOT NULL, sha256 TEXT NOT NULL,
    synced_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (kind, ref));

CREATE OR REPLACE FUNCTION storage_mark_row(t TEXT, j JSONB) RETURNS VOID AS $$
DECLARE d BIGINT;
BEGIN
    IF t = 'documents' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('doc', (j->>'id')::bigint);
    ELSIF t IN ('document_files', 'document_events', 'uapf_sessions', 'complaint_classifications', 'ai_processing_log') THEN
        IF j->>'document_id' IS NOT NULL THEN
            INSERT INTO storage_dirty (kind, ref) VALUES ('doc', (j->>'document_id')::bigint);
        END IF;
    ELSIF t = 'agent_runs' THEN
        IF j->>'document_id' IS NULL THEN
            INSERT INTO storage_dirty (kind, ref) VALUES ('agents', (j->>'id')::bigint);
        ELSE
            INSERT INTO storage_dirty (kind, ref) VALUES ('doc', (j->>'document_id')::bigint);
        END IF;
    ELSIF t IN ('agent_steps', 'agent_messages') THEN
        SELECT document_id INTO d FROM agent_runs WHERE id = (j->>'run_id')::bigint;
        IF d IS NULL THEN
            INSERT INTO storage_dirty (kind, ref) VALUES ('agents', (j->>'run_id')::bigint);
        ELSE
            INSERT INTO storage_dirty (kind, ref) VALUES ('doc', d);
        END IF;
    ELSIF t = 'intake_items' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('ievade', (j->>'id')::bigint);
    ELSIF t = 'uapf_precedents' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('precedents', (j->>'id')::bigint);
    ELSIF t = 'standard_cases' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('lieta', (j->>'id')::bigint);
    ELSIF t = 'case_volumes' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('lieta', (j->>'case_id')::bigint);
    ELSIF t = 'classification_schemes' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('shema', (j->>'id')::bigint);
    ELSIF t = 'scheme_entries' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('shema', (j->>'scheme_id')::bigint);
    ELSIF t = 'archive_settings' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('iestatijumi', (j->>'org_id')::bigint);
    ELSIF t = 'archive_batches' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('arhivs', (j->>'id')::bigint);
    ELSIF t = 'archive_batch_documents' THEN
        INSERT INTO storage_dirty (kind, ref) VALUES ('arhivs', (j->>'batch_id')::bigint);
    ELSIF t = 'integration_audit_log' AND j->>'created_at' IS NOT NULL THEN
        INSERT INTO storage_dirty (kind, ref)
        VALUES ('integracijas', to_char(((j->>'created_at')::timestamptz) AT TIME ZONE 'UTC', 'YYYYMM')::bigint);
    END IF;
END $$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION storage_mark() RETURNS TRIGGER AS $$
BEGIN
    -- never let bookkeeping break the business write: on any error only warn
    BEGIN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN PERFORM storage_mark_row(TG_TABLE_NAME, to_jsonb(OLD)); END IF;
        IF TG_OP IN ('INSERT', 'UPDATE') THEN PERFORM storage_mark_row(TG_TABLE_NAME, to_jsonb(NEW)); END IF;
    EXCEPTION WHEN OTHERS THEN
        RAISE WARNING 'storage_mark %: %', TG_TABLE_NAME, SQLERRM;
    END;
    RETURN NULL;
END $$ LANGUAGE plpgsql;
"""


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(_SCHEMA)
        for t in TRIGGERED:
            await conn.execute(f"DROP TRIGGER IF EXISTS storage_mark ON {t}")
            await conn.execute(f"""CREATE TRIGGER storage_mark AFTER INSERT OR UPDATE OR DELETE ON {t}
                                   FOR EACH ROW EXECUTE FUNCTION storage_mark()""")


async def mark_all() -> int:
    """Queue every document and shared object (first run, or after a restore)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        refs = [("doc", r["id"]) for r in await conn.fetch("SELECT id FROM documents")] + await export.shared_refs(conn)
        await conn.executemany("INSERT INTO storage_dirty (kind, ref) VALUES ($1, $2)", refs)
    return len(refs)


async def _build(conn, jc, kind: str, ref: int) -> tuple[Optional[str], Optional[bytes]]:
    if kind == "doc":
        rec = await export.doc_record(conn, jc, ref)
        if rec is None:
            return None, None
        folder, d, tabulas = rec
        return f"{layout.ROOT}/{folder}/dvs-ieraksts.json", export.record_bytes(d, tabulas)
    return await export.shared_object(conn, jc, kind, ref)


async def drain(limit: int = 500) -> dict:
    """Write what changed. One transaction: if a write fails, the notes stay and are retried."""
    st = get_storage()
    pool = await get_pool()
    written = deleted = skipped = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            notes = await conn.fetch("SELECT id, kind, ref FROM storage_dirty ORDER BY id LIMIT $1 FOR UPDATE SKIP LOCKED", limit)
            if not notes:
                return {"atzimes": 0, "rakstiti": 0, "dzesti": 0, "nemainiti": 0}
            jc = await export._jsonb_cols(conn)
            for kind, ref in dict.fromkeys((n["kind"], n["ref"]) for n in notes):
                prev = await conn.fetchrow("SELECT key, sha256 FROM storage_records WHERE kind = $1 AND ref = $2", kind, ref)
                key, data = await _build(conn, jc, kind, ref)
                if data is None:                                     # source gone → object gone
                    for k in {key, prev["key"] if prev else None} - {None}:
                        await st.delete(k)
                    await conn.execute("DELETE FROM storage_records WHERE kind = $1 AND ref = $2", kind, ref)
                    deleted += 1
                    continue
                sha = hashlib.sha256(data).hexdigest()
                if prev and prev["key"] == key and prev["sha256"] == sha:
                    skipped += 1
                    continue
                await st.put(key, data, "application/json")
                if prev and prev["key"] != key:                      # e.g. DVS-<id> → LV-DOK folder
                    await st.delete(prev["key"])
                await conn.execute(
                    """INSERT INTO storage_records (kind, ref, key, sha256, synced_at) VALUES ($1, $2, $3, $4, NOW())
                       ON CONFLICT (kind, ref) DO UPDATE SET key = $3, sha256 = $4, synced_at = NOW()""",
                    kind, ref, key, sha)
                written += 1
            await conn.execute("DELETE FROM storage_dirty WHERE id = ANY($1::bigint[])", [n["id"] for n in notes])
    _state["written"] += written
    _state["deleted"] += deleted
    return {"atzimes": len(notes), "rakstiti": written, "dzesti": deleted, "nemainiti": skipped}


async def status() -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rec = await conn.fetchrow("SELECT COUNT(*) n, MAX(synced_at) last FROM storage_records")
        pending = await conn.fetchval("SELECT COUNT(DISTINCT (kind, ref)) FROM storage_dirty")
    return {"ieraksti": rec["n"], "pedejaSinhronizacija": rec["last"].isoformat() if rec["last"] else None,
            "gaida": pending, "pedejaKluda": _state["last_error"]}


async def run_forever() -> None:
    try:
        await ensure_schema()
        pool = await get_pool()
        async with pool.acquire() as conn:
            first = not await conn.fetchval("SELECT EXISTS (SELECT 1 FROM storage_records)")
        if first:
            logger.info("storage sync: first run, queued %d objects", await mark_all())
    except Exception:
        logger.exception("storage sync: setup failed")
        return
    while True:
        try:
            while (await drain())["atzimes"]:
                pass
            _state["last_error"] = None
        except asyncio.CancelledError:
            raise
        except Exception as e:
            _state["last_error"] = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(e).__name__}: {str(e)[:200]}"
            logger.exception("storage sync failed")
        _state["last_run"] = time.time()
        await asyncio.sleep(INTERVAL_S)

