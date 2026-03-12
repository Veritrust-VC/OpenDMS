"""SDK-backed intelligence proxy endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from opendms import sdk_client
from opendms.middleware.auth import get_current_user

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
    if not result:
        raise HTTPException(502, "Briefing unavailable")
    return result
