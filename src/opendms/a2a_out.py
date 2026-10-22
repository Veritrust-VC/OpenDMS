"""A2A — sending a document to another institution's MI agent.

The organisation's own agent sends a DVS document to a peer agent (for example
an application forwarded by competence). Two tools, both called by the agent
runtime itself, never shown to the language model:

  a2a_izsutamais_dokuments   the document's primary file, short metadata and its
                             identity (document ID, central register DID), so the
                             file goes from the DVS straight into the A2A message
                             (the bytes never pass through the model). With the
                             addressee's DID it first records DocumentSent in the
                             central register — the register keeps the record and
                             the chain of custody, never the content.
  a2a_atzimet_nosutitu       after the peer answered: an 'AtzimetsNosutits'
                             event on the document with the addressee, its
                             registration number and the A2A task, and the
                             dispatch kept in metadata.nosutisana

Sending does not change the document's status: forwarding an incoming document
by competence is one step in its handling, and a person closes it.
"""

from __future__ import annotations

import base64
import json
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

MAX_BYTES = 15 * 1024 * 1024


def _j(v) -> dict:
    return json.loads(v) if isinstance(v, str) else (v or {})


async def _find(conn, args: dict):
    doc_id = args.get("document_id")
    nr = str(args.get("registracijas_numurs") or "").strip()
    if doc_id not in (None, ""):
        return await conn.fetchrow(
            "SELECT id, registration_number, title, status, metadata, content_summary, created_at, doc_uid, doc_did, org_id "
            "FROM documents WHERE id = $1", int(doc_id))
    if nr:
        return await conn.fetchrow(
            "SELECT id, registration_number, title, status, metadata, content_summary, created_at, doc_uid, doc_did, org_id "
            "FROM documents WHERE registration_number = $1", nr)
    raise ValueError("norādiet dokumenta reģistrācijas numuru")


async def outgoing(args: dict) -> dict:
    """The document to send: metadata plus its primary file (base64)."""
    from opendms.database import get_pool
    from opendms.storage import get_storage
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await _find(conn, args)
        if not d:
            raise ValueError("dokuments nav atrasts")
        f = await conn.fetchrow(
            """SELECT file_name, mime_type, file_size, storage_key FROM document_files
                WHERE document_id = $1 ORDER BY is_primary DESC, id LIMIT 1""", d["id"])
        org_did = await conn.fetchval("SELECT org_did FROM organizations WHERE id = $1", d.get("org_id")) if d.get("org_id") else None
    meta = _j(d["metadata"])
    out = {"document_id": d["id"], "registracijasNr": d["registration_number"], "temats": d["title"],
           "kopsavilkums": d["content_summary"], "statuss": d["status"],
           "dokumentaDatums": (meta.get("dokumentaDatums") or (d["created_at"].date().isoformat() if d["created_at"] else None)),
           "dokumentaVeids": meta.get("dokumentaVeids"),
           "nosutisana": meta.get("nosutisana") or [],
           "identitate": {"DokumentaID": d.get("doc_uid"), "RegistraDID": d.get("doc_did"), "SutitajaDID": org_did,
                          "SutitajaRegNr": d["registration_number"]}}
    to = str(args.get("adresata_did") or "").strip()
    if to and d.get("doc_did"):
        out["registrs"] = await _register_sent(d.get("doc_did"), to)
    if f:
        if (f["file_size"] or 0) > MAX_BYTES:
            raise ValueError("datne pārsniedz 15 MB")
        data = await get_storage().get(f["storage_key"])
        out.update(file_name=f["file_name"], mime_type=f["mime_type"] or "application/octet-stream",
                   file_b64=base64.b64encode(data).decode())
    return out


async def _register_sent(doc_did: str, recipient_did: str) -> dict:
    """DocumentSent in the central register, delivery method A2A."""
    from opendms import sdk_client
    from opendms.config import get_settings
    if not get_settings().sdk_enabled:
        return {"notikums": False, "iemesls": "reģistra savienojums izslēgts"}
    try:
        res = await sdk_client.send_document(doc_did, recipient_did=recipient_did, method="A2A (aģents aģentam)")
    except Exception as exc:  # the register must not block the handover; the gap is recorded
        logger.warning("register DocumentSent %s -> %s: %s", doc_did, recipient_did, exc)
        return {"notikums": False, "iemesls": str(exc)}
    ok = bool(res) and (res.get("_meta", {}).get("status_code", 200) in (200, 201))
    return {"notikums": ok, "registraDid": doc_did, "adresataDid": recipient_did,
            **({} if ok else {"iemesls": (res or {}).get("detail") or "reģistrs nepieņēma notikumu"})}


async def record_sent(args: dict, actor: dict) -> dict:
    """Event + metadata after the peer agent accepted the document."""
    from opendms.database import get_pool
    adresats = str(args.get("adresats") or "").strip()
    task = str(args.get("a2a_uzdevums") or "").strip()
    if not adresats or not task:
        raise ValueError("norādiet adresātu un A2A uzdevumu")
    entry = {"kanals": "a2a", "adresats": adresats, "adresataIestade": args.get("adresata_iestade") or None,
             "adresataRegNr": args.get("adresata_reg_nr") or None, "adresataDid": args.get("adresata_did") or None,
             "uzdevums": task,
             "stavoklis": args.get("stavoklis") or None,
             "laiks": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "persona": args.get("persona") or None}
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await _find(conn, args)
        if not d:
            raise ValueError("dokuments nav atrasts")
        meta = _j(d["metadata"])
        if any(x.get("uzdevums") == task for x in meta.get("nosutisana") or []):
            return {"atzimets": True, "jauAtzimets": True, "document_id": d["id"]}
        await conn.execute(
            "UPDATE documents SET metadata = jsonb_set(COALESCE(metadata,'{}'::jsonb), '{nosutisana}', "
            "COALESCE(metadata->'nosutisana','[]'::jsonb) || $2::jsonb), updated_at = NOW() WHERE id = $1",
            d["id"], json.dumps([entry], ensure_ascii=False))
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, 'AtzimetsNosutits', $2, FALSE, $3)""",
            d["id"], actor["id"], json.dumps({**entry, "nosutisana": "A2A: nosūtīts citas iestādes MI aģentam"},
                                             ensure_ascii=False))
    logger.info("a2a: document %s sent to %s (task %s, their nr %s)", d["id"], adresats, task,
                entry["adresataRegNr"])
    return {"atzimets": True, "jauAtzimets": False, "document_id": d["id"], "registracijasNr": d["registration_number"]}
