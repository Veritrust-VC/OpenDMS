"""Mans darbs — UAPF process steps waiting for a person.

GET  /api/tasks                       open steps, earliest deadline first
GET  /api/tasks/{doc_id}              the step waiting on one document
POST /api/tasks/{doc_id}/complete     the person's decision; the process continues

POC 1: every signed-in user may act in every role (see opendms.tasks).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from opendms.middleware.auth import get_current_user
from opendms import tasks

router = APIRouter(prefix="/api/tasks", tags=["Tasks"])


class CompleteIn(BaseModel):
    decision: str
    comment: Optional[str] = None
    changes: Optional[dict] = None


@router.get("")
async def my_tasks(limit: int = Query(100, ge=1, le=500), overdue_only: bool = False,
                   user=Depends(get_current_user)):
    items = await tasks.list_tasks(limit=limit, overdue_only=overdue_only)
    return {"count": len(items), "overdue": sum(1 for t in items if t["overdue"]), "items": items}


@router.get("/{doc_id}")
async def one_task(doc_id: int, user=Depends(get_current_user)):
    t = await tasks.get_task(doc_id)
    if not t:
        raise HTTPException(404, "No process step is waiting on this document")
    return t


@router.post("/{doc_id}/complete")
async def complete_task(doc_id: int, body: CompleteIn, user=Depends(get_current_user)):
    try:
        return await tasks.complete(doc_id, body.decision, user=user, comment=body.comment,
                                    changes=body.changes, via="dvs")
    except tasks.TaskError as e:
        raise HTTPException(e.status, e.message)
