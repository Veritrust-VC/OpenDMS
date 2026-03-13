"""SDK-backed intelligence proxy endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from opendms import sdk_client
from opendms.middleware.auth import get_current_user
from opendms.database import get_pool

router = APIRouter(prefix="/api/intelligence", tags=["Intelligence"])


class BriefingRequest(BaseModel):
    context: dict = {}


@router.get("/topics")
async def topics(user=Depends(get_current_user)):
    result = await sdk_client.get_topic_trends(actor=user)
    if not result:
        raise HTTPException(502, "Topic trends unavailable")
    return result


@router.get("/similar/{doc_id}")
async def similar(doc_id: str, user=Depends(get_current_user)):
    result = await sdk_client.get_similar_documents(doc_id, actor=user)
    if not result:
        raise HTTPException(502, "Similar documents unavailable")
    return result


@router.get("/warnings")
async def warnings(user=Depends(get_current_user)):
    result = await sdk_client.get_warnings(actor=user)
    if not result:
        raise HTTPException(502, "Warnings unavailable")
    return result


@router.post("/briefing")
async def briefing(req: BriefingRequest, user=Depends(get_current_user)):
    result = await sdk_client.generate_briefing(req.context, actor=user)
    if result:
        return result

    # SDK unavailable — fall back to local AI briefing from recent document activity
    from opendms.ai import generate_local_briefing, is_configured
    if not is_configured():
        raise HTTPException(
            503,
            "Briefing unavailable — SDK not connected and AI not configured "
            "(set OPENDMS_LLM_API_KEY to enable local AI fallback)",
        )

    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT d.title, d.status, d.created_at,
                      d.semantic_summary->>'primaryTopic' AS topic
               FROM documents d
               ORDER BY d.created_at DESC
               LIMIT 20"""
        )
    recent_docs = [dict(r) for r in rows]

    result = await generate_local_briefing(recent_docs)
    if not result:
        raise HTTPException(502, "Briefing unavailable — SDK not connected and AI generation failed")
    return result
