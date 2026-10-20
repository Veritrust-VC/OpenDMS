"""A2A — a document handed over by another institution's MI agent.

The organisation's own agent receives an A2A task from a peer agent (for
example a document forwarded by competence) and passes it here through the
pienemt_dokumentu_a2a MCP tool. The document goes in through the same intake
path as every other channel (ingest), so registration, classification and
routing run exactly as for e-mail or e-adrese; people decide about it.

Who sent it is not the language model's word: the agent runtime fills
a2a_zvanitajs from the bearer token the peer presented, and a2a_uzdevums from
the A2A task. A task delivered twice is one document (external_ref per task).
A peer sees the status only of documents it sent itself.

Central register: when the peer sends the document's identity (register DID,
document ID) and the sender's organisation DID matches the one recorded for its
token (a2a_zvanitaja_did, filled by the runtime), this DVS records
DocumentReceived on the SAME register document and keeps its identifier — one
document, one timeline across institutions; the content travelled directly.

Channel code DVSIntegracija (standard: dokumenta-metadati-v2.xsd) — another
institution's system delivering into this DVS.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

CHANNEL = {"id": "a2a", "veids": "a2a", "nosaukums": "Citas iestādes MI aģents (A2A)",
           # the A2A answer (registration number) is the acknowledgement
           "apstiprinajums": {"ieslegts": False}}
MAX_BYTES = 15 * 1024 * 1024
STATUS_LV = {"draft": "sagatave", "registered": "reģistrēts", "assigned": "nodots izpildei",
             "decided": "lēmums pieņemts", "sent": "atbilde nosūtīta", "received": "saņemts", "archived": "arhivēts"}


def _decode(file_b64: Optional[str]) -> bytes:
    if not file_b64:
        return b""
    try:
        data = base64.b64decode(re.sub(r"\s+", "", file_b64), validate=True)
    except Exception:
        raise ValueError("datne nav derīgā base64")
    if len(data) > MAX_BYTES:
        raise ValueError("datne pārsniedz 15 MB")
    return data


def _caller(args: dict) -> tuple[str, str]:
    caller = str(args.get("a2a_zvanitajs") or "").strip()
    task = str(args.get("a2a_uzdevums") or "").strip()
    if not caller or not task:
        raise ValueError("šo rīku izsauc tikai A2A uzdevumā (zvanītāju un uzdevumu norāda aģenta vide)")
    return caller, task


async def receive(args: dict) -> dict:
    from opendms.intake.service import ingest, status
    caller, task = _caller(args)
    fields = args.get("fields") or {}
    temats = str(fields.get("temats") or "").strip()
    if not temats:
        raise ValueError("norādiet dokumenta tematu")
    data = _decode(args.get("file_b64"))
    text = str(args.get("text") or "").strip()
    if not data and not text:
        raise ValueError("pievienojiet datni vai dokumenta tekstu")

    org = str(fields.get("sutitajaOrganizacija") or "").strip() or None
    reg = await _register_received(args, task)
    sender = {"name": caller, "organization": org}
    atts = [{"file_name": args.get("file_name") or "dokuments",
             "mime_type": args.get("mime_type") or "application/octet-stream", "data": data}] if data else []
    ident = args.get("a2a_identitate") or {}
    if not fields.get("sutitajaAtsauce") and reg.get("pienemts") and ident.get("SutitajaRegNr"):
        fields = {**fields, "sutitajaAtsauce": ident["SutitajaRegNr"]}
    extra = {"a2a": {"zvanitajs": caller, "uzdevums": task, "iestade": org,
                     "zvanitajaDid": args.get("a2a_zvanitaja_did") or None},
             "centralaisRegistrs": {k: v for k, v in reg.items() if k != "pienemts"},
             "ievadesVeids": "Citas iestādes MI aģents (A2A)",
             **{k: fields.get(k) for k in ("dokumentaDatums", "dokumentaVeids", "kopsavilkums", "sutitajaAtsauce")
                if fields.get(k) not in (None, "")}}
    r = await ingest(CHANNEL, external_ref=f"a2a-{task}", sender=sender, subject=temats,
                     body=text, attachments=atts, extra=extra,
                     register_did=reg.get("registraDid") if reg.get("pienemts") else None,
                     received_vc=bool(reg.get("pienemts")),
                     doc_uid=ident.get("DokumentaID") if reg.get("pienemts") else None)
    doc_id = r["documentId"]
    if fields.get("kopsavilkums") and not r.get("dublikats"):
        from opendms.database import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE documents SET content_summary = COALESCE(content_summary, $1) WHERE id = $2",
                               str(fields["kopsavilkums"])[:2000], doc_id)
    st = await status(doc_id) if doc_id else {}
    logger.info("a2a intake from %s (task %s) -> document %s%s", caller, task, doc_id,
                " (already received)" if r.get("dublikats") else "")
    return {"sanemts": True, "jauASanemts": bool(r.get("dublikats")),
            "registracijasNr": st.get("registracijasNr") or r.get("registrationNumber"),
            "izsekosanasKods": st.get("izsekosanasKods"), "izsekosanasSaite": st.get("izsekosanasSaite"),
            "centralaisRegistrs": "tas pats dokuments (DocumentReceived)" if reg.get("pienemts") else "jauns ieraksts"}


async def _register_received(args: dict, task: str) -> dict:
    """DocumentReceived on the sender's register document, if the identity is trustworthy."""
    ident = args.get("a2a_identitate") or {}
    reg_did = str(ident.get("RegistraDID") or "").strip()
    caller_did = str(args.get("a2a_zvanitaja_did") or "").strip()
    if not reg_did:
        return {"pienemts": False, "iemesls": "sūtītājs nenodeva reģistra identitāti"}
    if not caller_did or caller_did != str(ident.get("SutitajaDID") or "").strip():
        # the organisation in the message must be the one the token was issued to
        return {"pienemts": False, "iemesls": "sūtītāja DID neatbilst žetonam", "registraDid": reg_did}
    from opendms import sdk_client
    from opendms.config import get_settings
    if not get_settings().sdk_enabled:
        return {"pienemts": False, "iemesls": "reģistra savienojums izslēgts", "registraDid": reg_did}
    try:
        res = await sdk_client.receive_document(reg_did, sender_did=caller_did, local_reg=f"a2a-{task}")
    except Exception as exc:
        logger.warning("register DocumentReceived %s: %s", reg_did, exc)
        return {"pienemts": False, "iemesls": str(exc), "registraDid": reg_did}
    ok = bool(res) and (res.get("_meta", {}).get("status_code", 200) in (200, 201))
    return {"pienemts": ok, "registraDid": reg_did, "sutitajaDid": caller_did,
            **({} if ok else {"iemesls": (res or {}).get("detail") or "reģistrs nepieņēma notikumu"})}


async def status_for(args: dict) -> dict:
    caller = str(args.get("a2a_zvanitajs") or "").strip()
    nr = str(args.get("registracijas_numurs") or "").strip()
    if not caller:
        raise ValueError("šo rīku izsauc tikai A2A uzdevumā")
    if not nr:
        raise ValueError("norādiet reģistrācijas numuru")
    from opendms.database import get_pool
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await conn.fetchrow(
            """SELECT id, registration_number, status, created_at, updated_at FROM documents
               WHERE registration_number = $1
                 AND metadata->'ievade'->>'veids' = 'a2a'
                 AND metadata->'ievade'->'a2a'->>'zvanitajs' = $2""", nr, caller)
    if not d:
        # Not found and not yours look the same on purpose: a peer learns nothing about other documents.
        return {"atrasts": False, "registracijasNr": nr,
                "piezime": "Šāds dokuments no jūsu aģenta nav saņemts."}
    return {"atrasts": True, "registracijasNr": d["registration_number"],
            "stavoklis": STATUS_LV.get(d["status"], d["status"]),
            "sanemts": d["created_at"].isoformat(timespec="minutes") if d["created_at"] else None,
            "atjaunots": d["updated_at"].isoformat(timespec="minutes") if d["updated_at"] else None}
