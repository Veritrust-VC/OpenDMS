"""User tasks — UAPF process steps waiting for a person.

A BPMN userTask suspends the engine session and task.request writes the
waiting step on the document (documents.metadata.uapf_review, status
"gaida"). This module is the one place that reads those steps as a work list
("Mans darbs") and completes one with the person's decision, for the DVS
(routers/tasks.py), the Lietvedības aģents (mcp/lietveda.py) and the older
review endpoint (routers/uapf_admin.py).

POC 1: every signed-in user may act in every role, so the list is not
filtered by role or assignee; the step's role is shown so the person knows
in which capacity they act.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

from opendms.database import get_pool

logger = logging.getLogger(__name__)

# Decisions every step understands unless the process names its own (input "lemumi").
DEFAULT_DECISIONS = ("apstiprinats", "labots", "noraidits")
CORRECTION_KEYS = ("labotsKods", "labotaVieniba", "labojumaIemesls")
DECISION_LABELS = {"apstiprinats": "Apstiprināt", "labots": "Labot", "noraidits": "Noraidīt"}


class TaskError(Exception):
    """A task cannot be completed as asked; status is the HTTP status to answer with."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _j(v) -> dict:
    return json.loads(v) if isinstance(v, str) else (v or {})


def _parse_ts(v) -> Optional[datetime]:
    if not v:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        t = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def deadline_of(review: dict, classification_due: Optional[datetime] = None) -> Optional[datetime]:
    """When the step is due.

    In order: an explicit deadline on the step (termins as a date or a number of
    days, slaHours, responseDays — from the process), else the latest
    classification's SLA, else none.
    """
    p = review.get("proposal") or {}
    start = _parse_ts(review.get("requestedAt")) or datetime.now(timezone.utc)
    t = review.get("deadline") or p.get("termins")
    if t not in (None, ""):
        if isinstance(t, (int, float)) or re.fullmatch(r"\d{1,4}", str(t).strip()):
            return start + timedelta(days=int(t))
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(t).strip()):
            d = date.fromisoformat(str(t).strip())
            return datetime(d.year, d.month, d.day, 23, 59, tzinfo=timezone.utc)
        ts = _parse_ts(t)
        if ts:
            return ts
    for key, unit in (("slaHours", "hours"), ("responseDays", "days")):
        v = p.get(key)
        if v not in (None, "") and re.fullmatch(r"\d{1,5}", str(v).strip()):
            return start + timedelta(**{unit: int(v)})
    return classification_due


@lru_cache(maxsize=64)
def _steps(package_id: str, _stamp: float) -> dict[str, str]:
    from opendms.uapf.package_inspector import inspect_package
    info = inspect_package(package_id) or {}
    proc = info.get("process") or {}
    names = {s["id"]: s.get("name") or s["id"] for s in proc.get("steps") or []}
    names["__process__"] = proc.get("name") or ""
    return names


def step_names(package_id: Optional[str]) -> dict[str, str]:
    """Step id → name from the installed package's BPMN (empty if not installed)."""
    if not package_id:
        return {}
    try:
        from opendms.uapf.package_inspector import find_package_file
        path = find_package_file(package_id)
        if not path:
            return {}
        return _steps(package_id, path.stat().st_mtime)
    except Exception as exc:  # a missing or broken package must not hide the task
        logger.debug("step names for %s: %s", package_id, exc)
        return {}


_TASKS_SQL = """
SELECT d.id, d.registration_number, d.title, d.status, d.metadata, d.created_at, d.content_summary,
       s.package_id, s.process_id, s.state AS session_state,
       cc.due_at AS classification_due
  FROM documents d
  LEFT JOIN uapf_sessions s ON s.session_id = d.metadata->'uapf_review'->>'sessionId'
  LEFT JOIN LATERAL (
        SELECT created_at + make_interval(hours => sla_hours) AS due_at
          FROM complaint_classifications c
         WHERE c.document_id = d.id AND c.sla_hours IS NOT NULL
         ORDER BY c.created_at DESC, c.id DESC LIMIT 1) cc ON TRUE
 WHERE d.metadata->'uapf_review'->>'status' = 'gaida'
   {extra}
"""


def _shape(r, now: datetime) -> dict:
    meta = _j(r["metadata"])
    review = meta.get("uapf_review") or {}
    names = step_names(r["package_id"])
    due = deadline_of(review, r["classification_due"])
    decisions = list(review.get("decisions") or DEFAULT_DECISIONS)
    sender = (meta.get("sender") or meta.get("sutitajs") or meta.get("from")
              or (meta.get("incoming") or {}).get("sender"))
    if isinstance(sender, dict):
        sender = sender.get("name") or sender.get("nosaukums") or sender.get("email")
    return {
        "documentId": r["id"],
        "registrationNumber": r["registration_number"],
        "title": r["title"],
        "documentStatus": r["status"],
        "sender": sender,
        "sessionId": review.get("sessionId"),
        "stepId": review.get("stepId"),
        "stepName": names.get(review.get("stepId") or "", review.get("stepId")),
        "processId": r["process_id"],
        "processName": names.get("__process__") or r["process_id"],
        "packageId": r["package_id"],
        "role": review.get("role"),
        "department": review.get("department"),
        "proposal": review.get("proposal") or {},
        "decisions": [{"id": d, "label": DECISION_LABELS.get(d, d)} for d in decisions],
        "requestedAt": review.get("requestedAt"),
        "deadline": due.isoformat() if due else None,
        "overdue": bool(due and due < now),
        "sessionState": r["session_state"],
        "summary": r["content_summary"],
        # the reply draft the step asks the person to review (atbildes projekts)
        "draft": ({k: (meta.get("uapf_draft") or {}).get(k) for k in ("text", "missingElements", "templateId")}
                  if (meta.get("uapf_draft") or {}).get("text") else None),
    }


async def list_tasks(*, limit: int = 100, overdue_only: bool = False,
                     include_stale: bool = False) -> list[dict]:
    """Open user tasks, those with a deadline first (earliest first), then oldest first.

    A step whose engine session is no longer suspended (failed, completed by
    another path) is stale and left out unless include_stale.
    """
    extra = "" if include_stale else "AND (s.state IS NULL OR s.state = 'suspended')"
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(_TASKS_SQL.format(extra=extra))
    now = datetime.now(timezone.utc)
    out = [_shape(r, now) for r in rows]
    if overdue_only:
        out = [t for t in out if t["overdue"]]
    out.sort(key=lambda t: (t["deadline"] is None, t["deadline"] or "", t["requestedAt"] or ""))
    return out[: max(1, min(int(limit), 500))]


async def get_task(doc_id: int) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(_TASKS_SQL.format(extra="AND d.id = $1"), int(doc_id))
    return _shape(r, datetime.now(timezone.utc)) if r else None


async def complete(doc_id: int, decision: str, *, user: dict, comment: Optional[str] = None,
                   changes: Optional[dict] = None, via: str = "dvs",
                   on_behalf_of: Optional[str] = None) -> dict:
    """Complete the step waiting on this document with the person's decision.

    Resumes the engine session; the process continues from there. An approved
    proposal is a decision on the document, so processes waiting for
    'document.decided' start afterwards.
    """
    from opendms.config import get_settings
    from opendms.uapf.bridge import on_document_event
    from opendms.uapf.client import UapfClient

    pool = await get_pool()
    async with pool.acquire() as conn:
        meta = await conn.fetchval("SELECT metadata FROM documents WHERE id = $1", int(doc_id))
    if meta is None:
        raise TaskError(404, "Document not found")
    review = _j(meta).get("uapf_review") or {}
    if review.get("status") != "gaida" or not review.get("sessionId"):
        raise TaskError(409, "No process step is waiting for a decision on this document")
    allowed = tuple(review.get("decisions") or DEFAULT_DECISIONS)
    if decision not in allowed:
        raise TaskError(400, f"decision must be one of {', '.join(allowed)}")

    actor = user.get("email") or user.get("username") or str(user.get("id"))
    reviewer = on_behalf_of or actor
    changes = {k: str(v).strip() for k, v in (changes or {}).items()
               if k in CORRECTION_KEYS and v not in (None, "")}
    if decision == "labots" and not (changes.get("labotsKods") or changes.get("labotaVieniba")):
        raise TaskError(400, "A correction needs labotsKods or labotaVieniba")

    output = {"decision": decision, "comment": comment, "reviewer": reviewer, **changes}
    s = get_settings()
    client = UapfClient(s.uapf_engine_url, s.uapf_engine_auth_token)
    try:
        result = await client.resume_session(review["sessionId"], output)
    except Exception as e:
        raise TaskError(502, f"Engine resume failed: {e}")

    review.update({"status": decision, "decidedBy": reviewer, "comment": comment,
                   "decidedAt": datetime.now(timezone.utc).isoformat(), "via": via})
    if on_behalf_of:
        review["recordedBy"] = actor
    state = result.get("state", "unknown")
    async with pool.acquire() as conn:
        # While resuming, the process may already have asked for the next person
        # (a new task.request replaced uapf_review); that newer step must stay.
        await conn.execute(
            """UPDATE documents SET metadata = metadata || $1::jsonb
                WHERE id = $2 AND metadata->'uapf_review'->>'requestedAt' IS NOT DISTINCT FROM $3""",
            json.dumps({"uapf_review": review}), int(doc_id), review.get("requestedAt"))
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, 'uapf.review.decided', $2, FALSE, $3)""",
            int(doc_id), user.get("id"), json.dumps(review))
        await conn.execute(
            """UPDATE uapf_sessions SET state = $2,
                   output_payload = COALESCE($3::jsonb, output_payload),
                   completed_at = CASE WHEN $2 IN ('completed','failed','aborted') THEN NOW() ELSE completed_at END
               WHERE session_id = $1""",
            review["sessionId"], state,
            json.dumps(result.get("output")) if result.get("output") is not None else None)

    if decision in ("apstiprinats", "labots") and state == "completed":
        out = result.get("output") or {}
        dept = out.get("department") or out.get("strukturvieniba")
        if dept:
            try:
                from opendms.uapf.handlers import _register_assignment
                await _register_assignment(int(doc_id), {"department": dept, "vieniba": out.get("vieniba")},
                                           review["sessionId"])
            except Exception as exc:  # the register must not block the decision
                logger.warning("register assignment for doc %s failed: %s", doc_id, exc)
        async with pool.acquire() as conn:
            finished_pkg = await conn.fetchval(
                "SELECT package_id FROM uapf_sessions WHERE session_id = $1", review["sessionId"])
        await on_document_event("document.decided", int(doc_id), exclude_package=finished_pkg)

    nxt = await get_task(int(doc_id))   # the process may already wait for the next person
    return {"sessionId": review["sessionId"], "state": state, "review": review, "nextTask": nxt}
