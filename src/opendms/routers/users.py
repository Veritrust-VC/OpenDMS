"""User management endpoints."""

import json
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user, require_role, hash_password

router = APIRouter(prefix="/api/users", tags=["Users"])


class UserCreate(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "operator"
    org_id: Optional[int] = None
    department: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    org_id: Optional[int] = None
    department: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("")
async def list_users(
    org_id: Optional[int] = None, role: Optional[str] = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    user=Depends(require_role("superadmin", "admin")),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        wheres, params, idx = [], [], 1
        if org_id:
            wheres.append(f"u.org_id = ${idx}"); params.append(org_id); idx += 1
        if role:
            wheres.append(f"u.role = ${idx}"); params.append(role); idx += 1
        where = " AND ".join(wheres) if wheres else "TRUE"
        total = await conn.fetchval(f"SELECT COUNT(*) FROM users u WHERE {where}", *params)
        rows = await conn.fetch(
            f"""SELECT u.id, u.email, u.full_name, u.role, u.org_id, u.department, u.is_active,
                       u.created_at, o.name as org_name
                FROM users u LEFT JOIN organizations o ON u.org_id = o.id
                WHERE {where} ORDER BY u.created_at DESC LIMIT ${idx} OFFSET ${idx+1}""",
            *params, page_size, (page - 1) * page_size,
        )
    return {"items": [dict(r) for r in rows], "total": total, "page": page}


@router.post("", status_code=201)
async def create_user(req: UserCreate, user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM users WHERE email = $1", req.email)
        if existing:
            raise HTTPException(409, "Email already exists")
        row = await conn.fetchrow(
            """INSERT INTO users (email, password_hash, full_name, role, org_id, department)
               VALUES ($1, $2, $3, $4, $5, $6) RETURNING id, email, full_name, role, org_id""",
            req.email, hash_password(req.password), req.full_name, req.role, req.org_id, req.department,
        )
    return dict(row)


@router.get("/{user_id}")
async def get_user(user_id: int, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT u.id, u.email, u.full_name, u.role, u.org_id, u.department, u.is_active,
                      u.created_at, o.name as org_name
               FROM users u LEFT JOIN organizations o ON u.org_id = o.id WHERE u.id = $1""", user_id)
    if not row: raise HTTPException(404, "User not found")
    return dict(row)


@router.patch("/{user_id}")
async def update_user(user_id: int, req: UserUpdate, user=Depends(require_role("superadmin", "admin"))):
    pool = await get_pool()
    async with pool.acquire() as conn:
        sets, params, idx = [], [], 1
        for field in ["full_name", "role", "org_id", "department", "is_active"]:
            val = getattr(req, field, None)
            if val is not None:
                sets.append(f"{field} = ${idx}"); params.append(val); idx += 1
        if not sets: raise HTTPException(400, "No fields to update")
        params.append(user_id)
        row = await conn.fetchrow(
            f"UPDATE users SET {', '.join(sets)} WHERE id = ${idx} RETURNING id, email, full_name, role, org_id, is_active",
            *params)
    if not row: raise HTTPException(404, "User not found")
    return dict(row)


@router.get("/me/profile")
async def my_profile(user=Depends(get_current_user)):
    return user
