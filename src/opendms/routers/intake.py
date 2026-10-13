"""Inputs (ievade) — channel status for admins, and the public web form.

Channels are configured in the YAML file (opendms/intake/config.py); there is
no configuration UI. Admin endpoints are read-only plus "poll now".
"""

from __future__ import annotations

import json
import secrets
import time
from collections import defaultdict, deque
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from opendms.database import get_pool
from opendms.intake import config as cfg
from opendms.intake import service
from opendms.middleware.auth import require_role

router = APIRouter(prefix="/api/ievade", tags=["Ievade"])

_admin = require_role("admin", "superadmin", "operator")


@router.get("/kanali")
async def list_channels(user=Depends(_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        counts = {r["channel_id"]: dict(r) for r in await conn.fetch(
            """SELECT channel_id, COUNT(*) FILTER (WHERE status='registrets') AS registreti,
                      COUNT(*) FILTER (WHERE status='noraidits') AS noraiditi,
                      COUNT(*) FILTER (WHERE ack_status='gaida') AS gaida_apstiprinajumu,
                      MAX(received_at) AS pedejais
               FROM intake_items GROUP BY channel_id""")}
    data = cfg.load()
    return {"konfiguracija": cfg.path(), "kluda": data.get("_kluda"), "nav": data.get("_nav"),
            "registrs": cfg.register_public_url() or None,
            "kanali": [{**cfg.public_view(c), "skaits": counts.get(c.get("id"), {})}
                       for c in cfg.channels(enabled_only=False)] + [
                       {"id": "gui", "veids": "manuala-augsupielade", "ieslegts": True,
                        "nosaukums": "Manuāla augšupielāde DVS saskarnē"}]}


@router.get("/ieraksti")
async def list_items(limit: int = 50, user=Depends(_admin)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT i.id, i.channel_id, i.channel_kind, i.sender_address, i.subject, i.document_id, i.status,
                      i.detail, i.ack_status, i.ack_sent_at, i.ack_error, i.received_at,
                      d.registration_number, d.doc_uid
               FROM intake_items i LEFT JOIN documents d ON d.id = i.document_id
               ORDER BY i.id DESC LIMIT $1""", max(1, min(limit, 500)))
    out = []
    for r in rows:
        x = dict(r)
        x["detail"] = json.loads(x["detail"]) if isinstance(x["detail"], str) else x["detail"]
        out.append(x)
    return {"items": out}


@router.post("/kanali/{cid}/parbaudit")
async def poll_now(cid: str, user=Depends(require_role("admin", "superadmin"))):
    ch = cfg.channel(cid)
    if not ch:
        raise HTTPException(404, "kanāls nav konfigurēts")
    if ch.get("veids") != "epasts":
        raise HTTPException(400, "pārbaudīt var tikai e-pasta kanālu")
    from opendms.intake.email_channel import poll_once
    return await poll_once(ch)


# ── Public web form ────────────────────────────────────────────────────────

_hits: dict[str, deque] = defaultdict(deque)
RATE = (5, 600)  # 5 submissions per 10 minutes per address


def _rate_ok(ip: str) -> bool:
    now = time.monotonic()
    q = _hits[ip]
    while q and now - q[0] > RATE[1]:
        q.popleft()
    if len(q) >= RATE[0]:
        return False
    q.append(now)
    return True


def _form_channel(cid: str) -> dict:
    ch = cfg.channel(cid)
    if not ch or ch.get("veids") != "tiessaistes-forma" or not ch.get("ieslegts", True):
        raise HTTPException(404, "forma nav pieejama")
    return ch


def _shema(ch: dict) -> dict:
    sh = ch.get("shema") or {}
    if not sh.get("xsd"):
        raise HTTPException(503, "Formai nav norādīta datu shēma")
    return sh


@router.get("/forma/{cid}")
async def form_info(cid: str):
    """Form description: what the schema allows, plus the classifier choices."""
    from opendms.intake import structured
    from opendms.org_context import get_default_org
    ch = _form_channel(cid)
    sh = _shema(ch)
    org = await get_default_org() or {}
    jomas, kodi = [], []
    try:
        klas = await structured.classifier(sh)
    except Exception:
        klas = None
    if klas:
        seen = {}
        for c in klas["kodi"]:
            seen.setdefault(c["joma"], c["jomasNosaukums"])
            if c["izvelams"]:
                kodi.append({"kods": c["kods"], "joma": c["joma"], "nosaukums": c["nosaukums"], "cels": c["cels"]})
        jomas = [{"kods": k, "nosaukums": n} for k, n in seen.items()]
    return {"id": ch["id"], "nosaukums": ch.get("nosaukums") or "Iesniegums", "iestade": org.get("name"),
            "maxMb": ch.get("max_mb", 20), "apraksts": ch.get("apraksts"),
            "shema": sh.get("xsd"), "noteikumi": sh.get("noteikumi"),
            "klasifikatorsVersija": (klas or {}).get("versija"), "jomas": jomas, "kodi": kodi}


@router.post("/forma/{cid}")
async def form_submit(cid: str, request: Request, iesniegums: str = Form(...), web: str = Form(""),
                      apraksti: str = Form("[]"), datnes: Optional[list[UploadFile]] = File(None)):
    """Field values (JSON, schema names) + evidence files -> schema-valid XML -> DVS document.

    Nothing is interpreted: the XML is written from the fields, validated with the
    schema, the rules and the classifier, and stored as the document itself."""
    from opendms.intake import structured
    ch = _form_channel(cid)
    sh = _shema(ch)
    if web:  # honeypot field, hidden from people
        raise HTTPException(400, "neizdevās")
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    if not _rate_ok(ip):
        raise HTTPException(429, "Pārāk daudz iesniegumu. Mēģiniet vēlāk.")
    try:
        fields = json.loads(iesniegums)
        notes = json.loads(apraksti or "[]")
        assert isinstance(fields, dict) and isinstance(notes, list)
    except Exception:
        raise HTTPException(422, {"kludas": ["Nederīgi veidlapas dati."]})
    limit = int(float(ch.get("max_mb", 20)) * 1024 * 1024)
    atts, total = [], 0
    for idx, f in enumerate(datnes or []):
        if not f or not f.filename:
            continue
        data = await f.read()
        total += len(data)
        if total > limit:
            raise HTTPException(413, {"kludas": [f"Datnes kopā pārsniedz {ch.get('max_mb', 20)} MB."]})
        atts.append({"file_name": f.filename, "mime_type": f.content_type or "application/octet-stream", "data": data,
                     "apraksts": str(notes[idx])[:200] if idx < len(notes) and notes[idx] else None})
    if len(atts) > 10:
        raise HTTPException(422, {"kludas": ["Ne vairāk kā 10 pielikumi."]})

    xml = structured.build(fields, kanals="Portals", attachments=atts)
    try:
        info = await structured.validate(xml, sh, await structured.classifier(sh))
    except structured.InvalidSubmission as exc:
        raise HTTPException(422, {"kludas": exc.errors})

    token = secrets.token_urlsafe(16)
    label = info["joma"] + (f" {info['kods']}" if info.get("kods") else "")
    r = await service.ingest(
        ch, external_ref=token, sender={k: v for k, v in info["sender"].items() if v},
        subject=f"Iesniegums ({label})", body="",
        attachments=[{k: a[k] for k in ("file_name", "mime_type", "data")} for a in atts],
        primary={"file_name": "iesniegums.xml", "mime_type": "application/xml", "data": xml,
                 "avots": f"strukturēta veidlapa ({sh.get('xsd')})"},
        extra={"strukturets": {k: v for k, v in info.items() if k != "sender"}})
    return {"registracijasNr": r.get("registrationNumber"), "statusaKods": token, "datnes": r.get("datnes"),
            "edoc": [{"konteiners": e.get("konteiners"), "paraksti": e.get("parakstuSkaits"),
                      "integritate": e.get("integritateVisiem")} for e in r.get("edoc") or []]}


@router.get("/statuss/{token}")
async def form_status(token: str):
    """Status for the submitter of a web form (token from the submission). No personal data."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT document_id FROM intake_items WHERE external_ref = $1 AND channel_kind = 'tiessaistes-forma'", token)
    if not row or not row["document_id"]:
        raise HTTPException(404, "nav atrasts")
    st = await service.status(row["document_id"])
    return {k: st.get(k) for k in ("registracijasNr", "dokumentaId", "iestade", "izsekosanasKods",
                                   "izsekosanasSaite", "nodotsRegistram")}
