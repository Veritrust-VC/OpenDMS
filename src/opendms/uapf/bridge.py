"""
Bridge — fires UAPF processes in response to OpenDMS document lifecycle events.

Public API:
  - on_document_event(event_type, doc_id) — call this from documents.py
    after a lifecycle transition succeeds. Looks up matching triggers and
    dispatches each to uapf-engine in the background.
"""

import asyncio
import json
import logging
from typing import Optional

from opendms.config import get_settings
from opendms.database import get_pool
from opendms.uapf.client import UapfClient
from opendms.uapf.manifest import build_host_manifest
from opendms.uapf.triggers import find_matching_triggers

logger = logging.getLogger(__name__)


async def on_document_event(event_type: str, doc_id: int) -> None:
    """
    Hook called after a document lifecycle transition succeeds.

    event_type: one of "document.created", "document.received", "document.assigned"
                 (mirrors the values stored in process_triggers.trigger_event)
    doc_id:     the affected document's primary key
    """
    s = get_settings()
    if not s.uapf_enabled:
        return

    pool = await get_pool()
    async with pool.acquire() as conn:
        doc_row = await conn.fetchrow(
            """SELECT id, doc_did, title, registration_number, status, org_id,
                      register_id, classification_id, metadata
                 FROM documents WHERE id = $1""",
            doc_id,
        )
    if not doc_row:
        logger.warning("on_document_event: document %s not found", doc_id)
        return

    document = dict(doc_row)
    if isinstance(document.get("metadata"), (str, bytes)):
        try:
            document["metadata"] = json.loads(document["metadata"])
        except Exception:
            document["metadata"] = {}

    triggers = await find_matching_triggers(event_type, document)
    if not triggers:
        return

    logger.info(
        "UAPF: %s on doc %s matched %d trigger(s): %s",
        event_type, doc_id, len(triggers),
        [t["name"] for t in triggers],
    )

    # Dispatch each matching trigger as a background task so the originating
    # HTTP request is not blocked on uapf-engine round-trips.
    for trigger in triggers:
        asyncio.create_task(_dispatch_trigger(trigger, document))


async def _dispatch_trigger(trigger: dict, document: dict) -> None:
    """Invoke uapf-engine for one trigger. Persists session record + errors."""
    s = get_settings()
    client = UapfClient(s.uapf_engine_url, s.uapf_engine_auth_token)

    input_payload = {
        "documentId": document["id"],
        "documentDid": document.get("doc_did"),
        "title": document.get("title"),
        "registrationNumber": document.get("registration_number"),
    }

    session_id = None
    state = "starting"
    output = None
    error = None

    try:
        result = await client.start_session(
            package_id=trigger["package_id"],
            process_id=trigger["process_id"],
            input_payload=input_payload,
            host_manifest=build_host_manifest(),
            package_version=trigger.get("package_version"),
        )
        session_id = result.get("sessionId")
        state = result.get("state", "unknown")
        output = result.get("output")
        logger.info(
            "UAPF session %s state=%s for trigger %s on doc %s",
            session_id, state, trigger["name"], document["id"],
        )
    except Exception as e:
        state = "failed"
        error = str(e)
        logger.exception(
            "UAPF start-session failed for trigger %s on doc %s",
            trigger["name"], document["id"],
        )

    # Persist whatever we know about the session
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO uapf_sessions
                 (session_id, document_id, trigger_id, package_id, process_id,
                  state, input_payload, output_payload, error_message,
                  completed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,
                       CASE WHEN $6 IN ('completed','failed','aborted') THEN NOW() ELSE NULL END)
               ON CONFLICT (session_id) DO UPDATE SET
                 state = EXCLUDED.state,
                 output_payload = EXCLUDED.output_payload,
                 error_message = EXCLUDED.error_message,
                 completed_at = CASE WHEN EXCLUDED.state IN ('completed','failed','aborted')
                                     THEN NOW() ELSE uapf_sessions.completed_at END""",
            session_id or f"sess_pending_{document['id']}",
            document["id"],
            trigger["id"],
            trigger["package_id"],
            trigger["process_id"],
            state,
            json.dumps(input_payload),
            json.dumps(output) if output is not None else None,
            error,
        )
