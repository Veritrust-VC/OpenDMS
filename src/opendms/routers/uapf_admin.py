"""
UAPF admin REST API — what the OpenDMS frontend uses to manage the bridge.

Endpoints (all under /api/uapf):
  GET    /triggers                  list process_triggers
  POST   /triggers                  create
  PUT    /triggers/{id}             update
  DELETE /triggers/{id}             soft-delete (sets is_active=false)
  GET    /sessions?limit=&doc=      list uapf_sessions
  GET    /sessions/{session_id}     detail + audit chain from engine
  GET    /classifications?doc=      list complaint_classifications
  GET    /packages                  what's loaded in the engine + source URLs
  POST   /packages/sync             {packageId, sourceUrl} — fetch from ProcessGit
  POST   /packages/reload           re-scan engine packages dir
  POST   /run-now/{doc_id}          manually trigger UAPF for a doc (Demo button)
  POST   /seed-demo-data            create 6 synthetic Latvian iesniegumi
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Body, Query
from pydantic import BaseModel

from opendms.config import get_settings
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user, require_role
from opendms.uapf import on_document_event
from opendms.uapf.client import UapfClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/uapf", tags=["UAPF Management"])


def _decode_json_fields(row: dict, fields: list[str]) -> dict:
    for f in fields:
        v = row.get(f)
        if isinstance(v, (str, bytes)):
            try:
                row[f] = json.loads(v)
            except Exception:
                pass
    return row


# ─────────────────────────────────────────────────────────────
# Triggers
# ─────────────────────────────────────────────────────────────

class TriggerIn(BaseModel):
    name: str
    description: Optional[str] = None
    package_id: str
    package_version: Optional[str] = None
    process_id: str
    trigger_event: str  # document.received | document.created | document.assigned | document.decided
    match_condition: dict = {}
    is_active: bool = True


@router.get("/triggers")
async def list_triggers(user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT t.id, t.name, t.description, t.package_id, t.package_version,
                      t.process_id, t.trigger_event, t.match_condition,
                      t.is_active, t.created_at, t.updated_at
                 FROM process_triggers t
                ORDER BY t.id"""
        )
    return [_decode_json_fields(dict(r), ["match_condition"]) for r in rows]


@router.post("/triggers", status_code=201)
async def create_trigger(t: TriggerIn, user=Depends(require_role("admin", "superadmin"))):
    if t.trigger_event not in (
        "document.created", "document.received", "document.assigned",
        "document.decided", "manual",
    ):
        raise HTTPException(400, f"Invalid trigger_event: {t.trigger_event}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO process_triggers
                 (name, description, package_id, package_version, process_id,
                  trigger_event, match_condition, is_active, created_by)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               RETURNING *""",
            t.name, t.description, t.package_id, t.package_version,
            t.process_id, t.trigger_event, json.dumps(t.match_condition or {}),
            t.is_active, user.get("id"),
        )
    return _decode_json_fields(dict(row), ["match_condition"])


@router.put("/triggers/{trigger_id}")
async def update_trigger(
    trigger_id: int,
    fields: dict = Body(...),
    user=Depends(require_role("admin", "superadmin")),
):
    allowed = {
        "name", "description", "package_id", "package_version", "process_id",
        "trigger_event", "match_condition", "is_active",
    }
    sets, vals, idx = [], [], 1
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "match_condition":
            v = json.dumps(v or {})
        sets.append(f"{k} = ${idx}")
        vals.append(v)
        idx += 1
    if not sets:
        raise HTTPException(400, "No valid fields to update")
    sets.append("updated_at = NOW()")
    vals.append(trigger_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE process_triggers SET {', '.join(sets)} WHERE id = ${idx} RETURNING *",
            *vals,
        )
    if not row:
        raise HTTPException(404, "Trigger not found")
    return _decode_json_fields(dict(row), ["match_condition"])


@router.delete("/triggers/{trigger_id}")
async def delete_trigger(
    trigger_id: int,
    user=Depends(require_role("admin", "superadmin")),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Soft-delete: set is_active = false (preserve session history references)
        result = await conn.execute(
            "UPDATE process_triggers SET is_active = FALSE, updated_at = NOW() WHERE id = $1",
            trigger_id,
        )
    if result.endswith("UPDATE 0"):
        raise HTTPException(404, "Trigger not found")
    return {"deactivated": True, "id": trigger_id}


# ─────────────────────────────────────────────────────────────
# Sessions
# ─────────────────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions(
    limit: int = Query(50, le=200),
    doc: Optional[int] = None,
    user=Depends(get_current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if doc is not None:
            rows = await conn.fetch(
                """SELECT s.*, t.name AS trigger_name
                     FROM uapf_sessions s
                     LEFT JOIN process_triggers t ON t.id = s.trigger_id
                    WHERE s.document_id = $1
                    ORDER BY s.started_at DESC
                    LIMIT $2""",
                doc, limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT s.*, t.name AS trigger_name
                     FROM uapf_sessions s
                     LEFT JOIN process_triggers t ON t.id = s.trigger_id
                    ORDER BY s.started_at DESC
                    LIMIT $1""",
                limit,
            )
    return [_decode_json_fields(dict(r), ["input_payload", "output_payload"]) for r in rows]


@router.get("/sessions/{session_id}")
async def get_session(session_id: str, user=Depends(get_current_user)):
    """Detail of one session — combines local DB record with audit chain pulled
    live from the engine. The engine holds the step-by-step CloudEvents trace."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """SELECT s.*, t.name AS trigger_name
                 FROM uapf_sessions s
                 LEFT JOIN process_triggers t ON t.id = s.trigger_id
                WHERE s.session_id = $1""",
            session_id,
        )
    if not row:
        raise HTTPException(404, "Session not found")
    out = _decode_json_fields(dict(row), ["input_payload", "output_payload"])

    # Try to fetch the audit chain from the engine. This is best-effort —
    # in-memory sessions are lost if the engine restarted.
    s = get_settings()
    audit_chain = []
    try:
        client = UapfClient(s.uapf_engine_url, s.uapf_engine_auth_token)
        audit_chain = await client.get_session_audit(session_id)
    except Exception as e:
        logger.info("Engine audit fetch failed for %s: %s", session_id, e)

    # Also pull document_events with type starting "UAPF/" — those are
    # persisted permanently from the engine's audit callbacks.
    async with pool.acquire() as conn:
        events = await conn.fetch(
            """SELECT id, event_type, details, created_at
                 FROM document_events
                WHERE document_id = $1
                  AND event_type LIKE 'UAPF/%'
                ORDER BY id""",
            row["document_id"],
        )
    out["audit_chain_live"] = audit_chain
    out["audit_chain_persisted"] = [
        {**dict(e), "details": _try_json(e["details"])} for e in events
    ]
    return out


def _try_json(v):
    if isinstance(v, (str, bytes)):
        try:
            return json.loads(v)
        except Exception:
            return v
    return v


# ─────────────────────────────────────────────────────────────
# Classifications (Tiesibsargs-specific result table)
# ─────────────────────────────────────────────────────────────

@router.get("/classifications")
async def list_classifications(
    doc: Optional[int] = None,
    limit: int = Query(50, le=200),
    user=Depends(get_current_user),
):
    pool = await get_pool()
    async with pool.acquire() as conn:
        if doc is not None:
            rows = await conn.fetch(
                """SELECT c.*, d.title AS document_title, d.registration_number
                     FROM complaint_classifications c
                     LEFT JOIN documents d ON d.id = c.document_id
                    WHERE c.document_id = $1
                    ORDER BY c.created_at DESC""",
                doc,
            )
        else:
            rows = await conn.fetch(
                """SELECT c.*, d.title AS document_title, d.registration_number
                     FROM complaint_classifications c
                     LEFT JOIN documents d ON d.id = c.document_id
                    ORDER BY c.created_at DESC
                    LIMIT $1""",
                limit,
            )
    return [_decode_json_fields(dict(r), ["raw_facets"]) for r in rows]


# ─────────────────────────────────────────────────────────────
# Packages — what's loaded in the engine + source tracking
# ─────────────────────────────────────────────────────────────

@router.get("/packages")
async def list_packages(user=Depends(get_current_user)):
    """Combines engine's loaded packages with our local source-URL tracking."""
    s = get_settings()
    client = UapfClient(s.uapf_engine_url, s.uapf_engine_auth_token)

    engine_packages = []
    engine_alive = False
    try:
        engine_packages = await client.list_packages()
        engine_alive = True
    except Exception as e:
        logger.warning("Engine list_packages failed: %s", e)

    pool = await get_pool()
    async with pool.acquire() as conn:
        sources = await conn.fetch("SELECT * FROM uapf_package_sources")
    source_by_pkg = {s["package_id"]: dict(s) for s in sources}

    enriched = []
    for p in engine_packages:
        pid = p.get("packageId")
        src = source_by_pkg.get(pid, {})
        enriched.append({
            **p,
            "source_url": src.get("source_url"),
            "last_synced_at": src.get("last_synced_at").isoformat()
                if src.get("last_synced_at") else None,
        })

    return {
        "engine_alive": engine_alive,
        "engine_url": s.uapf_engine_url,
        "packages": enriched,
    }


class PackageSyncIn(BaseModel):
    package_id: str
    source_url: str  # e.g. "https://processgit.org/AI_Sandbox/iesnieguma-izskatisana/archive/main.zip"


@router.post("/packages/sync")
async def sync_package(
    body: PackageSyncIn,
    user=Depends(require_role("admin", "superadmin")),
):
    """Fetch a package from a remote URL (ProcessGit / GitHub) and tell the
    engine to install it. Records the source URL so we can re-sync later."""
    s = get_settings()
    client = UapfClient(s.uapf_engine_url, s.uapf_engine_auth_token)

    # Tell the engine to install — engine handles the actual download
    async with httpx.AsyncClient(timeout=120.0) as hc:
        r = await hc.post(
            f"{s.uapf_engine_url.rstrip('/')}/uapf/admin/install-from-url",
            json={"sourceUrl": body.source_url, "packageId": body.package_id},
        )
        if r.status_code >= 400:
            raise HTTPException(502, f"Engine install failed: {r.text[:400]}")
        result = r.json()

    # Record / update source mapping
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO uapf_package_sources (package_id, source_url, last_synced_at)
               VALUES ($1, $2, NOW())
               ON CONFLICT (package_id) DO UPDATE SET
                 source_url = EXCLUDED.source_url,
                 last_synced_at = NOW()""",
            body.package_id, body.source_url,
        )
    return result


@router.post("/packages/reload")
async def reload_packages(user=Depends(require_role("admin", "superadmin"))):
    """Tell the engine to re-scan its PACKAGES_DIR. Use after manual file drop."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=30.0) as hc:
        r = await hc.post(f"{s.uapf_engine_url.rstrip('/')}/uapf/admin/reload")
        if r.status_code >= 400:
            raise HTTPException(502, f"Engine reload failed: {r.text[:400]}")
        return r.json()


# ─────────────────────────────────────────────────────────────
# Run-now: manually trigger UAPF for a document (the Demo button)
# ─────────────────────────────────────────────────────────────

class RunNowIn(BaseModel):
    event_type: str = "document.received"
    package_id: Optional[str] = None  # if set, override trigger matching
    process_id: Optional[str] = None


@router.post("/run-now/{doc_id}")
async def run_now(
    doc_id: int,
    body: RunNowIn,
    user=Depends(get_current_user),
):
    """Manually fire UAPF for a document. Used by the demo console.

    If package_id+process_id are provided, runs that specific package directly,
    bypassing process_triggers matching. Otherwise behaves like a normal
    lifecycle event and matches against active triggers.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            "SELECT id, title, doc_did, registration_number FROM documents WHERE id = $1",
            doc_id,
        )
    if not doc:
        raise HTTPException(404, "Document not found")

    if body.package_id and body.process_id:
        # Direct invocation — skip trigger lookup
        s = get_settings()
        client = UapfClient(s.uapf_engine_url, s.uapf_engine_auth_token)
        from opendms.uapf.manifest import build_host_manifest
        input_payload = {
            "documentId": doc["id"],
            "documentDid": doc["doc_did"],
            "title": doc["title"],
            "registrationNumber": doc["registration_number"],
        }
        session_id = None
        state = "starting"
        output = None
        error = None
        try:
            result = await client.start_session(
                package_id=body.package_id,
                process_id=body.process_id,
                input_payload=input_payload,
                host_manifest=build_host_manifest(),
            )
            session_id = result.get("sessionId")
            state = result.get("state", "unknown")
            output = result.get("output")
        except Exception as e:
            state = "failed"
            error = str(e)
            # Persist failed run too so it shows up in Sessions tab
            async with pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO uapf_sessions
                         (session_id, document_id, package_id, process_id, state,
                          input_payload, error_message, completed_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())
                       ON CONFLICT (session_id) DO NOTHING""",
                    f"sess_failed_{doc_id}_{int(__import__('time').time())}",
                    doc_id, body.package_id, body.process_id, state,
                    json.dumps(input_payload), error,
                )
            raise HTTPException(502, f"Engine start-session failed: {e}")

        # Persist successful run so Sessions tab shows it
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO uapf_sessions
                     (session_id, document_id, package_id, process_id, state,
                      input_payload, output_payload,
                      completed_at)
                   VALUES ($1, $2, $3, $4, $5, $6, $7,
                           CASE WHEN $5 IN ('completed','failed','aborted')
                                THEN NOW() ELSE NULL END)
                   ON CONFLICT (session_id) DO UPDATE SET
                     state = EXCLUDED.state,
                     output_payload = EXCLUDED.output_payload,
                     completed_at = CASE WHEN EXCLUDED.state IN ('completed','failed','aborted')
                                         THEN NOW() ELSE uapf_sessions.completed_at END""",
                session_id or f"sess_manual_{doc_id}_{int(__import__('time').time())}",
                doc_id, body.package_id, body.process_id, state,
                json.dumps(input_payload),
                json.dumps(output) if output is not None else None,
            )
        return {"mode": "direct", "result": result}
    else:
        # Trigger-based — same code path as automatic lifecycle hook
        await on_document_event(body.event_type, doc_id)
        return {"mode": "trigger", "event_type": body.event_type, "document_id": doc_id}


# ─────────────────────────────────────────────────────────────
# Demo data seeder
# ─────────────────────────────────────────────────────────────

@router.post("/seed-demo-data")
async def seed_demo_data(user=Depends(require_role("admin", "superadmin"))):
    """Create 6 synthetic Latvian iesniegumi for live demos. Idempotent —
    skipped if any document with registration_number starting with 'DEMO-' exists."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT COUNT(*) FROM documents WHERE registration_number LIKE 'DEMO-%'"
        )
        if existing > 0:
            return {"created": 0, "skipped": True, "message": f"{existing} demo docs already exist"}

        default_org = await conn.fetchrow(
            "SELECT id FROM organizations WHERE is_default = TRUE LIMIT 1"
        )
        org_id = default_org["id"] if default_org else None

    iesniegumi = [
        {
            "title": "Sūdzība par bāriņtiesas lēmumu (mazbērna aizgādība)",
            "content_summary": "Vecmāmiņa lūdz pārskatīt bāriņtiesas lēmumu par 5 gadus veca mazbērna ievietošanu ārpus ģimenes aprūpē. Lēmums pieņemts steigā, ģimenei nav bijusi iespēja izklāstīt savu pozīciju.",
            "expected_topic": "child-rights",
            "expected_priority": "high",
        },
        {
            "title": "Diskriminācija pieņemšanā darbā (invaliditāte)",
            "content_summary": "Iesniedzējs ar otrās grupas invaliditāti norāda, ka valsts iestādes darba intervijā atklāti pateikts: 'nevaram pieņemt cilvēkus ar īpašām vajadzībām'. Lūdz Tiesībsargu izmeklēt.",
            "expected_topic": "discrimination",
            "expected_priority": "urgent",
        },
        {
            "title": "Sūdzība par būvvaldes bezdarbību (atbilde 3 mēnešus)",
            "content_summary": "Iesniedzējs nav saņēmis atbildi no pašvaldības būvvaldes 3 mēnešus. Pieprasījumi neatbildēti. Uzskata, ka pārkāpts labas pārvaldības princips (APL 4.p.).",
            "expected_topic": "good-governance",
            "expected_priority": "normal",
        },
        {
            "title": "Veselības aprūpes pakalpojumu pieejamība (rinda speciālistam)",
            "content_summary": "Iesniedzējs gaida pieņemšanu pie endokrinologa 14 mēnešus. Veselības stāvoklis pasliktinās. Lūdz Tiesībsargu izvērtēt pacientu tiesību ievērošanu.",
            "expected_topic": "health-rights",
            "expected_priority": "high",
        },
        {
            "title": "Personas datu apstrāde bez piekrišanas",
            "content_summary": "Iesniedzējs konstatējis, ka pašvaldība publicējusi viņa vārdu un adresi tīmekļa vietnē bez piekrišanas. Lūdz pārbaudīt GDPR atbilstību.",
            "expected_topic": "privacy-rights",
            "expected_priority": "normal",
        },
        {
            "title": "Apcietinājuma apstākļi (pārmērīga celle)",
            "content_summary": "Ieslodzītā tuviniece raksta par necilvēcīgiem apstākļiem cietumā: pārpildīta kamera, nepietiekama medicīniskā aprūpe. Lūdz pārbaudīt.",
            "expected_topic": "prisoner-rights",
            "expected_priority": "high",
        },
    ]

    created = []
    async with pool.acquire() as conn:
        for i, ie in enumerate(iesniegumi, start=1):
            reg_num = f"DEMO-{i:03d}"
            metadata = {
                "demo_fixture": True,
                "expected_topic": ie["expected_topic"],
                "expected_priority": ie["expected_priority"],
                "channel": "e-Adrese (demo)",
            }
            row = await conn.fetchrow(
                """INSERT INTO documents
                       (title, registration_number, status, org_id,
                        content_summary, metadata, created_by, ai_summary_status)
                   VALUES ($1, $2, 'registered', $3, $4, $5, $6, 'PENDING')
                   RETURNING id, title, registration_number""",
                ie["title"], reg_num, org_id, ie["content_summary"],
                json.dumps(metadata), user["id"],
            )
            created.append(dict(row))
            # Log a DocumentCreated event so it appears in the lifecycle
            await conn.execute(
                """INSERT INTO document_events
                       (document_id, event_type, actor_id, vc_submitted, details)
                   VALUES ($1, 'DocumentCreated', $2, FALSE, $3)""",
                row["id"], user["id"],
                json.dumps({"seeded": True, "registration_number": reg_num}),
            )

    return {"created": len(created), "documents": created}
