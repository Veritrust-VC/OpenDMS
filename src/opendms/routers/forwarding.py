"""Pārsūtīšana citai iestādei e-adresē (DIV) — DVS saskarnes API.

Saskarne izveido pieprasījumu; to izpilda process ar trigeri 'document.forwarding'
(vdvc/dokumenta-parsutisana). Ja process nav uzstādīts, pieprasījums netiek izpildīts.
"""

from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from opendms import div
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user, require_role
from opendms.org_context import get_default_org_required

router = APIRouter(tags=["Pārsūtīšana"])


@router.get("/api/div/statuss")
async def div_status(user=Depends(get_current_user)):
    c = div.config()
    return {"konfigurets": div.configured(), "eAdrese": c["eAddress"] or None}


@router.get("/api/div/adreses")
async def addresses(q: str = "", user=Depends(get_current_user)):
    try:
        res = await div.search(q)
    except div.DivError as exc:
        raise HTTPException(503, str(exc))
    me = div.config()["eAddress"]
    return {"adreses": [a for a in res if a["E-Address"] != me]}


class ForwardIn(BaseModel):
    adresats: str
    iemesls: str = "piekritiba"
    pavadteksts: str = ""
    datnes: list[int] = []


@router.post("/api/documents/{doc_id}/parsutit")
async def forward(doc_id: int, req: ForwardIn, user=Depends(require_role("admin", "superadmin", "operator"))):
    from opendms.div import forwarding
    from opendms.uapf import on_document_event
    from opendms.uapf.triggers import find_matching_triggers

    org = await get_default_org_required()
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT id, org_id, metadata FROM documents WHERE id = $1 AND org_id = $2", doc_id, org["id"])
    if not doc:
        raise HTTPException(404, "Dokuments nav atrasts")
    if not div.configured():
        raise HTTPException(503, "E-adrese (DIV) šai DVS nav konfigurēta")
    if not await find_matching_triggers("document.forwarding", {"id": doc_id, "org_id": doc["org_id"]}):
        raise HTTPException(409, "Nav uzstādīts pārsūtīšanas process (trigeris 'document.forwarding')")
    try:
        p = await forwarding.request(doc_id, adresats=req.adresats, iemesls=req.iemesls,
                                     pavadteksts=req.pavadteksts, datnes=req.datnes, user=user)
    except (ValueError, div.DivError) as exc:
        raise HTTPException(422, str(exc))
    await on_document_event("document.forwarding", doc_id)
    return {"parsutisana": p}


@router.get("/api/documents/{doc_id}/parsutisana")
async def forward_status(doc_id: int, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        meta = await conn.fetchval("SELECT metadata FROM documents WHERE id = $1", doc_id)
    meta = json.loads(meta) if isinstance(meta, str) else (meta or {})
    return {"parsutisana": meta.get("parsutisana"), "sanemts": (meta.get("ievade") or {}).get("div")}
