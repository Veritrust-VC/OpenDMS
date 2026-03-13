"""AI Instruction Management API — CRUD for system prompts, guardrails, schemas."""

import json
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from opendms.database import get_pool
from opendms.middleware.auth import require_role

router = APIRouter(prefix="/api/ai-instructions", tags=["AI Instructions"])


class InstructionUpdate(BaseModel):
    content: str
    change_reason: Optional[str] = None


class InstructionCreate(BaseModel):
    instruction_key: str
    display_name: str
    description: Optional[str] = None
    category: str = "prompt"
    content: str
    content_type: str = "text"


@router.get("")
async def list_instructions(
    category: Optional[str] = None,
    user=Depends(require_role("admin", "superadmin")),
):
    """List all AI instructions. Admin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if category:
            rows = await conn.fetch(
                """SELECT id, instruction_key, display_name, description,
                          category, content_type, is_active, version,
                          updated_at
                   FROM ai_instructions WHERE category = $1
                   ORDER BY category, instruction_key""",
                category,
            )
        else:
            rows = await conn.fetch(
                """SELECT id, instruction_key, display_name, description,
                          category, content_type, is_active, version,
                          updated_at
                   FROM ai_instructions ORDER BY category, instruction_key"""
            )
    return {"items": [dict(r) for r in rows]}


@router.get("/{instruction_key}")
async def get_instruction(
    instruction_key: str,
    user=Depends(require_role("admin", "superadmin")),
):
    """Get a single instruction with full content."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM ai_instructions WHERE instruction_key = $1",
            instruction_key,
        )
    if not row:
        raise HTTPException(404, "Instruction not found")
    return dict(row)


@router.post("")
async def create_instruction(
    req: InstructionCreate,
    user=Depends(require_role("superadmin")),
):
    """Create a new instruction. Superadmin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                """INSERT INTO ai_instructions
                   (instruction_key, display_name, description, category, content, content_type,
                    created_by, updated_by)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $7)
                   RETURNING id, instruction_key, version""",
                req.instruction_key,
                req.display_name,
                req.description,
                req.category,
                req.content,
                req.content_type,
                user["id"],
            )
        except Exception as exc:
            raise HTTPException(400, f"Unable to create instruction: {exc}") from exc
    return {"status": "created", **dict(row)}


@router.put("/{instruction_key}")
async def update_instruction(
    instruction_key: str,
    req: InstructionUpdate,
    user=Depends(require_role("admin", "superadmin")),
):
    """Update an instruction's content. Creates a history entry."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id, version, content FROM ai_instructions WHERE instruction_key = $1",
            instruction_key,
        )
        if not existing:
            raise HTTPException(404, "Instruction not found")

        new_version = existing["version"] + 1

        await conn.execute(
            """INSERT INTO ai_instructions_history
               (instruction_id, instruction_key, version, content, changed_by, change_reason)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            existing["id"],
            instruction_key,
            existing["version"],
            existing["content"],
            user["id"],
            req.change_reason,
        )

        await conn.execute(
            """UPDATE ai_instructions
               SET content = $1, version = $2, updated_by = $3, updated_at = NOW()
               WHERE instruction_key = $4""",
            req.content,
            new_version,
            user["id"],
            instruction_key,
        )

    return {"status": "updated", "version": new_version}


@router.get("/{instruction_key}/history")
async def get_instruction_history(
    instruction_key: str,
    user=Depends(require_role("admin", "superadmin")),
):
    """Get version history of an instruction."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT h.*, u.full_name as changed_by_name
               FROM ai_instructions_history h
               LEFT JOIN users u ON h.changed_by = u.id
               WHERE h.instruction_key = $1
               ORDER BY h.version DESC LIMIT 50""",
            instruction_key,
        )
    return {"items": [dict(r) for r in rows]}


@router.post("/{instruction_key}/restore/{version}")
async def restore_instruction_version(
    instruction_key: str,
    version: int,
    user=Depends(require_role("superadmin")),
):
    """Restore a previous version. Superadmin only."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        hist = await conn.fetchrow(
            """SELECT content FROM ai_instructions_history
               WHERE instruction_key = $1 AND version = $2""",
            instruction_key,
            version,
        )
        if not hist:
            raise HTTPException(404, "Version not found")

        existing = await conn.fetchrow(
            "SELECT id, version, content FROM ai_instructions WHERE instruction_key = $1",
            instruction_key,
        )
        if not existing:
            raise HTTPException(404, "Instruction not found")

        new_version = existing["version"] + 1

        await conn.execute(
            """INSERT INTO ai_instructions_history
               (instruction_id, instruction_key, version, content, changed_by, change_reason)
               VALUES ($1, $2, $3, $4, $5, $6)""",
            existing["id"],
            instruction_key,
            existing["version"],
            existing["content"],
            user["id"],
            f"Restored from version {version}",
        )

        await conn.execute(
            """UPDATE ai_instructions
               SET content = $1, version = $2, updated_by = $3, updated_at = NOW()
               WHERE instruction_key = $4""",
            hist["content"],
            new_version,
            user["id"],
            instruction_key,
        )

    return {"status": "restored", "from_version": version, "new_version": new_version}


async def load_instruction(key: str) -> Optional[str]:
    """Load an active instruction by key. Used at runtime by AI module."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT content FROM ai_instructions WHERE instruction_key = $1 AND is_active = TRUE",
            key,
        )
    return row["content"] if row else None


async def load_instruction_json(key: str) -> Optional[dict]:
    """Load an instruction and parse as JSON."""
    content = await load_instruction(key)
    if not content:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return None
