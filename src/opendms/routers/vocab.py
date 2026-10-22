"""GET /api/vardnicas — status names and number format from ProcessGit (opendms.vocab)."""

from fastapi import APIRouter, Depends

from opendms import vocab
from opendms.middleware.auth import get_current_user, require_role

router = APIRouter(prefix="/api/vardnicas", tags=["Vārdnīcas"])


@router.get("")
async def vardnicas(user=Depends(get_current_user)):
    v = await vocab.load()
    return {"statusi": v["statusi"], "numurs": v.get("numurs"), "avots": v.get("avots"), "kluda": v.get("kluda")}


@router.post("/atjaunot")
async def reload(user=Depends(require_role("admin", "superadmin"))):
    """Read ProcessGit again now (otherwise every five minutes)."""
    v = await vocab.load(force=True)
    return {"statusi": v["statusi"], "numurs": v.get("numurs"), "avots": v.get("avots"), "kluda": v.get("kluda")}
