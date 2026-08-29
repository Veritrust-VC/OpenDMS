"""Mailbox connector — IMAP inbound, SMTP outbound. Real implementation.

This is the intake path for Rīgas siltums: documents arrive as e-mail to a
shared address, get polled from IMAP, and become OpenDMS documents with their
attachments. Nothing existed for this in either OpenDMS or OpenITSM — OpenITSM
had two enum values and a README saying "Placeholder".

DELIBERATELY PLAIN IMAP/SMTP, not Graph/EWS. Rihards confirmed a plain mailbox,
which keeps the connector vendor-neutral: the same driver works against
Exchange with IMAP enabled, Zimbra, Postfix/Dovecot or MailEnable. If Exchange
Online with modern auth is ever mandated, that is a *second* driver (kind
email_graph), not a rewrite of this one.

THREADING. imaplib and smtplib are blocking and this runs inside a FastAPI
event loop, so every network call goes through asyncio.to_thread. Calling them
directly would stall every other request on the worker for the duration of the
poll — which on a slow mailbox is seconds, not milliseconds.

THE DRIVER DOES NOT CREATE DOCUMENTS. It normalises messages and hands them
back. Turning a message into a document, a register entry and a lifecycle VC is
the intake service's job. Keeping transport and domain apart is what makes it
possible to test the mailbox without writing rows.
"""

from __future__ import annotations

import asyncio
import base64
import email
import imaplib
import smtplib
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from typing import Any

from opendms.connectors.base import Field, Operation, Result, missing_fields

KIND = "email_imap"
DISPLAY_NAME = "Mailbox (IMAP / SMTP)"
IMPLEMENTED = True
SUMMARY = "Polls a shared mailbox into documents and sends outbound replies."

CONFIG_FIELDS = (
    Field("imap_host", "IMAP host", placeholder="mail.example.lv"),
    Field("imap_port", "IMAP port", required=False, kind="number", placeholder="993"),
    Field("imap_ssl", "IMAP SSL", required=False, kind="bool", help="Defaults to on (port 993)."),
    Field("imap_user", "IMAP user"),
    Field("folder", "Folder", required=False, placeholder="INBOX"),
    Field("smtp_host", "SMTP host", required=False, placeholder="mail.example.lv"),
    Field("smtp_port", "SMTP port", required=False, kind="number", placeholder="587"),
    Field("smtp_starttls", "SMTP STARTTLS", required=False, kind="bool"),
    Field("smtp_user", "SMTP user", required=False,
          help="Leave blank to reuse the IMAP user."),
    Field("from_address", "From address", required=False, placeholder="dvs@example.lv"),
    Field("max_attachment_mb", "Max attachment size (MB)", required=False, kind="number",
          placeholder="25"),
)

SECRET_FIELDS = (
    Field("imap_password", "IMAP password", kind="password"),
    Field("smtp_password", "SMTP password", kind="password", required=False,
          help="Leave blank to reuse the IMAP password."),
)

OPERATIONS = (
    Operation("fetch", "connector/email.fetch",
              "Poll unread messages from the mailbox.", direction="inbound"),
    Operation("send", "connector/email.send", "Send an outbound message."),
    Operation("mark_seen", "connector/email.mark-seen",
              "Mark messages as read once they have been ingested."),
)

SPEC: tuple[str, ...] = ()

_TIMEOUT = 30


def _s(value: Any, default: str = "") -> str:
    return str(value).strip() if value is not None and str(value).strip() else default


def _decode(raw: Any) -> str:
    """Decode RFC 2047 headers (=?UTF-8?B?...?=) into plain text.

    Latvian subjects are almost always encoded this way; skipping it yields
    mojibake in every document title.
    """
    if raw is None:
        return ""
    try:
        return str(make_header(decode_header(str(raw))))
    except Exception:
        return str(raw)


def _smtp_creds(config: dict, secret: dict) -> tuple[str, str]:
    user = _s(config.get("smtp_user")) or _s(config.get("imap_user"))
    password = _s(secret.get("smtp_password")) or _s(secret.get("imap_password"))
    return user, password


def _imap_connect(config: dict, secret: dict) -> imaplib.IMAP4:
    host = _s(config.get("imap_host"))
    ssl_on = config.get("imap_ssl", True) not in (False, "false", "False", 0, "0")
    port = int(_s(config.get("imap_port"), "993" if ssl_on else "143"))
    cls = imaplib.IMAP4_SSL if ssl_on else imaplib.IMAP4
    conn = cls(host, port, timeout=_TIMEOUT)
    conn.login(_s(config.get("imap_user")), _s(secret.get("imap_password")))
    return conn


def _walk_message(msg: email.message.Message, max_bytes: int) -> tuple[str, list[dict]]:
    """Split a message into its best-effort plain-text body and its attachments."""
    body_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[dict] = []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        disposition = (part.get("Content-Disposition") or "").lower()
        filename = _decode(part.get_filename())
        payload = part.get_payload(decode=True) or b""
        if filename or "attachment" in disposition:
            record = {
                "file_name": filename or "attachment.bin",
                "mime_type": part.get_content_type(),
                "size": len(payload),
                "truncated": len(payload) > max_bytes,
            }
            if len(payload) <= max_bytes:
                record["content_b64"] = base64.b64encode(payload).decode()
            attachments.append(record)
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        (body_parts if part.get_content_type() == "text/plain" else html_parts).append(text)
    body = "\n".join(body_parts).strip()
    if not body and html_parts:
        # No text/plain alternative — keep the HTML rather than returning nothing.
        body = html_parts[0].strip()
    return body, attachments


def _fetch_sync(config: dict, secret: dict, limit: int, unseen_only: bool) -> dict:
    max_bytes = int(float(_s(config.get("max_attachment_mb"), "25")) * 1024 * 1024)
    conn = _imap_connect(config, secret)
    try:
        conn.select(_s(config.get("folder"), "INBOX"))
        typ, data = conn.search(None, "UNSEEN" if unseen_only else "ALL")
        if typ != "OK":
            return {"error": f"IMAP search failed: {typ}"}
        uids = (data[0] or b"").split()
        selected = uids[-limit:] if limit else uids
        messages = []
        for uid in selected:
            typ, raw = conn.fetch(uid, "(BODY.PEEK[])")  # PEEK: do not set \Seen yet
            if typ != "OK" or not raw or not raw[0]:
                continue
            msg = email.message_from_bytes(raw[0][1])
            body, attachments = _walk_message(msg, max_bytes)
            try:
                received = parsedate_to_datetime(msg.get("Date")).isoformat()
            except Exception:
                received = None
            messages.append({
                "uid": uid.decode(),
                "message_id": _s(msg.get("Message-ID")),
                "subject": _decode(msg.get("Subject")),
                "from": _decode(msg.get("From")),
                "to": _decode(msg.get("To")),
                "received_at": received,
                "body": body[:100000],
                "attachments": attachments,
            })
        return {"messages": messages, "unread_total": len(uids)}
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()


def _mark_seen_sync(config: dict, secret: dict, uids: list[str]) -> dict:
    conn = _imap_connect(config, secret)
    try:
        conn.select(_s(config.get("folder"), "INBOX"))
        for uid in uids:
            conn.store(str(uid).encode(), "+FLAGS", "\\Seen")
        return {"marked": len(uids)}
    finally:
        try:
            conn.close()
        except Exception:
            pass
        conn.logout()


def _send_sync(config: dict, secret: dict, inputs: dict) -> dict:
    user, password = _smtp_creds(config, secret)
    host = _s(config.get("smtp_host")) or _s(config.get("imap_host"))
    starttls = config.get("smtp_starttls", True) not in (False, "false", "False", 0, "0")
    port = int(_s(config.get("smtp_port"), "587" if starttls else "25"))
    msg = EmailMessage()
    msg["From"] = _s(config.get("from_address")) or user
    msg["To"] = inputs["to"]
    msg["Subject"] = inputs.get("subject") or "(no subject)"
    if inputs.get("in_reply_to"):
        msg["In-Reply-To"] = inputs["in_reply_to"]
        msg["References"] = inputs["in_reply_to"]
    msg.set_content(inputs.get("body") or "")
    for att in inputs.get("attachments") or []:
        raw = base64.b64decode(att["content_b64"])
        maintype, _, subtype = (att.get("mime_type") or "application/octet-stream").partition("/")
        msg.add_attachment(raw, maintype=maintype, subtype=subtype or "octet-stream",
                           filename=att.get("file_name") or "attachment.bin")
    with smtplib.SMTP(host, port, timeout=_TIMEOUT) as s:
        if starttls:
            s.starttls()
        if user and password:
            s.login(user, password)
        s.send_message(msg)
    return {"sent": True, "to": inputs["to"]}


async def test(config: dict, secret: dict) -> Result:
    missing = missing_fields(CONFIG_FIELDS, config) + missing_fields(SECRET_FIELDS, secret)
    if missing:
        return Result.fail("connection incomplete", missing=missing)
    try:
        probe = await asyncio.to_thread(_fetch_sync, config, secret, 1, False)
    except imaplib.IMAP4.error as exc:
        return Result.fail(f"IMAP rejected the login: {exc}")
    except Exception as exc:
        return Result.fail(f"{type(exc).__name__}: {exc}")
    if probe.get("error"):
        return Result.fail(probe["error"])

    detail = f"IMAP OK — {probe.get('unread_total', 0)} message(s) in the folder"
    smtp_state = "not configured"
    if _s(config.get("smtp_host")) or _s(config.get("imap_host")):
        try:
            user, password = _smtp_creds(config, secret)
            host = _s(config.get("smtp_host")) or _s(config.get("imap_host"))
            starttls = config.get("smtp_starttls", True) not in (False, "false", "False", 0, "0")
            port = int(_s(config.get("smtp_port"), "587" if starttls else "25"))

            def _probe_smtp():
                with smtplib.SMTP(host, port, timeout=_TIMEOUT) as s:
                    if starttls:
                        s.starttls()
                    if user and password:
                        s.login(user, password)
                return True

            await asyncio.to_thread(_probe_smtp)
            smtp_state = "OK"
        except Exception as exc:
            # An unusable SMTP leg does not invalidate intake, so report it
            # without failing the whole test.
            smtp_state = f"{type(exc).__name__}: {exc}"
    return Result.good(detail=f"{detail}; SMTP {smtp_state}",
                       unread_total=probe.get("unread_total", 0), smtp=smtp_state)


async def invoke(operation: str, config: dict, secret: dict, inputs: dict, ctx: dict) -> Result:
    missing = missing_fields(CONFIG_FIELDS, config) + missing_fields(SECRET_FIELDS, secret)
    if missing:
        return Result.fail("connection incomplete", missing=missing)
    try:
        if operation == "fetch":
            out = await asyncio.to_thread(
                _fetch_sync, config, secret,
                int(inputs.get("limit") or 20),
                inputs.get("unseen_only", True) is not False,
            )
            if out.get("error"):
                return Result.fail(out["error"])
            return Result.good(**out)
        if operation == "mark_seen":
            uids = inputs.get("uids") or []
            if not uids:
                return Result.fail("uids is required")
            return Result.good(**await asyncio.to_thread(_mark_seen_sync, config, secret, uids))
        if operation == "send":
            if not inputs.get("to"):
                return Result.fail("to is required")
            return Result.good(**await asyncio.to_thread(_send_sync, config, secret, inputs))
    except Exception as exc:
        return Result.fail(f"{type(exc).__name__}: {exc}")
    return Result.fail(f"unknown email operation '{operation}'",
                       available=["fetch", "send", "mark_seen"])
