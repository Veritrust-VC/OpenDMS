"""
process_triggers CRUD + matching.

A process_trigger declares "when X lifecycle event happens to a document, fire
UAPF process Y with package Z." Each event from documents.py against a
DocumentReceived/Created/etc. is matched against active triggers, and any that
fit are dispatched (in background) to uapf-engine.
"""

import json
import logging
from typing import Any, Optional

from opendms.database import get_pool

logger = logging.getLogger(__name__)


async def list_triggers(
    org_id: Optional[int] = None,
    only_active: bool = True,
) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if org_id is not None:
            rows = await conn.fetch(
                """SELECT * FROM process_triggers
                   WHERE ($1::bigint IS NULL OR org_id IS NULL OR org_id = $1)
                     AND (NOT $2 OR is_active = TRUE)
                   ORDER BY id""",
                org_id, only_active,
            )
        else:
            rows = await conn.fetch(
                "SELECT * FROM process_triggers WHERE (NOT $1 OR is_active = TRUE) ORDER BY id",
                only_active,
            )
    return [_decode(dict(r)) for r in rows]


async def find_matching_triggers(
    event_type: str,
    document: dict,
) -> list[dict]:
    """
    Find active triggers that match the given lifecycle event on the given document.

    Trigger matching:
      - trigger_event must equal event_type
      - org_id matches (or trigger is global)
      - match_condition (JSONB) — every key/value must match document field

    match_condition examples:
      {}                                          → match all
      {"register_code": "iesniegumi"}             → only docs in a specific register
      {"classification_code": "lv-tiesibsargs"}   → only docs with a specific classification
    """
    pool = await get_pool()
    org_id = document.get("org_id")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT t.*, r.code AS register_code, c.code AS classification_code
                 FROM process_triggers t
                 LEFT JOIN registers       r ON r.id = (
                   SELECT register_id FROM documents WHERE id = $3 LIMIT 1)
                 LEFT JOIN classifications c ON c.id = (
                   SELECT classification_id FROM documents WHERE id = $3 LIMIT 1)
                WHERE t.is_active = TRUE
                  AND t.trigger_event = $1
                  AND ($2::bigint IS NULL OR t.org_id IS NULL OR t.org_id = $2)
                ORDER BY t.id""",
            event_type, org_id, document.get("id"),
        )

    matched = []
    for r in rows:
        t = _decode(dict(r))
        conds = t.get("match_condition") or {}
        # Simple equality match against the document fields we joined in
        if all(
            t.get(k) == v if k in t else _check_doc_field(document, k, v)
            for k, v in conds.items()
        ):
            matched.append(t)
    return matched


def _check_doc_field(document: dict, key: str, expected: Any) -> bool:
    """Allow match_condition keys to reference document fields directly."""
    if key in document:
        return document[key] == expected
    # Allow nested-metadata matches like "metadata.foo"
    if "." in key and key.split(".", 1)[0] == "metadata":
        meta = document.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        return meta.get(key.split(".", 1)[1]) == expected
    return False


async def create_trigger(
    name: str,
    package_id: str,
    process_id: str,
    trigger_event: str,
    description: Optional[str] = None,
    package_version: Optional[str] = None,
    match_condition: Optional[dict] = None,
    org_id: Optional[int] = None,
    created_by: Optional[int] = None,
) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO process_triggers
                 (name, description, package_id, package_version, process_id,
                  trigger_event, match_condition, org_id, created_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               RETURNING *""",
            name, description, package_id, package_version, process_id,
            trigger_event, json.dumps(match_condition or {}), org_id, created_by,
        )
    return _decode(dict(row))


async def update_trigger(trigger_id: int, **fields) -> Optional[dict]:
    allowed = {
        "name", "description", "package_id", "package_version", "process_id",
        "trigger_event", "match_condition", "is_active",
    }
    sets = []
    vals = []
    idx = 1
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "match_condition":
            v = json.dumps(v or {})
        sets.append(f"{k} = ${idx}")
        vals.append(v)
        idx += 1
    if not sets:
        return None
    sets.append("updated_at = NOW()")
    vals.append(trigger_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE process_triggers SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
            *vals,
        )
    return _decode(dict(row)) if row else None


def _decode(record: dict) -> dict:
    for k in ("match_condition",):
        v = record.get(k)
        if isinstance(v, (str, bytes)):
            try:
                record[k] = json.loads(v)
            except Exception:
                pass
    return record
