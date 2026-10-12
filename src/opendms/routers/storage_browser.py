"""Storage explorer: read-only browsing of document package folders."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from opendms.middleware.auth import get_current_user
from opendms.org_context import get_default_org_required
from opendms.standard import service

router = APIRouter(prefix="/api/storage", tags=["Storage"])


@router.get("/browse")
async def browse(path: str = "", user=Depends(get_current_user)):
    """One level of the package storage. Empty path = document folders."""
    org = await get_default_org_required()
    try:
        return await service.browse_storage(org["id"], path)
    except LookupError as e:
        raise HTTPException(404, str(e))


@router.get("/file")
async def file(path: str, download: bool = False, user=Depends(get_current_user)):
    """Contents of one file under a document folder."""
    org = await get_default_org_required()
    try:
        data, media = await service.read_storage_file(org["id"], path)
    except LookupError as e:
        raise HTTPException(404, str(e))
    disp = "attachment" if download else "inline"
    name = path.rstrip("/").rsplit("/", 1)[-1]
    return Response(content=data, media_type=media, headers={
        "Content-Disposition": f"{disp}; filename*=UTF-8''{quote(name)}",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox"})
