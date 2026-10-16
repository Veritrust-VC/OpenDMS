"""DIV (e-adrese) — DIV aploksne un klients.

Aploksne pēc DIVEnvelope.xsd (http://ivis.eps.gov.lv/XMLSchemas/100001/DIV/v1-0), kā to
veido e-rēķinu klients: SenderDocument/DocumentMetadata (GeneralMetadata,
PayloadReference/File ar SHA-256, ExtendedMetadata) + SenderTransportMetadata.
ExtendedMetadata nes dokumenta identitāti pēc Dokumentu metadatu standarta
(LV-DOK, reģistra DID, sūtītāja DID, pārsūtīšanas iemesls), lai saņēmējs saglabā izcelsmi.

Klients runā ar DIV emulatoru (div-emulator/) — tās pašas darbības kā DIV
UnifiedService. Iestatījumi: OPENDMS_DIV_URL, OPENDMS_DIV_TOKEN, OPENDMS_DIV_E_ADDRESS.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import date
from typing import Any, Optional

import httpx
from lxml import etree

NS = "http://ivis.eps.gov.lv/XMLSchemas/100001/DIV/v1-0"
DS = "http://www.w3.org/2000/09/xmldsig#"
PNS = "urn:lv:vdvc:parsutisana:1.0"
SHA256 = "http://www.w3.org/2001/04/xmlenc#sha256"
N = {"div": NS, "p": PNS}


def config() -> dict:
    return {"url": os.environ.get("OPENDMS_DIV_URL", "").rstrip("/"),
            "token": os.environ.get("OPENDMS_DIV_TOKEN", ""),
            "eAddress": os.environ.get("OPENDMS_DIV_E_ADDRESS", "")}


def configured() -> bool:
    c = config()
    return bool(c["url"] and c["token"] and c["eAddress"])


def _q(local: str) -> str:
    return f"{{{NS}}}{local}"


def _sub(parent, local: str, text: Optional[str] = None):
    el = etree.SubElement(parent, _q(local))
    if text is not None:
        el.text = text
    return el


def build_envelope(*, sender: str, recipients: list[str], sender_ref: str, title: str, description: str,
                   author: str, kind_code: str, files: list[dict], identity: dict,
                   notify_on_delivery: bool = True) -> bytes:
    """files: [{content_id, name, mime_type, data}]; identity -> ExtendedMetadata (p:Parsutisana)."""
    env = etree.Element(_q("Envelope"), nsmap={"div": NS, "ds": DS})
    sd = _sub(env, "SenderDocument")
    sd.set("Id", "SenderSection")
    dm = _sub(sd, "DocumentMetadata")
    gm = _sub(dm, "GeneralMetadata")
    _sub(_sub(_sub(gm, "Authors"), "AuthorEntry"), "InformationSystem", author[:100])
    _sub(gm, "Date", date.today().isoformat())
    dk = _sub(gm, "DocumentKind")
    _sub(dk, "DocumentKindCode", kind_code)
    _sub(dk, "DocumentKindVersion", "1.0")
    if description:
        _sub(gm, "Description", description[:2000])
    _sub(gm, "Title", (title or "Dokuments")[:500])
    pr = _sub(dm, "PayloadReference")
    for n, f in enumerate(files, 1):
        fe = _sub(pr, "File")
        _sub(fe, "MimeType", f.get("mime_type") or "application/octet-stream")
        _sub(fe, "Size", str(len(f["data"])))
        _sub(fe, "Name", f["name"][:200])
        ct = _sub(fe, "Content")
        _sub(ct, "ContentReference", f["content_id"])
        etree.SubElement(ct, _q("DigestMethod")).set("Algorithm", SHA256)
        _sub(ct, "DigestValue", base64.b64encode(hashlib.sha256(f["data"]).digest()).decode())
        _sub(fe, "Compressed", "false")
        _sub(fe, "AppendixNumber", str(n))
    em = _sub(dm, "ExtendedMetadata")
    p = etree.SubElement(em, f"{{{PNS}}}Parsutisana", nsmap={"p": PNS})
    for k, v in identity.items():
        if v not in (None, ""):
            etree.SubElement(p, f"{{{PNS}}}{k}").text = str(v)
    st = _sub(sd, "SenderTransportMetadata")
    _sub(st, "SenderE-Address", sender)
    _sub(st, "SenderRefNumber", sender_ref[:50])
    rs = _sub(st, "Recipients")
    for r in recipients:
        _sub(_sub(rs, "RecipientEntry"), "RecipientE-Address", r)
    _sub(st, "NotifySenderOnDelivery", "true" if notify_on_delivery else "false")
    _sub(st, "Priority", "normal")
    sig = _sub(env, "Signatures")
    etree.SubElement(sig, f"{{{DS}}}Signature")  # vieta parakstam, kā DIV klientā
    return etree.tostring(env, xml_declaration=True, encoding="UTF-8", pretty_print=True)


def parse_envelope(xml: str | bytes) -> dict[str, Any]:
    env = etree.fromstring(xml.encode() if isinstance(xml, str) else xml,
                           parser=etree.XMLParser(resolve_entities=False, no_network=True))
    t = lambda p: env.findtext(p, namespaces=N)  # noqa: E731
    gm = "div:SenderDocument/div:DocumentMetadata/div:GeneralMetadata/"
    files = [{"content_id": f.findtext("div:Content/div:ContentReference", namespaces=N),
              "name": f.findtext("div:Name", namespaces=N), "mime_type": f.findtext("div:MimeType", namespaces=N),
              "sha256_b64": f.findtext("div:Content/div:DigestValue", namespaces=N),
              "size": int(f.findtext("div:Size", namespaces=N) or 0)}
             for f in env.findall("div:SenderDocument/div:DocumentMetadata/div:PayloadReference/div:File", N)]
    ident = {}
    p = env.find("div:SenderDocument/div:DocumentMetadata/div:ExtendedMetadata/p:Parsutisana", N)
    if p is not None:
        ident = {etree.QName(c).localname: c.text for c in p}
    return {"title": t(gm + "div:Title"), "description": t(gm + "div:Description"), "date": t(gm + "div:Date"),
            "kind": t(gm + "div:DocumentKind/div:DocumentKindCode"),
            "sender": t("div:SenderDocument/div:SenderTransportMetadata/div:SenderE-Address"),
            "senderRef": t("div:SenderDocument/div:SenderTransportMetadata/div:SenderRefNumber"),
            "serverRef": t("div:ServerTransportMetadata/div:ServerRefNumber"),
            "serverReceived": t("div:ServerTransportMetadata/div:ServerReceivedTime"),
            "files": files, "identity": ident}


class DivError(RuntimeError):
    pass


async def _call(method: str, path: str, **kw) -> dict:
    c = config()
    if not configured():
        raise DivError("DIV nav konfigurēts (OPENDMS_DIV_URL, OPENDMS_DIV_TOKEN, OPENDMS_DIV_E_ADDRESS)")
    async with httpx.AsyncClient(timeout=60.0) as hc:
        r = await hc.request(method, c["url"] + path, headers={"Authorization": f"Bearer {c['token']}"}, **kw)
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except Exception:
            detail = r.text[:300]
        raise DivError(f"DIV {path.split('/')[2] if path.count('/') > 1 else path}: HTTP {r.status_code} {detail}")
    return r.json()


async def send(envelope: bytes, files: list[dict]) -> dict:
    return await _call("POST", "/UnifiedService/SendMessage", json={
        "envelope": envelope.decode(),
        "attachments": [{"contentId": f["content_id"], "contents": base64.b64encode(f["data"]).decode()} for f in files]})


async def headers() -> list[dict]:
    return (await _call("GET", "/UnifiedService/GetMessageHeaders")).get("Headers", [])


async def get(mid: str) -> dict:
    return await _call("GET", f"/UnifiedService/GetMessage/{mid}")


async def confirm(mid: str) -> dict:
    return await _call("POST", f"/UnifiedService/ConfirmMessage/{mid}", json={"NotifySender": True})


async def notifications() -> list[dict]:
    return (await _call("GET", "/UnifiedService/GetNotifications")).get("Notifications", [])


async def ack(ids: list[int]) -> None:
    if ids:
        await _call("POST", "/UnifiedService/ConfirmNotifications", json={"Ids": ids})


async def search(q: str = "") -> list[dict]:
    return (await _call("GET", "/AddressLists/Search", params={"q": q})).get("Results", [])
