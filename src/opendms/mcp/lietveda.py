"""Lietvedība tools — what a records-management agent needs to work a DVS.

READ   worklist, document_history, people_and_categories, mans_darbs, uzdevums, dokumenta_priekslikums,
       meklet_dokumentus
WRITE  assign_document, apply_classification, add_note, pabeigt_uzdevumu, iesniegt_dokumentu
A2A    pienemt_dokumentu_a2a (write), dokumenta_statuss_a2a (read) — documents from other institutions'
       agents; the caller is filled in by the agent runtime from the peer's token, never by the model

Every write runs as the authenticated DVS user (for the Lietvedības aģents:
its own named user, see config.mcp_agent_*), lands in document_events with a
reason, and goes through the same code paths as the GUI — assigning uses the
GUI's lifecycle transition, so the register gets the same lifecycle event.

Process steps (UAPF user tasks) are completed only with pabeigt_uzdevumu, which
records the person who confirmed the decision in the Agent; the agent itself
never decides. Deliberately absent: the document lifecycle actions decide,
send, archive and delete — they belong to the processes, not to the agent.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from opendms.database import get_pool

CLOSED = ("decided", "sent", "archived")


def _j(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


def _schema(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": required or [], "additionalProperties": False}


TOOLS: list[dict[str, Any]] = [
    {
        "name": "worklist",
        "class": "read",
        "description": "Open documents (not yet decided, sent or archived) with their current "
                       "classification, assignee and deadline. Deadline = when the latest "
                       "classification was made + its SLA hours. Use for 'what is overdue', "
                       "'what is due this week', 'what is unassigned', 'what does X have'.",
        "inputSchema": _schema({
            "status": {"type": "string", "description": "Optional status: registered, received, assigned."},
            "assigned_user_id": {"type": "integer", "description": "Only documents assigned to this user."},
            "unassigned_only": {"type": "boolean", "default": False},
            "overdue_only": {"type": "boolean", "default": False},
            "due_within_days": {"type": "integer", "minimum": 0, "maximum": 90,
                                "description": "Only documents whose deadline is within this many days (or past)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        }),
    },
    {
        "name": "document_history",
        "class": "read",
        "description": "Everything about one document: registry record, assignee, files, every "
                       "event in its history (who, when, what), every classification made, the "
                       "process review status and the public tracking code in the central register.",
        "inputSchema": _schema({"document_id": {"type": "integer"}}, ["document_id"]),
    },
    {
        "name": "people_and_categories",
        "class": "read",
        "description": "Who documents can be assigned to (active users with id, name, role, "
                       "department), the departments, and the topics and priorities already used "
                       "in classifications. Call before assign_document or apply_classification.",
        "inputSchema": _schema({}),
    },
    {
        "name": "assign_document",
        "class": "write",
        "description": "Assign a document to a person (and optionally a department). Recorded in "
                       "the document history and as a lifecycle event in the central register. "
                       "Not possible for decided, sent or archived documents. Always give a reason.",
        "inputSchema": _schema({
            "document_id": {"type": "integer"},
            "user_id": {"type": "integer", "description": "From people_and_categories."},
            "department": {"type": "string"},
            "reason": {"type": "string", "description": "Why this person — recorded with the event."},
        }, ["document_id", "user_id", "reason"]),
    },
    {
        "name": "apply_classification",
        "class": "write",
        "description": "Record a classification for a document (topic, priority, department, SLA "
                       "hours) — e.g. confirming or correcting what the process proposed. It becomes "
                       "the document's current classification; earlier ones stay in history. "
                       "Always give a reason.",
        "inputSchema": _schema({
            "document_id": {"type": "integer"},
            "topic": {"type": "string"},
            "priority": {"type": "string"},
            "department": {"type": "string"},
            "sla_hours": {"type": "integer", "minimum": 1, "maximum": 8760},
            "reason": {"type": "string"},
        }, ["document_id", "topic", "priority", "reason"]),
    },
    {
        "name": "add_note",
        "class": "write",
        "description": "Add a note to a document's history (visible to staff in the DVS). For "
                       "observations, follow-ups and summaries — not for decisions.",
        "inputSchema": _schema({
            "document_id": {"type": "integer"},
            "text": {"type": "string", "maxLength": 4000},
        }, ["document_id", "text"]),
    },
    {
        "name": "mans_darbs",
        "class": "read",
        "description": "Mans darbs: process steps waiting for a person (UAPF user tasks), earliest "
                       "deadline first. Each item: document id and number, title, sender, process and "
                       "step name, role, the AI proposal for the step, the decisions the person can "
                       "take, deadline and whether it is overdue. Use for 'what do I have to do', "
                       "'what is overdue'.",
        "inputSchema": _schema({
            "overdue_only": {"type": "boolean", "default": False},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 25},
        }),
    },
    {
        "name": "uzdevums",
        "class": "read",
        "description": "The process step waiting on one document: step, role, AI proposal, decisions "
                       "allowed, deadline. Read before pabeigt_uzdevumu.",
        "inputSchema": _schema({"document_id": {"type": "integer"}}, ["document_id"]),
    },
    {
        "name": "meklet_dokumentus",
        "class": "read",
        "description": "Dokumenti: find documents by number, subject, sender or meaning. mode 'teksts' = the words as "
                       "typed (all must match); mode 'nozime' = the question is expanded into related terms (synonyms, "
                       "legal terms, topics) and results are ranked by how many match. Returns number, title, status, "
                       "direction, sender, topic, department and the open process step, if any.",
        "inputSchema": _schema({
            "query": {"type": "string"},
            "mode": {"type": "string", "enum": ["teksts", "nozime"], "default": "teksts"},
            "status": {"type": "string", "description": "Optional: draft, registered, assigned, decided, sent, archived."},
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 30},
        }, ["query"]),
    },
    {
        "name": "dokumenta_priekslikums",
        "class": "read",
        "description": "Jauns dokuments, 1. solis: from a file (base64) or pasted text, propose the registration "
                       "metadata (temats, sūtītāja organizācija, dokumenta datums, veids, kopsavilkums). Stores nothing. "
                       "Personal data is redacted before the model, so the sender's name comes from the person.",
        "inputSchema": _schema({
            "file_name": {"type": "string"}, "mime_type": {"type": "string"},
            "file_b64": {"type": "string", "description": "File content, base64 (max 15 MB)."},
            "text": {"type": "string", "maxLength": 50000},
        }),
    },
    {
        "name": "iesniegt_dokumentu",
        "class": "write",
        "description": "Jauns dokuments, 2. solis: register the document with the values the person confirmed; the "
                       "organisation's processes start (registration, classification, routing). Only after the person "
                       "has seen and confirmed the values.",
        "inputSchema": _schema({
            "fields": {"type": "object", "description": "temats (required), sutitajs, sutitajaOrganizacija, "
                       "sutitajaEpasts, dokumentaDatums, dokumentaVeids, kopsavilkums"},
            "file_name": {"type": "string"}, "mime_type": {"type": "string"},
            "file_b64": {"type": "string"}, "text": {"type": "string", "maxLength": 50000},
            "person": {"type": "string", "description": "E-mail of the person who entered the document."},
            "confirmed": {"type": "boolean"},
        }, ["fields", "person", "confirmed"]),
    },
    {
        "name": "pienemt_dokumentu_a2a",
        "class": "write",
        "description": "A2A: pieņem dokumentu, ko nosūtījis citas iestādes MI aģents (piem. iesniegumu, kas pārsūtīts "
                       "pēc piekritības), un reģistrē to kā saņemtu dokumentu; iestādes procesi to virza kā jebkuru "
                       "saņemtu dokumentu, lēmumu pieņem cilvēks. Atgriež reģistrācijas numuru. a2a_zvanitajs un "
                       "a2a_uzdevums aizpilda aģenta vide, nevis valodas modelis.",
        "inputSchema": _schema({
            "a2a_zvanitajs": {"type": "string", "description": "Sūtītāja aģents (aizpilda aģenta vide)."},
            "a2a_uzdevums": {"type": "string", "description": "A2A uzdevuma identifikators (aizpilda aģenta vide)."},
            "fields": {"type": "object", "description": "temats (required), sutitajaOrganizacija, dokumentaDatums, "
                       "dokumentaVeids, kopsavilkums, sutitajaAtsauce (sūtītāja dokumenta numurs)"},
            "file_name": {"type": "string"}, "mime_type": {"type": "string"},
            "file_b64": {"type": "string", "description": "Datne base64 (pievieno aģenta vide no A2A ziņojuma)."},
            "text": {"type": "string", "maxLength": 50000, "description": "Dokumenta teksts, ja datnes nav."},
        }, ["a2a_zvanitajs", "a2a_uzdevums", "fields"]),
    },
    {
        "name": "dokumenta_statuss_a2a",
        "class": "read",
        "description": "A2A: parāda citas iestādes aģenta iepriekš nosūtīta dokumenta stāvokli pēc reģistrācijas "
                       "numura — tikai dokumentiem, ko nosūtījis tas pats aģents.",
        "inputSchema": _schema({
            "a2a_zvanitajs": {"type": "string", "description": "Sūtītāja aģents (aizpilda aģenta vide)."},
            "registracijas_numurs": {"type": "string"},
        }, ["a2a_zvanitajs", "registracijas_numurs"]),
    },
    {
        "name": "pabeigt_uzdevumu",
        "class": "write",
        "description": "Complete the process step waiting on a document with the person's decision; "
                       "the process continues (it may route, hand over or ask the next person). Only "
                       "after the person has seen the document, the step and the decision and has "
                       "confirmed it. decision must be one of the step's decisions (uzdevums). A "
                       "correction (labots) needs labotsKods or labotaVieniba in changes.",
        "inputSchema": _schema({
            "document_id": {"type": "integer"},
            "decision": {"type": "string"},
            "comment": {"type": "string", "maxLength": 4000},
            "changes": {"type": "object", "description": "labotsKods, labotaVieniba, labojumaIemesls (correction); "
                        "projektaTeksts (the draft, where the step allows editing it); rezolucija {izpilditajaId, "
                        "termins YYYY-MM-DD, teksts} (where the step asks for a resolution; people from people_and_categories)"},
            "person": {"type": "string", "description": "E-mail of the person who confirmed the decision."},
            "confirmed": {"type": "boolean", "description": "True only when the person confirmed this exact decision."},
        }, ["document_id", "decision", "person", "confirmed"]),
    },
]


# ── read ──────────────────────────────────────────────────────

_LATEST_CLASS = """
    LEFT JOIN LATERAL (
        SELECT topic, priority, department, sla_hours, created_at,
               created_at + make_interval(hours => COALESCE(sla_hours, 0)) AS due_at
          FROM complaint_classifications c WHERE c.document_id = d.id
         ORDER BY c.created_at DESC, c.id DESC LIMIT 1) cc ON TRUE"""


async def _worklist(args: dict, ctx: dict) -> dict:
    where, params = [f"d.status NOT IN {CLOSED!r}"], []
    if args.get("status"):
        params.append(args["status"]); where.append(f"d.status = ${len(params)}")
    if args.get("assigned_user_id"):
        params.append(int(args["assigned_user_id"])); where.append(f"d.assigned_to = ${len(params)}")
    if args.get("unassigned_only"):
        where.append("d.assigned_to IS NULL")
    if args.get("overdue_only"):
        where.append("cc.sla_hours IS NOT NULL AND cc.due_at < NOW()")
    if args.get("due_within_days") is not None:
        params.append(int(args["due_within_days"]))
        where.append(f"cc.sla_hours IS NOT NULL AND cc.due_at < NOW() + make_interval(days => ${len(params)})")
    params.append(min(int(args.get("limit") or 25), 100))
    sql = f"""
        SELECT d.id, d.registration_number, d.title, d.status, d.created_at,
               u.id AS assignee_id, u.full_name AS assignee,
               cc.topic, cc.priority, cc.department, cc.sla_hours, cc.due_at,
               CASE WHEN cc.sla_hours IS NULL THEN NULL
                    ELSE round(extract(epoch FROM cc.due_at - NOW()) / 86400.0, 1) END AS days_left
          FROM documents d
          LEFT JOIN users u ON u.id = d.assigned_to
          {_LATEST_CLASS}
         WHERE {' AND '.join(where)}
         ORDER BY cc.due_at ASC NULLS LAST, d.id DESC
         LIMIT ${len(params)}"""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
    return {"count": len(rows), "documents": [dict(r) for r in rows],
            "note": "days_left < 0 means overdue; null means no SLA recorded."}


async def _document_history(args: dict, ctx: dict) -> dict:
    doc_id = int(args["document_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await conn.fetchrow(
            """SELECT d.id, d.registration_number, d.title, d.status, d.doc_did, d.doc_uid,
                      d.content_summary, d.metadata, d.created_at, d.updated_at,
                      u.id AS assignee_id, u.full_name AS assignee, u.department AS assignee_department
                 FROM documents d LEFT JOIN users u ON u.id = d.assigned_to WHERE d.id = $1""", doc_id)
        if d is None:
            return {"error": "document not found", "document_id": doc_id}
        files = await conn.fetch(
            "SELECT file_name, mime_type, file_size, created_at FROM document_files WHERE document_id = $1 ORDER BY id",
            doc_id)
        events = await conn.fetch(
            """SELECT e.event_type, e.created_at, e.vc_submitted, e.details,
                      u.full_name AS actor, u.email AS actor_email
                 FROM document_events e LEFT JOIN users u ON u.id = e.actor_id
                WHERE e.document_id = $1 ORDER BY e.created_at, e.id""", doc_id)
        classes = await conn.fetch(
            """SELECT topic, topic_confidence, priority, department, sla_hours, reviewer_role,
                      raw_facets, created_at
                 FROM complaint_classifications WHERE document_id = $1
                ORDER BY created_at DESC, id DESC""", doc_id)
    meta = _j(d["metadata"])
    review = meta.get("uapf_review") or {}
    try:
        from opendms.intake.service import tracking_code
        code = tracking_code(d["doc_did"])
    except Exception:
        code = None
    out = {k: d[k] for k in ("id", "registration_number", "title", "status", "doc_did", "doc_uid",
                             "content_summary", "created_at", "updated_at",
                             "assignee_id", "assignee", "assignee_department")}
    out.update({
        "intake": meta.get("ievade"),
        "process_review": {k: review.get(k) for k in ("status", "decidedBy", "decidedAt", "note") if review.get(k)},
        "draft_reply_available": bool(meta.get("uapf_draft")),
        "register_tracking_code": code,
        "files": [dict(f) for f in files],
        "events": [{**dict(e), "details": _j(e["details"])} for e in events],
        "classifications": [{**dict(c), "raw_facets": _j(c["raw_facets"])} for c in classes],
    })
    return out


async def _people_and_categories(args: dict, ctx: dict) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        users = await conn.fetch(
            """SELECT id, full_name, email, role, department FROM users
                WHERE is_active AND role <> 'viewer' ORDER BY full_name""")
        topics = await conn.fetch(
            "SELECT topic, count(*) n FROM complaint_classifications GROUP BY topic ORDER BY n DESC LIMIT 60")
        prios = await conn.fetch(
            "SELECT priority, count(*) n FROM complaint_classifications GROUP BY priority ORDER BY n DESC")
        depts = await conn.fetch(
            """SELECT DISTINCT department FROM (
                   SELECT department FROM users WHERE department IS NOT NULL
                   UNION SELECT department FROM complaint_classifications WHERE department IS NOT NULL) x
               ORDER BY department""")
    me = (ctx.get("user") or {}).get("id")
    return {
        "people": [dict(u) | {"is_this_agent": u["id"] == me} for u in users],
        "departments": [r["department"] for r in depts],
        "topics_in_use": [r["topic"] for r in topics],
        "priorities_in_use": [r["priority"] for r in prios],
    }


# ── write ─────────────────────────────────────────────────────

async def _open_doc(conn, doc_id: int) -> tuple[Optional[dict], Optional[dict]]:
    d = await conn.fetchrow("SELECT id, status, title FROM documents WHERE id = $1", doc_id)
    if d is None:
        return None, {"error": "document not found", "document_id": doc_id}
    if d["status"] in CLOSED:
        return None, {"error": f"document is '{d['status']}' — closed documents are changed only by a person in the DVS",
                      "document_id": doc_id}
    return dict(d), None


def _actor(ctx: dict) -> dict:
    u = ctx.get("user") or {}
    if not u.get("id"):
        raise PermissionError("write tools need an authenticated DVS user")
    return u


async def _assign_document(args: dict, ctx: dict) -> dict:
    from opendms import sdk_client
    from opendms.routers.documents import _transition

    actor = _actor(ctx)
    doc_id, user_id = int(args["document_id"]), int(args["user_id"])
    pool = await get_pool()
    async with pool.acquire() as conn:
        _, err = await _open_doc(conn, doc_id)
        if err:
            return err
        assignee = await conn.fetchrow(
            "SELECT id, full_name, department, is_active FROM users WHERE id = $1", user_id)
    if not assignee or not assignee["is_active"]:
        return {"error": "assignee not found or inactive", "user_id": user_id}
    dept = args.get("department") or assignee["department"] or ""
    res = await _transition(
        doc_id, "DocumentAssigned", "assigned", actor,
        sdk_client.assign_document, {"assignee": assignee["full_name"], "department": dept},
        {"user_id": user_id, "assignee": assignee["full_name"], "department": dept,
         "assigned_to": user_id, "via": "mcp", "reason": args["reason"]},
        action_name="opendms.doc.assign")
    return {"done": True, "document_id": doc_id, "assignee": assignee["full_name"], "department": dept,
            "status": res.get("status"), "register_event_recorded": res.get("vc_submitted")}


async def _apply_classification(args: dict, ctx: dict) -> dict:
    actor = _actor(ctx)
    doc_id = int(args["document_id"])
    facets = {"source": "mcp", "by": actor.get("email"), "reason": args["reason"]}
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            _, err = await _open_doc(conn, doc_id)
            if err:
                return err
            row = await conn.fetchrow(
                """INSERT INTO complaint_classifications
                       (document_id, topic, topic_confidence, priority, sla_hours, department, raw_facets)
                   VALUES ($1, $2, NULL, $3, $4, $5, $6) RETURNING id, created_at""",
                doc_id, args["topic"].strip(), args["priority"].strip(),
                int(args["sla_hours"]) if args.get("sla_hours") else None,
                (args.get("department") or "").strip() or None, json.dumps(facets, ensure_ascii=False))
            await conn.execute(
                """INSERT INTO document_events (document_id, event_type, actor_id, details)
                   VALUES ($1, 'ClassificationApplied', $2, $3)""",
                doc_id, actor["id"], json.dumps({
                    "topic": args["topic"], "priority": args["priority"], "department": args.get("department"),
                    "sla_hours": args.get("sla_hours"), "via": "mcp", "reason": args["reason"]},
                    ensure_ascii=False))
    return {"done": True, "document_id": doc_id, "classification_id": row["id"],
            "recorded_at": row["created_at"]}


async def _add_note(args: dict, ctx: dict) -> dict:
    actor = _actor(ctx)
    doc_id = int(args["document_id"])
    text = (args.get("text") or "").strip()
    if not text:
        return {"error": "empty note"}
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await conn.fetchrow("SELECT id FROM documents WHERE id = $1", doc_id)
        if d is None:
            return {"error": "document not found", "document_id": doc_id}
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, details)
               VALUES ($1, 'NoteAdded', $2, $3)""",
            doc_id, actor["id"], json.dumps({"text": text[:4000], "via": "mcp"}, ensure_ascii=False))
    return {"done": True, "document_id": doc_id}


async def _mans_darbs(args: dict, ctx: dict) -> dict:
    from opendms import tasks
    items = await tasks.list_tasks(limit=int(args.get("limit") or 25),
                                   overdue_only=bool(args.get("overdue_only")))
    return {"count": len(items), "overdue": sum(1 for t in items if t["overdue"]), "items": items}


async def _uzdevums(args: dict, ctx: dict) -> dict:
    from opendms import tasks
    t = await tasks.get_task(int(args["document_id"]))
    return t or {"error": "no process step is waiting on this document", "document_id": args["document_id"]}


async def _pabeigt_uzdevumu(args: dict, ctx: dict) -> dict:
    from opendms import tasks
    actor = _actor(ctx)
    if args.get("confirmed") is not True:
        return {"error": "the person has not confirmed this decision — show the document, step and "
                         "decision and ask first"}
    person = (args.get("person") or "").strip().lower()
    if "@" not in person:
        return {"error": "person must be the e-mail of the person who confirmed"}
    try:
        res = await tasks.complete(int(args["document_id"]), str(args["decision"]), user=actor,
                                   comment=args.get("comment"), changes=args.get("changes"),
                                   via="agent", on_behalf_of=person)
    except tasks.TaskError as e:
        return {"error": e.message, "document_id": args["document_id"]}
    nxt = res.get("nextTask")
    return {"done": True, "document_id": int(args["document_id"]), "decision": args["decision"],
            "process_state": res["state"],
            "next_step": ({"stepName": nxt["stepName"], "role": nxt["role"]} if nxt else None)}


async def _meklet_dokumentus(args: dict, ctx: dict) -> dict:
    from opendms import search
    return await search.search(str(args.get("query") or ""), mode=args.get("mode") or "teksts",
                               limit=int(args.get("limit") or 30), status=args.get("status"))


async def _dokumenta_priekslikums(args: dict, ctx: dict) -> dict:
    from opendms.intake import agent_channel
    try:
        return await agent_channel.propose(file_name=args.get("file_name"), mime_type=args.get("mime_type"),
                                           file_b64=args.get("file_b64"), text=args.get("text"))
    except ValueError as e:
        return {"error": str(e)}


async def _iesniegt_dokumentu(args: dict, ctx: dict) -> dict:
    from opendms.intake import agent_channel
    _actor(ctx)
    if args.get("confirmed") is not True:
        return {"error": "the person has not confirmed the values — show them and ask first"}
    person = (args.get("person") or "").strip().lower()
    if "@" not in person:
        return {"error": "person must be the e-mail of the person entering the document"}
    try:
        r = await agent_channel.submit(fields=args.get("fields") or {}, person=person,
                                       file_name=args.get("file_name"), mime_type=args.get("mime_type"),
                                       file_b64=args.get("file_b64"), text=args.get("text"))
    except ValueError as e:
        return {"error": str(e)}
    return {"done": True, **r}


async def _pienemt_dokumentu_a2a(args: dict, ctx: dict) -> dict:
    from opendms.intake import a2a_channel
    _actor(ctx)   # the organisation's own agent, with its own DVS user
    try:
        return await a2a_channel.receive(args)
    except ValueError as e:
        return {"error": str(e)}


async def _dokumenta_statuss_a2a(args: dict, ctx: dict) -> dict:
    from opendms.intake import a2a_channel
    try:
        return await a2a_channel.status_for(args)
    except ValueError as e:
        return {"error": str(e)}


HANDLERS = {
    "worklist": _worklist,
    "document_history": _document_history,
    "people_and_categories": _people_and_categories,
    "assign_document": _assign_document,
    "apply_classification": _apply_classification,
    "add_note": _add_note,
    "mans_darbs": _mans_darbs,
    "uzdevums": _uzdevums,
    "pabeigt_uzdevumu": _pabeigt_uzdevumu,
    "dokumenta_priekslikums": _dokumenta_priekslikums,
    "meklet_dokumentus": _meklet_dokumentus,
    "iesniegt_dokumentu": _iesniegt_dokumentu,
    "pienemt_dokumentu_a2a": _pienemt_dokumentu_a2a,
    "dokumenta_statuss_a2a": _dokumenta_statuss_a2a,
}
