from fastapi import HTTPException
from opendms.database import get_pool


async def get_default_org():
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM organizations WHERE is_default = TRUE ORDER BY id LIMIT 1"
        )
    return dict(row) if row else None


async def get_default_org_required():
    org = await get_default_org()
    if not org:
        raise HTTPException(409, "No default organization selected")
    return org
