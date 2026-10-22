"""Namejs intake endpoints — run a sync or import one document by hand."""

from fastapi import APIRouter, Depends

from opendms import namejs_intake
from opendms.middleware.auth import require_role

router = APIRouter(prefix="/api/integrations/namejs", tags=["Namejs intake"])
_ADMIN = require_role("admin", "superadmin")


@router.post("/sync", summary="Poll the Namejs status feed once and import new documents")
async def sync_now(user=Depends(_ADMIN)):
    return await namejs_intake.sync(actor=user)


@router.post("/import/{namejs_document_id}", summary="Import one Namejs document with its files")
async def import_one(namejs_document_id: int, user=Depends(_ADMIN)):
    return await namejs_intake.import_document(namejs_document_id, actor=user)
