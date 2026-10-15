"""Outgoing document (izejošais) — the reply as its own DVS document.

The reply draft is written on the incoming document (metadata.uapf_draft). For
approval, signing and sending it becomes a document of its own: a DVS record
with the draft as its file, linked both ways to the document it answers. The
process steps that act on it are UAPF capabilities (uapf/handlers.py):

  document.outgoing@1   create the outgoing document from the reply draft
  visa.record@1         the approver's vīza (Saskaņots / ar iebildumiem / Nesaskaņots)
  document.sign@1       DVS signature (MK 282 30. p.) by the person who decided
  document.sent@1       mark as sent (POC 1: no real dispatch)

The person who decided is the step's reviewer (e-mail). If that person has no
DVS account, the mark is recorded under the system account with their e-mail.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Optional

from opendms.database import get_pool

logger = logging.getLogger(__name__)

DRAFT_FILE = "atbildes-projekts.txt"
VISA_OF = {"saskanots": "Saskanots", "saskanots-ar-iebildumiem": "SaskanotsArIebildumiem",
           "nesaskanots": "Nesaskanots"}


def _j(v) -> dict:
    return json.loads(v) if isinstance(v, str) else (v or {})


async def person(email: Optional[str]) -> tuple[dict, Optional[str]]:
    """(DVS user, note): the DVS account of this e-mail, else the system account
    and a note naming the person."""
    from opendms.intake.service import system_user
    if email:
        pool = await get_pool()
        async with pool.acquire() as conn:
            u = await conn.fetchrow(
                "SELECT id, email, role, full_name FROM users WHERE lower(email) = lower($1) AND is_active", email)
        if u:
            return dict(u), None
    return await system_user(), (f"Lēmumu pieņēma {email} (Aģents)" if email else None)


async def _write_file(conn, doc_id: int, doc_uid: Optional[str], text: str, actor_id: int) -> None:
    """Put the draft text as the document's primary file (replacing the previous version)."""
    from opendms.config import get_settings
    from opendms.storage import get_storage, layout
    data = text.encode("utf-8")
    storage = get_storage()
    key, fname = await layout.file_key(storage, doc_id, doc_uid, DRAFT_FILE, data)
    await storage.put(key, data, "text/plain; charset=utf-8")
    checksum = hashlib.sha256(data).hexdigest()
    cur = await conn.fetchval("SELECT id FROM document_files WHERE document_id = $1 AND is_primary", doc_id)
    if cur:
        await conn.execute(
            """UPDATE document_files SET file_name = $2, file_size = $3, storage_key = $4, checksum_sha256 = $5
                WHERE id = $1""", cur, fname, len(data), key, checksum)
    else:
        await conn.execute(
            """INSERT INTO document_files (document_id, file_name, mime_type, file_size, storage_key,
                                           storage_backend, checksum_sha256, is_primary, uploaded_by)
               VALUES ($1,$2,'text/plain',$3,$4,$5,$6,TRUE,$7)""",
            doc_id, fname, len(data), key, get_settings().storage_backend, checksum, actor_id)


async def create_from_draft(incoming_id: int, session_id: Optional[str] = None) -> dict:
    """The outgoing document for the reply drafted on incoming_id (idempotent: one per incoming document)."""
    from opendms.intake.service import system_user
    from opendms.routers.documents import DocumentCreate, create_document
    pool = await get_pool()
    async with pool.acquire() as conn:
        src = await conn.fetchrow("SELECT id, title, registration_number, metadata FROM documents WHERE id = $1",
                                  incoming_id)
    if not src:
        raise LookupError(f"Document not found: {incoming_id}")
    meta = _j(src["metadata"])
    if meta.get("atbilde", {}).get("documentId"):
        return {"documentId": meta["atbilde"]["documentId"], "jauns": False}
    draft = meta.get("uapf_draft") or {}
    text = (draft.get("text") or "").strip()
    if not text:
        raise ValueError("Ienākošajam dokumentam nav atbildes projekta (uapf_draft)")

    user = await system_user()
    doc = await create_document(DocumentCreate(
        title=f"Atbilde: {src['title']}"[:300],
        metadata={"virziens": "izejosais",
                  "atbildeUz": {"documentId": src["id"], "registrationNumber": src["registration_number"]},
                  "uapf_draft": {**draft, "sessionId": session_id}}), user=user)
    out_id = doc["id"]
    async with pool.acquire() as conn:
        uid = await conn.fetchval("SELECT doc_uid FROM documents WHERE id = $1", out_id)
        await _write_file(conn, out_id, uid, text, user["id"])
        await conn.execute("UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
                           json.dumps({"atbilde": {"documentId": out_id,
                                                   "registrationNumber": doc.get("registration_number")}}),
                           src["id"])
        for d, other in ((src["id"], out_id), (out_id, src["id"])):
            await conn.execute(
                """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
                   VALUES ($1, 'IzejosaisIzveidots', $2, FALSE, $3)""",
                d, user["id"], json.dumps({"izejosais": out_id, "ienakosais": src["id"], "saistitais": other,
                                           "sessionId": session_id}))
    return {"documentId": out_id, "registrationNumber": doc.get("registration_number"), "jauns": True}


async def update_draft_text(doc_id: int, text: str, actor: dict) -> None:
    """A person edited the draft (step 'Labot projektu'): new text, new file version."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Projekta teksts nav norādīts")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT doc_uid, metadata FROM documents WHERE id = $1", doc_id)
        if not row:
            raise LookupError("Document not found")
        draft = _j(row["metadata"]).get("uapf_draft") or {}
        prev = draft.get("text") or ""
        if prev.strip() == text:
            return
        draft.update({"text": text, "labots": True})
        await conn.execute("UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
                           json.dumps({"uapf_draft": draft}), doc_id)
        u, note = await person(actor.get("email"))
        await _write_file(conn, doc_id, row["doc_uid"], text, u["id"])
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, 'ProjektsLabots', $2, FALSE, $3)""",
            doc_id, u["id"], json.dumps({"garums": len(text), "ieprieksGarums": len(prev), "piezime": note,
                                         "persona": actor.get("email")}))


async def visa(doc_id: int, decision: str, comment: Optional[str], email: Optional[str]) -> dict:
    from opendms.archive import marks as mk
    result = VISA_OF.get(decision)
    if not result:
        raise ValueError(f"Nav vīzas rezultāta lēmumam {decision}")
    u, note = await person(email)
    notes = " · ".join(x for x in ((comment or "").strip(), note) if x) or None
    return await mk.add_visa(doc_id, u["id"], result, notes)


async def sign(doc_id: int, comment: Optional[str], email: Optional[str]) -> dict:
    from opendms.archive import docmeta as dm
    from opendms.storage import get_storage
    u, note = await person(email)
    notes = " · ".join(x for x in ((comment or "").strip(), note) if x) or None
    r = await dm.sign(doc_id, u["id"], get_storage(), None, notes)
    try:
        from opendms.standard.service import refresh_package
        await refresh_package(doc_id)
    except Exception as exc:  # the standard package must not block the signature
        logger.warning("package refresh after signing %s: %s", doc_id, exc)
    return r


async def mark_sent(doc_id: int, email: Optional[str], comment: Optional[str]) -> None:
    u, note = await person(email)
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE documents SET status = 'sent', updated_at = NOW() WHERE id = $1", doc_id)
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, 'AtzimetsNosutits', $2, FALSE, $3)""",
            doc_id, u["id"], json.dumps({"piezimes": comment, "piezime": note, "persona": email,
                                         "nosutisana": "POC 1: atzīme bez nosūtīšanas"}))
