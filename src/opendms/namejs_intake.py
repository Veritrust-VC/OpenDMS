"""Namejs intake — turns documents arriving in Namejs into OpenDMS documents.

The Namejs driver (connectors/namejs.py) only moves data. This module decides
what to do with it, and it does so through the same code paths a person uses:
the document is created by the documents router's create handler and its files
are added by the add-file handler. So an imported document gets its DID, its
register number, its lifecycle events and its UAPF triggers exactly like one
typed in by hand — there is no second, slightly different creation path.

FLOW. sync() polls the Namejs status feed. For each event:
  * a document not seen before is imported (card, then every file);
  * a document already imported gets its Namejs status recorded in metadata;
  * a deletion is recorded as namejs_deleted, the OpenDMS copy is kept.
The event is acknowledged in Namejs only when that step succeeded. A failure
leaves it in the feed, so the next poll retries it (at-least-once).

DEDUPLICATION. The Namejs document id is stored in documents.metadata as
namejs_document_id and checked before every import, so a repeated event, a
manual import and a background poll cannot create two copies.

SCHEDULING. The background loop wakes every few seconds, reads the enabled
Namejs connection, and runs sync() when its intake_poll_seconds interval has
elapsed. Blank or 0 switches intake off — the connection's own settings are the
switch, not an environment variable, so an operator controls it from the GUI.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import time
from typing import Any

from opendms.connectors import runtime
from opendms.connectors.base import Result
from opendms.database import get_pool

logger = logging.getLogger(__name__)

KIND = "namejs"
_LOCK = asyncio.Lock()
_subscribed = False
_last_run = 0.0


# ── settings read from the connection ────────────────────────────────────────

def _poll_seconds(config: dict) -> int:
    try:
        return max(0, int(str(config.get("intake_poll_seconds") or "0").strip() or 0))
    except ValueError:
        return 0


def _folder_filter(config: dict) -> set[int]:
    raw = str(config.get("intake_folder_ids") or "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x.isdigit()}


# ── seams: thin wrappers so the logic can be tested without a database ──────

async def _run(operation: str, inputs: dict, actor: dict | None) -> Result:
    return await runtime.run(KIND, operation, inputs, {"source": "namejs_intake"}, actor=actor)


async def _connection_config() -> dict | None:
    row = await runtime.load_connection(KIND)
    if row is None:
        return None
    cfg = row.get("config") or {}
    return json.loads(cfg) if isinstance(cfg, str) else dict(cfg)


async def _system_actor() -> dict | None:
    """The account imports are recorded under: the first active superadmin, else admin."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, email, role FROM users
               WHERE role IN ('superadmin','admin') AND COALESCE(is_active, TRUE)
               ORDER BY (role = 'superadmin') DESC, id LIMIT 1""")
    return dict(row) if row else None


async def _find_imported(namejs_id: int) -> dict | None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, registration_number FROM documents WHERE metadata->>'namejs_document_id' = $1",
            str(namejs_id))
    return dict(row) if row else None


async def _update_metadata(doc_id: int, patch: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb, updated_at = NOW() WHERE id = $1",
            doc_id, json.dumps(patch))


async def _create_document(title: str, summary: str | None, metadata: dict, actor: dict) -> dict:
    from opendms.routers.documents import DocumentCreate, create_document
    return await create_document(
        DocumentCreate(title=title, content_summary=summary, metadata=metadata), user=actor)


async def _add_file(doc_id: int, name: str, content: bytes, content_type: str, actor: dict) -> dict:
    from starlette.datastructures import Headers, UploadFile

    from opendms.routers.documents import add_file
    upload = UploadFile(file=io.BytesIO(content), filename=name,
                        headers=Headers({"content-type": content_type or "application/octet-stream"}))
    return await add_file(doc_id, file=upload, user=actor)


# ── import one document ──────────────────────────────────────────────────────

def _metadata_from(doc: dict) -> dict[str, Any]:
    return {
        "source": "namejs",
        "namejs_document_id": str(doc.get("id")),
        "namejs_registration_no": doc.get("registrationNo"),
        "namejs_registration_date": doc.get("registrationDate"),
        "namejs_status": doc.get("status"),
        "namejs_folder_id": doc.get("folderId"),
        "namejs_type_id": doc.get("typeId"),
        "namejs_correspondent_no": doc.get("correspondentNo"),
        "namejs_correspondent_date": doc.get("correspondentDate"),
    }


async def import_document(namejs_id: int, actor: dict | None = None,
                          folder_filter: set[int] | None = None) -> dict[str, Any]:
    """Import one Namejs document with its files. Idempotent."""
    existing = await _find_imported(namejs_id)
    if existing:
        return {"ok": True, "imported": False, "already_imported": True,
                "document_id": existing["id"], "namejs_document_id": namejs_id}

    actor = actor or await _system_actor()
    if actor is None:
        return {"ok": False, "reason": "no admin user to record the import under"}

    got = await _run("get_document", {"document_id": namejs_id}, actor)
    if not got.ok:
        return {"ok": False, "reason": got.reason, "namejs_document_id": namejs_id}
    doc = got.data["document"]
    if doc.get("isDeleted"):
        return {"ok": True, "imported": False, "skipped": "deleted in Namejs", "namejs_document_id": namejs_id}
    if folder_filter and doc.get("folderId") not in folder_filter:
        return {"ok": True, "imported": False, "skipped": f"folder {doc.get('folderId')} not in intake folders",
                "namejs_document_id": namejs_id}

    created = await _create_document(doc.get("name") or f"Namejs {namejs_id}",
                                     doc.get("description"), _metadata_from(doc), actor)
    doc_id = created["id"]

    files = await _run("list_files", {"document_id": namejs_id}, actor)
    attached, failed = [], []
    for f in (files.data.get("files") or []) if files.ok else []:
        dl = await _run("download_file", {"document_id": namejs_id, "file_id": f["id"]}, actor)
        if not dl.ok:
            failed.append({"name": f.get("name"), "reason": dl.reason})
            continue
        try:
            await _add_file(doc_id, f.get("name") or f"file-{f['id']}",
                            base64.b64decode(dl.data["content_b64"]),
                            dl.data.get("content_type", "application/octet-stream"), actor)
            attached.append(f.get("name"))
        except Exception as exc:  # storage or database failure; the card already exists
            logger.exception("namejs intake: attaching %s to document %s failed", f.get("name"), doc_id)
            failed.append({"name": f.get("name"), "reason": f"{type(exc).__name__}: {exc}"})
    if not files.ok:
        failed.append({"name": "*", "reason": files.reason})
    if failed:
        await _update_metadata(doc_id, {"namejs_file_errors": failed})

    logger.info("namejs intake: Namejs %s -> OpenDMS %s (%d files)", namejs_id, doc_id, len(attached))
    return {"ok": True, "imported": True, "document_id": doc_id,
            "registration_number": created.get("registration_number"),
            "namejs_document_id": namejs_id, "files": attached, "file_errors": failed}


# ── sync from the status feed ────────────────────────────────────────────────

async def sync(actor: dict | None = None, config: dict | None = None) -> dict[str, Any]:
    """Poll the Namejs status feed once and process every event."""
    global _subscribed
    async with _LOCK:
        if config is None:
            config = await _connection_config()
            if config is None:
                return {"ok": False, "reason": "no enabled Namejs connection is configured"}
        actor = actor or await _system_actor()
        if actor is None:
            return {"ok": False, "reason": "no admin user to record the import under"}

        if not _subscribed:
            sub = await _run("subscribe_status", {}, actor)
            if not sub.ok:
                return {"ok": False, "reason": f"subscribe failed: {sub.reason}"}
            _subscribed = True

        polled = await _run("poll_status", {"limit": 100}, actor)
        if not polled.ok:
            return {"ok": False, "reason": polled.reason}

        folders = _folder_filter(config)
        summary: dict[str, Any] = {"ok": True, "events": 0, "imported": [], "updated": 0,
                                   "skipped": 0, "failed": [], "acknowledged": 0}
        done: list[int] = []
        for ev in polled.data.get("events") or []:
            summary["events"] += 1
            nid = ev.get("documentId")
            try:
                existing = await _find_imported(nid)
                if existing:
                    patch = {"namejs_status": ev.get("status")}
                    if ev.get("isDeleted"):
                        patch["namejs_deleted"] = True
                    if ev.get("status") == "DST_REG_DONE":
                        got = await _run("get_document", {"document_id": nid}, actor)
                        if got.ok:
                            patch["namejs_registration_no"] = got.data["document"].get("registrationNo")
                    await _update_metadata(existing["id"], patch)
                    summary["updated"] += 1
                elif ev.get("isDeleted"):
                    summary["skipped"] += 1
                else:
                    r = await import_document(nid, actor, folders)
                    if not r.get("ok"):
                        summary["failed"].append({"namejs_document_id": nid, "reason": r.get("reason")})
                        continue
                    if r.get("imported"):
                        summary["imported"].append({"namejs_document_id": nid, "document_id": r["document_id"]})
                    else:
                        summary["skipped"] += 1
                done.append(ev["id"])
            except Exception as exc:
                logger.exception("namejs intake: event %s failed", ev.get("id"))
                summary["failed"].append({"namejs_document_id": nid, "reason": f"{type(exc).__name__}: {exc}"})

        if done:
            ack = await _run("ack_status", {"event_ids": done}, actor)
            if ack.ok:
                summary["acknowledged"] = len(done)
            else:
                summary["ack_error"] = ack.reason
        return summary


async def poll_forever(tick: float = 5.0) -> None:
    """Background loop: run sync() at the connection's intake_poll_seconds."""
    global _last_run
    while True:
        try:
            config = await _connection_config()
            interval = _poll_seconds(config or {})
            if interval and time.monotonic() - _last_run >= interval:
                _last_run = time.monotonic()
                result = await sync(config=config)
                if result.get("imported") or result.get("failed") or not result.get("ok"):
                    logger.info("namejs intake: %s", {k: v for k, v in result.items() if v})
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("namejs intake loop error")
        await asyncio.sleep(tick)
