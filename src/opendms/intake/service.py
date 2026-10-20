"""Intake — every input channel ends here.

A channel (GUI upload, e-mail, web form) only transports. `ingest()` turns what
arrived into a DVS document the same way for all of them:

    item ─► eDoc containers unpacked (signed files + signature details)
         ─► document created (neutral title — the register receives the title
            at creation, so the sender's subject never leaves the DVS)
         ─► DVS-only metadata: sender, received-at, channel, subject, eDoc
         ─► files attached, the signed document first ─► 'document.received'
            ─► installed processes run (registration, classification, routing,
               semantic description, register submission)

The acknowledgement (registration number, LV-DOK identifier, register
tracking link) is sent by `process_acks()` once the registration process has
given the document its identifier and submitted it to the register.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import secrets
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Optional

from starlette.datastructures import Headers, UploadFile

from opendms.database import get_pool
from opendms.intake import config as cfg
from opendms.intake import edoc

logger = logging.getLogger(__name__)

SYSTEM_EMAIL = "ievade@opendms.local"
CHANNEL_CODE = {"epasts": "EPasts", "tiessaistes-forma": "Portals", "e-adrese": "EAdrese"}
TITLES = {"epasts": "Iesniegums (e-pasts)", "tiessaistes-forma": "Iesniegums (tiešsaistes forma)",
          "e-adrese": "Dokuments (e-adrese)"}
# Signed / main documents first — the primary file is what the processes read.
PRIMARY_RANK = {"application/pdf": 0,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": 1,
                "application/msword": 2, "application/vnd.oasis.opendocument.text": 2, "application/rtf": 2, "text/rtf": 2,
                "text/plain": 3}


async def system_user() -> dict:
    """The account inputs are recorded under. It cannot log in."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, email, role, full_name, department FROM users WHERE email = $1", SYSTEM_EMAIL)
        if not row:
            from opendms.middleware.auth import hash_password
            row = await conn.fetchrow(
                """INSERT INTO users (email, password_hash, full_name, role, is_active)
                   VALUES ($1, $2, 'Dokumentu ievade', 'operator', FALSE)
                   ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
                   RETURNING id, email, role, full_name, department""",
                SYSTEM_EMAIL, hash_password(secrets.token_urlsafe(32)))
    return dict(row)


def _upload(name: str, mime: str, data: bytes) -> UploadFile:
    return UploadFile(file=io.BytesIO(data), filename=name, size=len(data),
                      headers=Headers({"content-type": mime or "application/octet-stream"}))


def _safe_name(name: str) -> str:
    name = re.sub(r"[\\/\x00-\x1f]", "_", name or "").strip() or "datne"
    return name[:180]


def expand(attachments: list[dict], body: str = "") -> tuple[list[dict], list[dict]]:
    """Attachments -> ordered file list + eDoc summaries.

    eDoc: the signed data files go first (they are the document), the original
    container is kept after them (it is the legal record with the signatures).
    """
    signed, other, containers, edocs = [], [], [], []
    for a in attachments:
        data = a["data"]
        if edoc.is_edoc(a["file_name"], data):
            try:
                info = edoc.unpack(data, a["file_name"])
                edocs.append(edoc.summary(info))
                for f in info["datnes"]:
                    signed.append({**f, "avots": f"eDoc {a['file_name']}"})
            except edoc.EdocError as exc:
                edocs.append({"konteiners": a["file_name"], "kluda": str(exc)})
            containers.append({**a, "mime_type": edoc.ASIC_E_MIME})
        else:
            other.append(a)
    rank = lambda f: PRIMARY_RANK.get(f.get("mime_type") or "", 5)  # noqa: E731
    files = sorted(signed, key=rank) + sorted(other, key=rank) + containers
    text = (body or "").strip()
    if text and (not files or len(text) > 80):
        files.append({"file_name": "pavadteksts.txt", "mime_type": "text/plain",
                      "data": text.encode("utf-8"), "avots": "ziņas teksts"})
    return files, edocs


async def ingest(channel: dict, *, external_ref: str, sender: dict, subject: str, body: str,
                 attachments: list[dict], received_at: Optional[str] = None,
                 extra: Optional[dict] = None, primary: Optional[dict] = None,
                 register_did: Optional[str] = None, received_vc: bool = False,
                 doc_uid: Optional[str] = None) -> dict:
    """Register one received item as a DVS document. Idempotent per (channel, external_ref)."""
    from opendms.routers.documents import DocumentCreate, add_file, create_document

    kind = channel["veids"]
    cid = channel["id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        seen = await conn.fetchrow("SELECT id, document_id, status FROM intake_items WHERE channel_id = $1 AND external_ref = $2",
                                   cid, external_ref)
    if seen:
        return {"dublikats": True, "intakeId": seen["id"], "documentId": seen["document_id"], "status": seen["status"]}

    files, edocs = expand(attachments, body)
    if primary:  # a structured iesniegums: the XML is the document, everything else is evidence
        files.insert(0, primary)
    if not files:
        raise ValueError("nav ne pielikumu, ne teksta")
    user = await system_user()
    received_at = received_at or datetime.now(timezone.utc).isoformat()

    doc = await create_document(DocumentCreate(title=TITLES.get(kind, "Iesniegums"),
                                               metadata={"channel": CHANNEL_CODE.get(kind, "API")},
                                               register_did=register_did), user=user)
    doc_id = doc["id"]

    local_meta = {
        "channel": CHANNEL_CODE.get(kind, "API"),
        "receivedAt": received_at,
        "sender": {k: v for k, v in sender.items() if v},
        "ievade": {"kanals": cid, "veids": kind, "atsauce": external_ref, "temats": subject or None,
                   "datnes": [{"file_name": f["file_name"], "avots": f.get("avots")} for f in files],
                   **({"edoc": edocs} if edocs else {}), **(extra or {})},
    }
    title = (subject or "").strip()[:300] or TITLES.get(kind, "Iesniegums")
    async with pool.acquire() as conn:
        # Local only: the register received the neutral title at creation.
        await conn.execute("UPDATE documents SET title = $1, metadata = metadata || $2::jsonb WHERE id = $3",
                           title, json.dumps(local_meta, ensure_ascii=False), doc_id)
        if doc_uid:
            # A document received from another institution keeps its identifier.
            await conn.execute("""UPDATE documents SET doc_uid = $1 WHERE id = $2
                                  AND NOT EXISTS (SELECT 1 FROM documents WHERE doc_uid = $1)""", doc_uid, doc_id)
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, 'DocumentReceived', $2, $4, $3)""",
            doc_id, user["id"], json.dumps({"kanals": cid, "veids": kind, "datnes": len(files),
                                            "edoc": [{"paraksti": e.get("parakstuSkaits"), "integritate": e.get("integritateVisiem")} for e in edocs]},
                                           ensure_ascii=False), received_vc)
        intake_id = await conn.fetchval(
            """INSERT INTO intake_items (channel_id, channel_kind, external_ref, sender_address, subject,
                                         document_id, status, detail, ack_status)
               VALUES ($1,$2,$3,$4,$5,$6,'registrets',$7,$8) RETURNING id""",
            cid, kind, external_ref, sender.get("email"), subject, doc_id,
            json.dumps({"datnes": len(files), "edoc": len(edocs)}),
            "gaida" if sender.get("email") and _ack_enabled(channel) else None)

    # First attached file fires 'document.received' -> processes start.
    for f in files:
        await add_file(doc_id, _upload(_safe_name(f["file_name"]), f.get("mime_type"), f["data"]), user=user)

    logger.info("intake %s: %s -> document %s (%d files, %d eDoc)", cid, external_ref, doc_id, len(files), len(edocs))
    return {"intakeId": intake_id, "documentId": doc_id, "registrationNumber": doc["registration_number"],
            "datnes": len(files), "edoc": edocs}


async def record_rejected(channel: dict, external_ref: str, sender: str, subject: str, reason: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO intake_items (channel_id, channel_kind, external_ref, sender_address, subject, status, detail)
               VALUES ($1,$2,$3,$4,$5,'noraidits',$6) ON CONFLICT (channel_id, external_ref) DO NOTHING""",
            channel["id"], channel["veids"], external_ref, sender, subject, json.dumps({"iemesls": reason}, ensure_ascii=False))


def _ack_enabled(channel: dict) -> bool:
    if channel.get("veids") == "e-adrese":
        return False  # institution-to-institution: DIV confirmation is the acknowledgement
    a = channel.get("apstiprinajums") or {}
    if a.get("ieslegts", True) is False:
        return False
    # A web form has no mailbox of its own: it acknowledges through a named e-mail channel.
    return channel.get("veids") != "tiessaistes-forma" or bool(a.get("kanals"))


def tracking_code(doc_did: Optional[str]) -> Optional[str]:
    """Same as the register's: first 8 hex of sha256(did)."""
    return hashlib.sha256(doc_did.encode()).hexdigest()[:8] if doc_did else None


async def status(doc_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await conn.fetchrow(
            """SELECT d.registration_number, d.doc_uid, d.doc_did, d.metadata, d.created_at, o.name AS org_name
               FROM documents d LEFT JOIN organizations o ON o.id = d.org_id WHERE d.id = $1""", doc_id)
    if not d:
        return {}
    meta = d["metadata"]
    meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
    reg = cfg.register_public_url()
    code = tracking_code(d["doc_did"])
    return {
        "registracijasNr": d["registration_number"],
        "dokumentaId": d["doc_uid"],
        "iestade": d["org_name"],
        "registraDid": d["doc_did"],
        "izsekosanasKods": code,
        "izsekosanasSaite": f"{reg}/track/{code}" if reg and code else None,
        "nodotsRegistram": bool((meta.get("registraNodosana") or {}).get("nodots")),
        "edoc": (meta.get("ievade") or {}).get("edoc") or [],
        "izveidots": d["created_at"],
    }


def ack_text(st: dict, subject: str) -> tuple[str, str]:
    lines = [
        "Labdien!",
        "",
        f"Jūsu iesniegums ir saņemts un reģistrēts{(' — ' + st['iestade']) if st.get('iestade') else ''}.",
        "",
        f"Reģistrācijas numurs:     {st.get('registracijasNr') or '—'}",
        f"Dokumenta identifikators: {st.get('dokumentaId') or 'tiks piešķirts'}",
    ]
    if st.get("izsekosanasSaite"):
        lines += ["", "Iesnieguma virzību var sekot centrālajā dokumentu reģistrā:",
                  f"  {st['izsekosanasSaite']}",
                  f"  (izsekošanas kods {st['izsekosanasKods']}; meklēt var arī pēc dokumenta identifikatora)"]
    for e in st.get("edoc") or []:
        if e.get("kluda"):
            lines += ["", f"eDoc {e.get('konteiners')}: neizdevās atvērt ({e['kluda']}). Datne saglabāta kā saņemta."]
            continue
        names = ", ".join(p.get("parakstitajs") or "?" for p in e.get("paraksti") or []) or "nav parakstu"
        integ = "datnes atbilst parakstiem" if e.get("integritateVisiem") else "DATNES NEATBILST PARAKSTAM VAI NAV PĀRBAUDĀMAS"
        lines += ["", f"eDoc {e.get('konteiners')}: paraksti — {names}; {integ}.",
                  "Paraksta juridiskā derīguma pārbaude tiek veikta atsevišķi."]
    lines += ["", "Šī ir automātiska atbilde. Uz to nav jāatbild."]
    subj = f"Reģistrēts Nr. {st.get('registracijasNr')}" + (f": {subject}" if subject else "")
    return subj[:250], "\n".join(lines)


async def process_acks(channel: dict, send) -> int:
    """Send acknowledgements whose document is ready. `send(to, subject, body, in_reply_to)` is the channel's transport."""
    wait_s = int((channel.get("apstiprinajums") or {}).get("gaidit_s", 900))
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, document_id, sender_address, subject, external_ref, received_at
               FROM intake_items WHERE channel_id = $1 AND ack_status = 'gaida' ORDER BY id LIMIT 20""", channel["id"])
    sent = 0
    for r in rows:
        st = await status(r["document_id"])
        age = (datetime.now(timezone.utc) - r["received_at"]).total_seconds()
        ready = st.get("dokumentaId") and st.get("nodotsRegistram")
        if not ready and age < wait_s:
            continue
        subj, body = ack_text(st, r["subject"] or "")
        try:
            await send(r["sender_address"], subj, body, r["external_ref"] if r["external_ref"].startswith("<") else None)
            async with pool.acquire() as conn:
                await conn.execute("UPDATE intake_items SET ack_status = 'nosutits', ack_sent_at = NOW(), ack_error = NULL, detail = detail || $2::jsonb WHERE id = $1",
                                   r["id"], json.dumps({"apstiprinajums": {k: st.get(k) for k in ("registracijasNr", "dokumentaId", "izsekosanasKods", "nodotsRegistram")}}))
                await conn.execute(
                    """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
                       VALUES ($1, 'ReceiptAcknowledged', NULL, FALSE, $2)""",
                    r["document_id"], json.dumps({"kanals": channel["id"], "dokumentaId": st.get("dokumentaId"),
                                                  "pilns": bool(ready)}, ensure_ascii=False))
            sent += 1
        except Exception as exc:
            logger.warning("intake %s: ack for item %s failed: %s", channel["id"], r["id"], exc)
            async with pool.acquire() as conn:
                await conn.execute("UPDATE intake_items SET ack_error = $2 WHERE id = $1", r["id"], f"{type(exc).__name__}: {exc}"[:500])
    return sent


def parse_sender(raw_from: str) -> dict:
    name, addr = parseaddr(raw_from or "")
    return {"name": name or addr, "email": addr.lower() or None, "type": "FiziskaPersona"}
