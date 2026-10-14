"""Storage explorer: read-only browsing of document package folders."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from typing import Optional

from pydantic import BaseModel

from opendms.middleware.auth import get_current_user, require_role
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


# ── Datu glabātuve: settings and connection test (admins) ─────────────────

class S3In(BaseModel):
    endpoint: str
    bucket: str
    region: str = "us-east-1"
    accessKey: str
    secretKey: Optional[str] = None   # empty = keep the stored one


@router.get("/settings")
async def storage_settings(user=Depends(require_role("admin", "superadmin"))):
    from opendms.storage import settings as st
    return {"aktiva": await st.active(), "s3": await st.s3_config()}


@router.put("/settings/s3")
async def save_s3(body: S3In, user=Depends(require_role("admin", "superadmin"))):
    from opendms.storage import settings as st
    cur = await st.s3_config(with_secret=True)
    if not (body.secretKey or cur.get("secretKey")):
        raise HTTPException(422, "Norādiet slepeno atslēgu")
    await st.save_s3(body.endpoint, body.bucket, body.region, body.accessKey, body.secretKey,
                     user.get("email") or str(user.get("id")))
    return {"s3": await st.s3_config()}


@router.post("/settings/s3/test")
async def test_s3(body: Optional[S3In] = None, user=Depends(require_role("admin", "superadmin"))):
    """Test the given settings (unsaved form) or, without a body, the saved ones."""
    from opendms.storage import settings as st
    cfg = await st.s3_config(with_secret=True)
    if body:
        cfg = {**cfg, "endpoint": body.endpoint, "bucket": body.bucket, "region": body.region,
               "accessKey": body.accessKey, **({"secretKey": body.secretKey} if body.secretKey else {})}
    res = await st.test(cfg)
    if not body:
        await st.record_test(res)
    return res
