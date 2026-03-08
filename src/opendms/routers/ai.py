"""AI Intelligence endpoints for OpenDMS."""

import json
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user
from opendms.ai import (
    suggest_classification, suggest_routing, summarize_content,
    is_configured as ai_configured,
)

router = APIRouter(prefix="/api/ai", tags=["AI Intelligence"])


@router.get("/health")
async def ai_health():
    from opendms.ai import PROVIDER, _cfg
    cfg = _cfg()
    return {
        "ai_available": ai_configured(),
        "provider": cfg["provider"],
        "model": cfg["model"],
        "capabilities": ["classification_suggestion", "routing_recommendation", "content_summarization"],
    }


class ClassifyRequest(BaseModel):
    title: str
    content_summary: Optional[str] = None


@router.post("/classify")
async def classify_document(req: ClassifyRequest, user=Depends(get_current_user)):
    """
    AI-powered classification suggestion.
    Analyzes document title and content to recommend the best classification code.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        cls_rows = await conn.fetch(
            "SELECT code, name, description FROM classifications WHERE is_active = TRUE ORDER BY sort_order LIMIT 100"
        )
    classifications = [dict(r) for r in cls_rows]

    result = await suggest_classification(req.title, req.content_summary or "", classifications)
    if not result:
        return {"error": "AI not configured or unavailable", "ai_available": ai_configured()}
    return result


class RouteRequest(BaseModel):
    title: str
    classification: Optional[str] = None
    sender: Optional[str] = None


@router.post("/route")
async def route_document(req: RouteRequest, user=Depends(get_current_user)):
    """
    AI-powered routing recommendation.
    Suggests which department/person should handle the document.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        user_rows = await conn.fetch(
            "SELECT full_name, department, role FROM users WHERE is_active = TRUE AND role IN ('operator','admin') LIMIT 50"
        )
    users = [dict(r) for r in user_rows]

    result = await suggest_routing(req.title, req.classification or "", req.sender or "", users)
    if not result:
        return {"error": "AI not configured or unavailable", "ai_available": ai_configured()}
    return result


class SummarizeRequest(BaseModel):
    text: str
    max_length: Optional[int] = 200


@router.post("/summarize")
async def summarize(req: SummarizeRequest, user=Depends(get_current_user)):
    """
    AI-powered content summarization.
    Generates a brief summary, key topics, and detects language.
    """
    result = await summarize_content(req.text, req.max_length or 200)
    if not result:
        return {"error": "AI not configured or unavailable", "ai_available": ai_configured()}
    return result


@router.post("/analyze/{doc_id}")
async def analyze_document(doc_id: int, user=Depends(get_current_user)):
    """
    Full AI analysis of a document: classification, routing, and anomaly assessment.
    Combines multiple AI capabilities into a single analysis report.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            """SELECT d.*, c.name as classification_name, c.code as classification_code,
                      o.name as org_name
               FROM documents d
               LEFT JOIN classifications c ON d.classification_id = c.id
               LEFT JOIN organizations o ON d.org_id = o.id
               WHERE d.id = $1""", doc_id)
        if not doc:
            return {"error": "Document not found"}

        events = await conn.fetch(
            "SELECT event_type, actor_id, vc_submitted, details, created_at FROM document_events WHERE document_id = $1 ORDER BY created_at",
            doc_id)

        cls_rows = await conn.fetch("SELECT code, name, description FROM classifications WHERE is_active = TRUE LIMIT 100")
        user_rows = await conn.fetch("SELECT full_name, department, role FROM users WHERE is_active = TRUE AND role IN ('operator','admin') LIMIT 50")

    report = {"document_id": doc_id, "title": doc["title"], "current_status": doc["status"]}

    # Classification suggestion
    cls_result = await suggest_classification(
        doc["title"], doc["content_summary"] or "", [dict(r) for r in cls_rows])
    report["classification"] = cls_result

    # Routing suggestion
    route_result = await suggest_routing(
        doc["title"], doc.get("classification_name") or "", doc.get("org_name") or "",
        [dict(r) for r in user_rows])
    report["routing"] = route_result

    # Event analysis
    event_types = [e["event_type"] for e in events]
    vc_count = sum(1 for e in events if e["vc_submitted"])
    report["lifecycle"] = {
        "event_count": len(events),
        "vc_submitted_count": vc_count,
        "events": event_types,
        "has_did": bool(doc["doc_did"]),
    }

    report["ai_available"] = ai_configured()
    return report
