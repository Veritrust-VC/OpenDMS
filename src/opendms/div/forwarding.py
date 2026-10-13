"""Dokumenta pārsūtīšana citai iestādei e-adresē (DIV) — procesa spējas.

Process vdvc/dokumenta-parsutisana (UAPF) izsauc:

    forward.request@1   nolasa darbinieka pieprasījumu (adresāts, iemesls, pavadteksts, datnes)
    div.send@1          sagatavo DIV aploksni un nosūta (veids un metadatu pievienošana — no DMN)
    forward.record@1    ieraksta nosūtīšanu DVS un centrālajā reģistrā (DocumentSent → adresāta DID)
    submitter.notify@1  informē iesniedzēju, ka iesniegums pārsūtīts (ja DMN tā nosaka)

Pieprasījumu DVS saskarnē saglabā metadata.parsutisana; process to izpilda.
Sūtīšanas stāvoklis tiek atjaunināts no DIV paziņojumiem (Delivered, Confirmed).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from opendms import div
from opendms.database import get_pool

logger = logging.getLogger(__name__)

REASONS = {
    "piekritiba": "Pārsūtīts pēc piekritības",
    "informacijai": "Nosūtīts informācijai",
    "viedoklim": "Nosūtīts viedokļa sniegšanai",
}


def _j(v):
    return json.loads(v) if isinstance(v, str) else (v or {})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _doc(doc_id: int) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        d = await conn.fetchrow(
            """SELECT d.id, d.title, d.registration_number, d.doc_uid, d.doc_did, d.metadata, d.org_id,
                      o.name AS org_name, o.org_did AS org_did
               FROM documents d LEFT JOIN organizations o ON o.id = d.org_id WHERE d.id = $1""", doc_id)
    if not d:
        raise LookupError(f"document {doc_id} not found")
    out = dict(d)
    out["metadata"] = _j(out["metadata"])
    return out


async def _set(doc_id: int, patch: dict) -> dict:
    """Merge into metadata.parsutisana and return it."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        meta = _j(await conn.fetchval("SELECT metadata FROM documents WHERE id = $1", doc_id))
        p = {**(meta.get("parsutisana") or {}), **patch}
        await conn.execute("UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
                           json.dumps({"parsutisana": p}, ensure_ascii=False), doc_id)
    return p


async def _event(doc_id: int, kind: str, details: dict, vc: bool = False) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details) VALUES ($1,$2,NULL,$3,$4)",
            doc_id, kind, vc, json.dumps(details, ensure_ascii=False))


def _doc_id(ctx: dict) -> int:
    v = (ctx.get("input") or {}).get("documentId")
    if v is None:
        raise ValueError("documentId is required")
    return int(v)


# ── forward.request@1 ──────────────────────────────────────────────────────

async def handle_forward_request(ctx: dict) -> dict:
    """Output: { adresats, adresataNosaukums, adresataDid, parsutisanasIemesls, pavadteksts, datnuSkaits }"""
    doc = await _doc(_doc_id(ctx))
    p = doc["metadata"].get("parsutisana") or {}
    if p.get("statuss") not in ("pieprasits", "kluda"):
        raise ValueError(f"Nav gaidoša pārsūtīšanas pieprasījuma (statuss: {p.get('statuss')})")
    await _set(doc["id"], {"statuss": "apstrade", "sessionId": ctx.get("session_id")})
    return {"output": {"adresats": p["adresats"], "adresataNosaukums": p.get("adresataNosaukums"),
                       "adresataDid": p.get("adresataDid"), "parsutisanasIemesls": p.get("iemesls"),
                       "pavadteksts": p.get("pavadteksts") or "", "datnuSkaits": len(p.get("datnes") or [])}}


# ── div.send@1 ─────────────────────────────────────────────────────────────

async def _files(doc: dict, ids: list[int], with_metadata: bool) -> list[dict]:
    from opendms.storage import get_storage
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, file_name, mime_type, storage_key, std_id, is_primary FROM document_files
               WHERE document_id = $1 ORDER BY is_primary DESC, created_at""", doc["id"])
    st = get_storage()
    out = []
    for r in rows:
        if ids and r["id"] not in ids:
            continue
        data = await st.get(r["storage_key"])
        if data is None:
            raise LookupError(f"datne {r['file_name']} nav glabātuvē")
        out.append({"content_id": r["std_id"] or f"datne-{r['id']}", "name": r["file_name"],
                    "mime_type": r["mime_type"] or "application/octet-stream", "data": data})
    if not out:
        raise ValueError("Nav nevienas nosūtāmas datnes")
    prefix = (doc["metadata"].get("standartaPakotne") or {}).get("pakotnesAtslega")
    if with_metadata and prefix:
        xml = await st.get(f"{prefix}/metadati.xml")
        if xml:
            out.append({"content_id": "metadati.xml", "name": "metadati.xml", "mime_type": "application/xml", "data": xml})
    return out


async def handle_div_send(ctx: dict) -> dict:
    """Input: documentId, sutijumaVeids (DMN), pievienotMetadatus (DMN).
    Output: { messageId, serverRefNumber, datnes[], aploksnesSha256 }"""
    import hashlib
    inp = ctx.get("input") or {}
    doc = await _doc(_doc_id(ctx))
    p = doc["metadata"].get("parsutisana") or {}
    cfg = div.config()
    files = await _files(doc, [int(x) for x in p.get("datnes") or []], bool(inp.get("pievienotMetadatus", True)))
    ref = f"{doc['registration_number']}-P{uuid.uuid4().hex[:6].upper()}"
    env = div.build_envelope(
        sender=cfg["eAddress"], recipients=[p["adresats"]], sender_ref=ref,
        title=doc["title"] or "Dokuments", description=p.get("pavadteksts") or REASONS.get(p.get("iemesls"), ""),
        author=f"OpenDMS — {doc['org_name'] or ''}".strip(" —"), kind_code=inp.get("sutijumaVeids") or "PARSUTISANA",
        files=files,
        identity={"DokumentaID": doc.get("doc_uid"), "RegistraDID": doc.get("doc_did"),
                  "SutitajaDID": doc.get("org_did"), "SutitajaRegNr": doc.get("registration_number"),
                  "Iemesls": p.get("iemesls"), "IemeslsTeksts": REASONS.get(p.get("iemesls"))})
    try:
        res = await div.send(env, files)
    except div.DivError as exc:
        await _set(doc["id"], {"statuss": "kluda", "kluda": str(exc), "laiks": _now()})
        raise
    conf = res.get("ServerConfirmation") or {}
    out = {"messageId": res.get("MessageId"), "serverRefNumber": conf.get("ServerRefNumber"),
           "sutitajaAtsauce": ref, "datnes": [f["name"] for f in files],
           "aploksnesSha256": hashlib.sha256(env).hexdigest()}
    await _set(doc["id"], {"statuss": "nosutits", "messageId": out["messageId"], "serverRefNumber": out["serverRefNumber"],
                           "sutitajaAtsauce": ref, "nosutits": conf.get("ServerReceivedTime") or _now(),
                           "nosutitasDatnes": out["datnes"], "sutijumaVeids": inp.get("sutijumaVeids")})
    return {"output": out}


# ── forward.record@1 ───────────────────────────────────────────────────────

async def handle_forward_record(ctx: dict) -> dict:
    """DVS event + register lifecycle DocumentSent to the recipient's DID.
    Output: { registraNotikums, adresataDid }"""
    from opendms import sdk_client
    from opendms.config import get_settings
    doc = await _doc(_doc_id(ctx))
    p = doc["metadata"].get("parsutisana") or {}
    vc = False
    err = None
    if get_settings().sdk_enabled and doc.get("doc_did") and p.get("adresataDid"):
        res = await sdk_client.send_document(doc["doc_did"], recipient_did=p["adresataDid"], method="e-adrese (DIV)",
                                             trace_id=ctx.get("session_id"))
        vc = bool(res) and (res.get("_meta", {}).get("status_code", 200) in (200, 201))
        if not vc:
            err = (res or {}).get("detail") or "reģistrs nepieņēma notikumu"
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE documents SET status = 'sent' WHERE id = $1", doc["id"])
    await _event(doc["id"], "DocumentSent", {"kanals": "e-adrese (DIV)", "adresats": p.get("adresats"),
                                             "adresataNosaukums": p.get("adresataNosaukums"),
                                             "messageId": p.get("messageId"), "serverRefNumber": p.get("serverRefNumber"),
                                             "iemesls": p.get("iemesls"), "registraKluda": err}, vc=vc)
    await _set(doc["id"], {"registraNotikums": vc})
    return {"output": {"registraNotikums": vc, "adresataDid": p.get("adresataDid"), "registraKluda": err}}


# ── submitter.notify@1 ─────────────────────────────────────────────────────

async def handle_submitter_notify(ctx: dict) -> dict:
    """Inform the submitter (Iesniegumu likums: par pārsūtīšanu informē iesniedzēju).
    Uses the e-mail input channel's mailbox. Output: { informets, iemesls }"""
    from opendms.intake import config as icfg
    from opendms.intake.email_channel import sender_for
    doc = await _doc(_doc_id(ctx))
    p = doc["metadata"].get("parsutisana") or {}
    to = ((doc["metadata"].get("sender") or {}).get("email") or "").strip()
    if not to:
        return {"output": {"informets": False, "iemesls": "iesniedzējam nav e-pasta adreses"}}
    mail = next((c for c in icfg.channels("epasts") if icfg.password(c)), None)
    if not mail:
        return {"output": {"informets": False, "iemesls": "nav konfigurēta e-pasta kanāla"}}
    body = "\n".join([
        "Labdien!", "",
        f"Jūsu iesniegums (reģistrācijas Nr. {doc['registration_number']}) "
        f"{'pēc piekritības ' if p.get('iemesls') == 'piekritiba' else ''}pārsūtīts iestādei: {p.get('adresataNosaukums') or p.get('adresats')}.",
        f"Dokumenta identifikators: {doc.get('doc_uid') or '—'}",
        "", "Turpmāk iesniegumu izskata minētā iestāde.", "", "Šī ir automātiska ziņa.",
    ])
    await sender_for(mail)(to, f"Iesniegums Nr. {doc['registration_number']} pārsūtīts", body, None)
    await _set(doc["id"], {"iesniedzejsInformets": _now()})
    await _event(doc["id"], "SubmitterNotified", {"par": "parsutisana", "adresats": p.get("adresataNosaukums")})
    return {"output": {"informets": True}}


# ── sūtītāja paziņojumi no DIV ─────────────────────────────────────────────

async def poll_notifications() -> int:
    """Delivered / Confirmed from DIV -> metadata.parsutisana.statuss and events."""
    items = await div.notifications()
    if not items:
        return 0
    pool = await get_pool()
    done = []
    for n in items:
        async with pool.acquire() as conn:
            doc_id = await conn.fetchval(
                "SELECT id FROM documents WHERE metadata->'parsutisana'->>'messageId' = $1", n["MessageId"])
        if doc_id:
            status = {"Delivered": "sanemts", "Confirmed": "apstiprinats"}.get(n["Kind"], n["Kind"])
            await _set(doc_id, {"statuss": status, f"{status}Laiks": n.get("Time")})
            await _event(doc_id, "DeliveryNotification", {"kanals": "e-adrese (DIV)", "veids": n["Kind"],
                                                          "adresats": n.get("RecipientE-Address"), "laiks": n.get("Time")})
        done.append(n["Id"])
    await div.ack(done)
    return len(done)


async def request(doc_id: int, *, adresats: str, iemesls: str, pavadteksts: str, datnes: list[int],
                  user: dict) -> dict:
    """GUI request -> metadata.parsutisana, then the forwarding process is started by the caller."""
    if iemesls not in REASONS:
        raise ValueError("nezināms iemesls")
    match = next((a for a in await div.search(adresats) if a["E-Address"] == adresats), None)
    if not match:
        raise ValueError(f"E-adrese {adresats} nav adrešu katalogā")
    cfg = div.config()
    if adresats == cfg["eAddress"]:
        raise ValueError("Nevar pārsūtīt pašai iestādei")
    doc = await _doc(doc_id)
    cur = doc["metadata"].get("parsutisana") or {}
    if cur.get("statuss") in ("pieprasits", "apstrade"):
        raise ValueError("Pārsūtīšana jau notiek")
    hist = list(cur.get("vesture") or [])
    if cur.get("messageId"):
        hist.append({k: cur.get(k) for k in ("adresats", "adresataNosaukums", "iemesls", "messageId", "statuss", "nosutits")})
    p = {"statuss": "pieprasits", "adresats": adresats, "adresataNosaukums": match.get("Name"),
         "adresataDid": match.get("Did"), "iemesls": iemesls, "pavadteksts": (pavadteksts or "")[:2000],
         "datnes": datnes, "pieprasija": user.get("email"), "pieprasits": _now(), "vesture": hist}
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
                           json.dumps({"parsutisana": p}, ensure_ascii=False), doc_id)
    await _event(doc_id, "ForwardingRequested", {"adresats": match.get("Name"), "iemesls": iemesls,
                                                 "pieprasija": user.get("email")})
    return p
