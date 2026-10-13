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


@router.get("/forma/{cid}")
async def form_info(cid: str):
    ch = _form_channel(cid)
    from opendms.org_context import get_default_org
    org = await get_default_org() or {}
    return {"id": ch["id"], "nosaukums": ch.get("nosaukums") or "Iesniegums", "iestade": org.get("name"),
            "maxMb": ch.get("max_mb", 20), "apraksts": ch.get("apraksts")}


@router.post("/forma/{cid}")
async def form_submit(cid: str, request: Request,
                      vards: str = Form(...), epasts: str = Form(""), temats: str = Form(""),
                      teksts: str = Form(""), web: str = Form(""),
                      datnes: Optional[list[UploadFile]] = File(None)):
    ch = _form_channel(cid)
    if web:  # honeypot field, hidden from people
        raise HTTPException(400, "neizdevās")
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    if not _rate_ok(ip):
        raise HTTPException(429, "Pārāk daudz iesniegumu. Mēģiniet vēlāk.")
    vards = vards.strip()[:200]
    epasts = epasts.strip()[:200]
    if not vards:
        raise HTTPException(422, "Norādiet vārdu un uzvārdu vai nosaukumu")
    if epasts and ("@" not in epasts or " " in epasts):
        raise HTTPException(422, "Nederīga e-pasta adrese")
    limit = int(float(ch.get("max_mb", 20)) * 1024 * 1024)
    atts, total = [], 0
    for f in datnes or []:
        if not f or not f.filename:
            continue
        data = await f.read()
        total += len(data)
        if total > limit:
            raise HTTPException(413, f"Datnes kopā pārsniedz {ch.get('max_mb', 20)} MB")
        atts.append({"file_name": f.filename, "mime_type": f.content_type or "application/octet-stream", "data": data})
    if not atts and len(teksts.strip()) < 20:
        raise HTTPException(422, "Pievienojiet datni vai uzrakstiet iesnieguma tekstu")

    token = secrets.token_urlsafe(16)
    r = await service.ingest(ch, external_ref=token,
                             sender={"name": vards, "email": epasts.lower() or None, "type": "FiziskaPersona"},
                             subject=temats.strip()[:300], body=teksts[:100000], attachments=atts)
    return {"registracijasNr": r.get("registrationNumber"), "statusaKods": token,
            "datnes": r.get("datnes"), "edoc": [{"konteiners": e.get("konteiners"), "paraksti": e.get("parakstuSkaits"),
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
