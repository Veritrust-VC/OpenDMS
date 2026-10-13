"""E-mail input channel — polls an IMAP mailbox, sends acknowledgements over SMTP.

Transport is the existing mailbox driver (connectors/email_box.py); this file
only maps the channel's YAML settings onto it and runs the loop.

Per message:
  sender allowed?  no  -> recorded as 'noraidits', marked read, no reply
                   yes -> intake.ingest() -> document -> processes
  then marked read (\\Seen). Duplicates (same Message-ID) are skipped.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from opendms.connectors import email_box
from opendms.intake import config as cfg
from opendms.intake import service

logger = logging.getLogger(__name__)

LOCK_KEY = 0x0EDA1  # pg advisory lock: one poller per database


def _driver_config(ch: dict) -> tuple[dict, dict]:
    imap = ch.get("imap") or {}
    smtp = ch.get("smtp") or {}
    conf = {
        "imap_host": imap.get("host"), "imap_port": imap.get("port"), "imap_ssl": imap.get("ssl", True),
        "imap_user": imap.get("lietotajs"), "folder": imap.get("mape", "INBOX"),
        "smtp_host": smtp.get("host") or imap.get("host"), "smtp_port": smtp.get("port"),
        "smtp_starttls": smtp.get("starttls", True), "smtp_user": smtp.get("lietotajs"),
        "from_address": smtp.get("no_adreses") or imap.get("lietotajs"),
        "max_attachment_mb": ch.get("max_mb", 25),
    }
    pw = cfg.password(ch)
    smtp_pw = cfg.password({"parole_env": smtp.get("parole_env")}) if smtp.get("parole_env") else ""
    return conf, {"imap_password": pw, "smtp_password": smtp_pw or pw}


async def poll_once(ch: dict) -> dict[str, Any]:
    conf, secret = _driver_config(ch)
    res = await email_box.invoke("fetch", conf, secret, {"limit": 20, "unseen_only": True}, {})
    if not res.ok:
        return {"kluda": res.reason}
    done, out = [], {"registreti": [], "noraiditi": [], "kludas": []}
    for m in res.data.get("messages", []):
        ref = m.get("message_id") or f"uid:{m['uid']}:{m.get('received_at')}"
        sender = service.parse_sender(m.get("from"))
        own = {(conf.get("from_address") or "").lower(), (conf.get("imap_user") or "").lower()}
        robot = (m.get("auto_submitted") not in ("", "no")) or m.get("precedence") in ("bulk", "junk", "list")
        if (sender.get("email") or "") in own or robot:
            # Our own acknowledgements, bounces, auto-replies: never a document, never answered.
            await service.record_rejected(ch, ref, sender.get("email"), m.get("subject"),
                                          "automātiska vai pašas pastkastes ziņa")
            out["noraiditi"].append(sender.get("email"))
            done.append(m["uid"])
            continue
        if not cfg.sender_allowed(ch, sender.get("email") or ""):
            await service.record_rejected(ch, ref, sender.get("email"), m.get("subject"), "sūtītājs nav atļauto sarakstā")
            out["noraiditi"].append(sender.get("email"))
            done.append(m["uid"])
            continue
        atts, skipped = [], []
        for a in m.get("attachments", []):
            if a.get("truncated") or "content_b64" not in a:
                skipped.append(a.get("file_name"))
                continue
            atts.append({"file_name": a["file_name"], "mime_type": a.get("mime_type"),
                         "data": base64.b64decode(a["content_b64"])})
        try:
            r = await service.ingest(ch, external_ref=ref, sender=sender, subject=m.get("subject") or "",
                                     body=m.get("body") or "", attachments=atts, received_at=m.get("received_at"),
                                     extra={"izlaistasDatnes": skipped} if skipped else None)
            out["registreti"].append(r.get("documentId"))
            done.append(m["uid"])
        except Exception as exc:
            # Left unread: retried on the next poll.
            logger.exception("intake %s: message %s failed", ch["id"], ref)
            out["kludas"].append(f"{type(exc).__name__}: {exc}")
    if done:
        await email_box.invoke("mark_seen", conf, secret, {"uids": done}, {})

    out["apstiprinajumi"] = await service.process_acks(ch, sender_for(ch))
    return out


def sender_for(mail_ch: dict):
    """SMTP transport of an e-mail channel, as the send() that process_acks expects."""
    conf, secret = _driver_config(mail_ch)

    async def send(to, subject, body, in_reply_to):
        r = await email_box.invoke("send", conf, secret, {"to": to, "subject": subject, "body": body,
                                                          "in_reply_to": in_reply_to,
                                                          "auto_submitted": True}, {})
        if not r.ok:
            raise RuntimeError(r.reason)
    return send


async def form_acks() -> None:
    """Web form submitters get the same acknowledgement, sent through a named e-mail channel."""
    for ch in cfg.channels("tiessaistes-forma"):
        via = (ch.get("apstiprinajums") or {}).get("kanals")
        mail = cfg.channel(via) if via else None
        if mail and mail.get("veids") == "epasts" and cfg.password(mail):
            await service.process_acks(ch, sender_for(mail))


async def _div_tick(loop, last: dict) -> None:
    """e-adrese (DIV): incoming messages for an enabled 'e-adrese' channel, and
    delivery notifications for documents this DVS forwarded."""
    from opendms import div
    if not div.configured():
        return
    for ch in cfg.channels("e-adrese"):
        interval = max(15, int(ch.get("intervals_s", 30)))
        if loop.time() - last.get(ch["id"], 0) < interval:
            continue
        last[ch["id"]] = loop.time()
        try:
            from opendms.intake.div_channel import poll_once as div_poll
            r = await div_poll(ch)
            if r["registreti"] or r["kludas"]:
                logger.info("intake %s: %s", ch["id"], r)
        except Exception:
            logger.exception("intake %s: poll failed", ch["id"])
    if loop.time() - last.get("_div_notifications", 0) >= 20:
        last["_div_notifications"] = loop.time()
        try:
            from opendms.div.forwarding import poll_notifications
            n = await poll_notifications()
            if n:
                logger.info("e-adrese: %d delivery notification(s)", n)
        except Exception:
            logger.exception("e-adrese: notifications failed")


async def run_forever() -> None:
    """Background loop started with the app. Holds a DB advisory lock so only one process polls."""
    from opendms.database import get_pool

    pool = await get_pool()
    conn = await pool.acquire()
    try:
        if not await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY):
            logger.info("intake: another process polls the mailboxes")
            return
        logger.info("intake: e-mail poller started (config %s)", cfg.path())
        last: dict[str, float] = {}
        loop = asyncio.get_running_loop()
        while True:
            for ch in cfg.channels("epasts"):
                interval = max(15, int(ch.get("intervals_s", 60)))
                if loop.time() - last.get(ch["id"], 0) < interval:
                    continue
                last[ch["id"]] = loop.time()
                if not cfg.password(ch):
                    logger.warning("intake %s: %s is not set; channel skipped", ch["id"], ch.get("parole_env"))
                    continue
                try:
                    r = await poll_once(ch)
                    if r.get("kluda"):
                        logger.warning("intake %s: %s", ch["id"], r["kluda"])
                    elif r["registreti"] or r["noraiditi"] or r["apstiprinajumi"] or r["kludas"]:
                        logger.info("intake %s: %s", ch["id"], r)
                except Exception:
                    logger.exception("intake %s: poll failed", ch["id"])
            try:
                await form_acks()
            except Exception:
                logger.exception("intake: form acknowledgements failed")
            await _div_tick(loop, last)
            await asyncio.sleep(10)
    except asyncio.CancelledError:
        pass
    finally:
        try:
            await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
        finally:
            await pool.release(conn)
