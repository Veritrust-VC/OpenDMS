"""DIV (e-adrese) emulators — laboratorijas aizstājējs VDAA DIV UnifiedService.

Emulē tās DIV darbības, ko izmanto DVS un e-rēķinu klienti:

    SendMessage(Envelope, AttachmentsInput[ContentId, Contents])  -> MessageId
    GetMessageServerConfirmation(MessageId)
    GetMessageHeaders()                                            -> neapstiprinātie ienākošie
    GetMessage(MessageId)                                          -> aploksne + pielikumi
    ConfirmMessage(MessageId, NotifySender)
    GetNotifications() / ConfirmNotifications(ids)                 -> sūtītāja paziņojumi
    AddressLists Search(q)                                         -> e-adrešu katalogs

Aploksne ir DIV aploksne (http://ivis.eps.gov.lv/XMLSchemas/100001/DIV/v1-0):
SenderDocument/DocumentMetadata (GeneralMetadata, PayloadReference/File ar
ContentReference + SHA-256, ExtendedMetadata) un SenderTransportMetadata. Serveris
pievieno ServerTransportMetadata (ServerReceivedTime, ServerRefNumber,
DeliveryDeadline, AvailabilityTime) — tāpat kā DIV.

Atšķirības no īstā DIV (apzināti, laboratorijai):
  - transports ir JSON pār HTTP, nevis SOAP + WS-Security;
  - autentifikācija ar žetonu katrai e-adresei, nevis sertifikātu;
  - aploksnes paraksts (XAdES) netiek pārbaudīts; pārbauda sūtītāja e-adresi,
    adresātus katalogā un katra pielikuma kontrolsummu un izmēru pret aploksni.

Konfigurācija: DIV_ADDRESSES (YAML ceļš), DIV_DATA (glabātuves mape).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import yaml
from fastapi import FastAPI, Header, HTTPException
from lxml import etree
from pydantic import BaseModel

NS = "http://ivis.eps.gov.lv/XMLSchemas/100001/DIV/v1-0"
DS = "http://www.w3.org/2000/09/xmldsig#"
N = {"div": NS, "ds": DS}
SHA256_URIS = {"http://www.w3.org/2001/04/xmlenc#sha256"}

DATA = Path(os.environ.get("DIV_DATA", "/data"))
ADDRESSES = Path(os.environ.get("DIV_ADDRESSES", "/etc/div/addresses.yaml"))
MAX_BYTES = int(os.environ.get("DIV_MAX_MB", "50")) * 1024 * 1024

app = FastAPI(title="DIV emulators (laboratorija)", version="1.0")
_lock = threading.Lock()


# ── adrešu katalogs un piekļuve ─────────────────────────────────────────────

def directory() -> list[dict]:
    """addresses.yaml: [{eAddress, name, code, token_env}]. Žetoni — vides mainīgajos."""
    with open(ADDRESSES, encoding="utf-8") as fh:
        return (yaml.safe_load(fh) or {}).get("adreses") or []


def caller(authorization: Optional[str]) -> dict:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token:
        for a in directory():
            expected = os.environ.get(a.get("token_env") or "", "")
            if expected and secrets.compare_digest(token, expected):
                return a
    raise HTTPException(401, "Nederīgs DIV žetons")


def known(e_address: str) -> Optional[dict]:
    return next((a for a in directory() if a["eAddress"] == e_address), None)


# ── glabātuve ──────────────────────────────────────────────────────────────

def db() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DATA / "div.sqlite3", isolation_level=None)
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY, sender TEXT NOT NULL, sender_ref TEXT, server_ref TEXT,
            title TEXT, kind TEXT, received_at TEXT, envelope BLOB);
        CREATE TABLE IF NOT EXISTS deliveries (
            message_id TEXT, recipient TEXT, fetched_at TEXT, confirmed_at TEXT,
            PRIMARY KEY (message_id, recipient));
        CREATE TABLE IF NOT EXISTS attachments (
            message_id TEXT, content_id TEXT, sha256 TEXT, size INTEGER,
            PRIMARY KEY (message_id, content_id));
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT, message_id TEXT, recipient TEXT,
            kind TEXT, at TEXT, acked INTEGER DEFAULT 0);
    """)
    return c


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def blob_path(mid: str, cid: str) -> Path:
    return DATA / "blobs" / mid / hashlib.sha256(cid.encode()).hexdigest()


# ── darbības ───────────────────────────────────────────────────────────────

class Attachment(BaseModel):
    contentId: str
    contents: str  # base64


class SendIn(BaseModel):
    envelope: str
    attachments: list[Attachment] = []


@app.post("/UnifiedService/SendMessage")
def send_message(req: SendIn, authorization: Optional[str] = Header(None)):
    me = caller(authorization)
    try:
        env = etree.fromstring(req.envelope.encode(), parser=etree.XMLParser(resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError as e:
        raise HTTPException(400, f"Aploksne nav derīgs XML: {e}")
    if env.tag != f"{{{NS}}}Envelope":
        raise HTTPException(400, "Saknes elements nav div:Envelope")
    st = env.find("div:SenderDocument/div:SenderTransportMetadata", N)
    gm = env.find("div:SenderDocument/div:DocumentMetadata/div:GeneralMetadata", N)
    if st is None or gm is None:
        raise HTTPException(400, "Trūkst SenderTransportMetadata vai GeneralMetadata")
    sender = st.findtext("div:SenderE-Address", namespaces=N)
    if sender != me["eAddress"]:
        raise HTTPException(403, f"Sūtītāja e-adrese {sender} neatbilst žetona e-adresei")
    recipients = [r.text for r in st.findall("div:Recipients/div:RecipientEntry/div:RecipientE-Address", N)]
    if not recipients:
        raise HTTPException(400, "Nav adresātu")
    unknown = [r for r in recipients if not known(r)]
    if unknown:
        raise HTTPException(400, f"E-adrese nav katalogā: {', '.join(unknown)}")
    for el in ("div:Title", "div:Date", "div:DocumentKind/div:DocumentKindCode"):
        if not gm.findtext(el, namespaces=N):
            raise HTTPException(400, f"GeneralMetadata: trūkst {el.split(':')[-1]}")

    # pielikumi pret PayloadReference
    att = {}
    total = 0
    for a in req.attachments:
        data = base64.b64decode(a.contents)
        total += len(data)
        att[a.contentId] = data
    if total > MAX_BYTES:
        raise HTTPException(413, "Pielikumi pārsniedz atļauto apjomu")
    files = env.findall("div:SenderDocument/div:DocumentMetadata/div:PayloadReference/div:File", N)
    declared = set()
    for f in files:
        cid = f.findtext("div:Content/div:ContentReference", namespaces=N)
        declared.add(cid)
        data = att.get(cid)
        if data is None:
            raise HTTPException(400, f"Pielikums {cid} norādīts aploksnē, bet nav nosūtīts")
        alg = f.find("div:Content/div:DigestMethod", N)
        if alg is None or alg.get("Algorithm") not in SHA256_URIS:
            raise HTTPException(400, f"{cid}: atbalstīts tikai SHA-256")
        dv = (f.findtext("div:Content/div:DigestValue", namespaces=N) or "").strip()
        if base64.b64encode(hashlib.sha256(data).digest()).decode() != dv:
            raise HTTPException(400, f"{cid}: kontrolsumma neatbilst aploksnei")
        if str(len(data)) != (f.findtext("div:Size", namespaces=N) or "").strip():
            raise HTTPException(400, f"{cid}: izmērs neatbilst aploksnei")
    extra = set(att) - declared
    if extra:
        raise HTTPException(400, f"Pielikumi nav aprakstīti aploksnē: {', '.join(sorted(extra))}")

    mid = str(uuid.uuid4())
    t = now()
    server_ref = f"DIV-{t:%Y%m%d}-{secrets.token_hex(4).upper()}"
    sm = etree.Element(f"{{{NS}}}ServerTransportMetadata")
    etree.SubElement(sm, f"{{{NS}}}ServerReceivedTime").text = t.isoformat()
    etree.SubElement(sm, f"{{{NS}}}ServerRefNumber").text = server_ref
    etree.SubElement(sm, f"{{{NS}}}DeliveryDeadline").text = (t + timedelta(days=30)).isoformat()
    etree.SubElement(sm, f"{{{NS}}}AvailabilityTime").text = t.isoformat()
    sd = env.find("div:SenderDocument", N)
    sd.addnext(sm)

    with _lock:
        c = db()
        c.execute("BEGIN")
        c.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?,?)",
                  (mid, sender, st.findtext("div:SenderRefNumber", namespaces=N), server_ref,
                   gm.findtext("div:Title", namespaces=N), gm.findtext("div:DocumentKind/div:DocumentKindCode", namespaces=N),
                   t.isoformat(), etree.tostring(env, encoding="UTF-8")))
        for r in recipients:
            c.execute("INSERT INTO deliveries (message_id, recipient) VALUES (?,?)", (mid, r))
        for cid, data in att.items():
            p = blob_path(mid, cid)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            c.execute("INSERT INTO attachments VALUES (?,?,?,?)", (mid, cid, hashlib.sha256(data).hexdigest(), len(data)))
        c.execute("COMMIT")
    return {"MessageId": mid, "ServerConfirmation": {"ServerReceivedTime": t.isoformat(), "ServerRefNumber": server_ref,
                                                    "Recipients": recipients}}


@app.get("/UnifiedService/GetMessageServerConfirmation/{mid}")
def server_confirmation(mid: str, authorization: Optional[str] = Header(None)):
    me = caller(authorization)
    c = db()
    m = c.execute("SELECT * FROM messages WHERE id=? AND sender=?", (mid, me["eAddress"])).fetchone()
    if not m:
        raise HTTPException(404, "Ziņojums nav atrasts")
    rows = c.execute("SELECT recipient, fetched_at, confirmed_at FROM deliveries WHERE message_id=?", (mid,)).fetchall()
    return {"MessageId": mid, "ServerReceivedTime": m["received_at"], "ServerRefNumber": m["server_ref"],
            "Deliveries": [dict(r) for r in rows]}


@app.get("/UnifiedService/GetMessageHeaders")
def headers(authorization: Optional[str] = Header(None)):
    me = caller(authorization)
    rows = db().execute(
        """SELECT m.id, m.sender, m.title, m.kind, m.received_at, m.server_ref, m.sender_ref
           FROM messages m JOIN deliveries d ON d.message_id = m.id
           WHERE d.recipient = ? AND d.confirmed_at IS NULL ORDER BY m.received_at""", (me["eAddress"],)).fetchall()
    return {"Headers": [{"MessageId": r["id"], "SenderE-Address": r["sender"],
                         "SenderName": (known(r["sender"]) or {}).get("name"), "Title": r["title"],
                         "DocumentKindCode": r["kind"], "ServerReceivedTime": r["received_at"],
                         "ServerRefNumber": r["server_ref"], "SenderRefNumber": r["sender_ref"]} for r in rows]}


@app.get("/UnifiedService/GetMessage/{mid}")
def get_message(mid: str, authorization: Optional[str] = Header(None)):
    me = caller(authorization)
    c = db()
    d = c.execute("SELECT * FROM deliveries WHERE message_id=? AND recipient=?", (mid, me["eAddress"])).fetchone()
    if not d:
        raise HTTPException(404, "Ziņojums nav atrasts")
    m = c.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone()
    atts = c.execute("SELECT content_id FROM attachments WHERE message_id=?", (mid,)).fetchall()
    if not d["fetched_at"]:
        t = now().isoformat()
        c.execute("UPDATE deliveries SET fetched_at=? WHERE message_id=? AND recipient=?", (t, mid, me["eAddress"]))
        c.execute("INSERT INTO notifications (sender, message_id, recipient, kind, at) VALUES (?,?,?,?,?)",
                  (m["sender"], mid, me["eAddress"], "Delivered", t))
    return {"MessageId": mid, "Envelope": m["envelope"].decode(),
            "Attachments": [{"ContentId": a["content_id"],
                             "Contents": base64.b64encode(blob_path(mid, a["content_id"]).read_bytes()).decode()}
                            for a in atts]}


class ConfirmIn(BaseModel):
    NotifySender: bool = True


@app.post("/UnifiedService/ConfirmMessage/{mid}")
def confirm(mid: str, req: ConfirmIn, authorization: Optional[str] = Header(None)):
    me = caller(authorization)
    c = db()
    d = c.execute("SELECT * FROM deliveries WHERE message_id=? AND recipient=?", (mid, me["eAddress"])).fetchone()
    if not d:
        raise HTTPException(404, "Ziņojums nav atrasts")
    if not d["confirmed_at"]:
        t = now().isoformat()
        c.execute("UPDATE deliveries SET confirmed_at=? WHERE message_id=? AND recipient=?", (t, mid, me["eAddress"]))
        if req.NotifySender:
            m = c.execute("SELECT sender FROM messages WHERE id=?", (mid,)).fetchone()
            c.execute("INSERT INTO notifications (sender, message_id, recipient, kind, at) VALUES (?,?,?,?,?)",
                      (m["sender"], mid, me["eAddress"], "Confirmed", t))
    return {"MessageId": mid, "Confirmed": True}


@app.get("/UnifiedService/GetNotifications")
def notifications(authorization: Optional[str] = Header(None)):
    me = caller(authorization)
    rows = db().execute("SELECT * FROM notifications WHERE sender=? AND acked=0 ORDER BY id", (me["eAddress"],)).fetchall()
    return {"Notifications": [{"Id": r["id"], "MessageId": r["message_id"], "RecipientE-Address": r["recipient"],
                               "Kind": r["kind"], "Time": r["at"]} for r in rows]}


class AckIn(BaseModel):
    Ids: list[int]


@app.post("/UnifiedService/ConfirmNotifications")
def ack_notifications(req: AckIn, authorization: Optional[str] = Header(None)):
    me = caller(authorization)
    c = db()
    for i in req.Ids:
        c.execute("UPDATE notifications SET acked=1 WHERE id=? AND sender=?", (i, me["eAddress"]))
    return {"Confirmed": len(req.Ids)}


@app.get("/AddressLists/Search")
def search(q: str = "", authorization: Optional[str] = Header(None)):
    caller(authorization)
    ql = q.strip().lower()
    return {"Results": [{"E-Address": a["eAddress"], "Name": a["name"], "Code": a.get("code"), "Did": a.get("did")}
                        for a in directory()
                        if not ql or ql in a["name"].lower() or ql in a["eAddress"].lower() or ql in str(a.get("code", ""))]}


@app.get("/health")
def health():
    return {"ok": True, "adreses": len(directory())}
