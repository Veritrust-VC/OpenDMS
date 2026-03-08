"""Authentication endpoints."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from opendms.database import get_pool
from opendms.middleware.auth import hash_password, verify_password, create_token

router = APIRouter(prefix="/api/auth", tags=["Auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


@router.post("/login")
async def login(req: LoginRequest):
    pool = await get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, email, full_name, role, org_id, password_hash, is_active FROM users WHERE email = $1",
            req.email,
        )
    if not user or not user["is_active"]:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Invalid credentials")

    token = create_token(user["id"], user["email"], user["role"], user["org_id"])
    return {
        "token": token,
        "user": {"id": user["id"], "email": user["email"], "full_name": user["full_name"],
                 "role": user["role"], "org_id": user["org_id"]},
    }
