"""Document management with lifecycle workflow and SDK integration."""

import json
import uuid
from typing import Optional, Any
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from opendms.database import get_pool
from opendms.middleware.auth import get_current_user, require_role
from opendms.storage import get_storage, generate_storage_key
from opendms.config import get_settings
from opendms import sdk_client
from opendms.audit import log_integration_event, summarize_payload
from opendms.org_context import get_default_org_required

router = APIRouter(prefix="/api/documents", tags=["Documents"])


class DocumentCreate(BaseModel):
    title: str
    register_id: Optional[int] = None
    classification_id: Optional[int] = None
    content_summary: Optional[str] = None
    metadata: dict = {}
    semantic_summary: Optional[dict[str, Any]] = None
    sensitivity_control: Optional[dict[str, Any]] = None
    ai_summary_status: Optional[str] = None


class DocumentSend(BaseModel):
    recipient_org_did: str
    delivery_method: str = "internal"


class DocumentReceive(BaseModel):
    sender_org_did: str
    local_registration_number: Optional[str] = None


class DocumentAssign(BaseModel):
    user_id: int
    department: Optional[str] = None


class DocumentDecide(BaseModel):
    decision: str
    resolution: Optional[str] = None


class ExtractSummaryPreviewRequest(BaseModel):
    metadata: dict = {}
    file_name: Optional[str] = None
    file_content_base64: Optional[str] = None


def _derive_ai_summary_status(req: DocumentCreate, sdk_result: Optional[dict[str, Any]]) -> str:
    if req.ai_summary_status:
        return req.ai_summary_status
    if req.semantic_summary or req.sensitivity_control:
        source = (req.semantic_summary or {}).get("summarySource")
        return "VALIDATED" if source in ("HUMAN", "HYBRID") else "GENERATED"
    if sdk_result and (sdk_result.get("semanticSummary") or sdk_result.get("sensitivityControl")):
        return "GENERATED"
    return "SKIPPED"


def _decode_jsonb(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


# ── List / Search ──

@router.get("")
async def list_documents(
    org_id: Optional[int] = None, status: Optional[str] = None,
    register_id: Optional[int] = None, classification_id: Optional[int] = None,
    search: Optional[str] = None, assigned_to: Optional[int] = None,
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
):
    default_org = await get_default_org_required()
    workspace_org_id = default_org["id"]

    pool = await get_pool()
    async with pool.acquire() as conn:
        wheres, params, idx = ["d.org_id = $1"], [workspace_org_id], 2
        for field, val in [("d.status", status), ("d.register_id", register_id),
                           ("d.classification_id", classification_id), ("d.assigned_to", assigned_to)]:
            if val is not None:
                wheres.append(f"{field} = ${idx}"); params.append(val); idx += 1
        if search:
            wheres.append(f"(d.title ILIKE ${idx} OR d.registration_number ILIKE ${idx})"); params.append(f"%{search}%"); idx += 1

        where = " AND ".join(wheres)
        total = await conn.fetchval(f"SELECT COUNT(*) FROM documents d WHERE {where}", *params)
        rows = await conn.fetch(
            f"""SELECT d.*, o.name as org_name, r.name as register_name, c.name as classification_name,
                       u.full_name as assigned_name, cr.full_name as creator_name
                FROM documents d
                LEFT JOIN organizations o ON d.org_id = o.id
                LEFT JOIN registers r ON d.register_id = r.id
                LEFT JOIN classifications c ON d.classification_id = c.id
                LEFT JOIN users u ON d.assigned_to = u.id
                LEFT JOIN users cr ON d.created_by = cr.id
                WHERE {where} ORDER BY d.updated_at DESC LIMIT ${idx} OFFSET ${idx+1}""",
            *params, page_size, (page - 1) * page_size)
    items = []
    for r in rows:
        d = dict(r)
        d["metadata"] = _decode_jsonb(d["metadata"])
        d["semantic_summary"] = _decode_jsonb(d.get("semantic_summary"))
        d["sensitivity_control"] = _decode_jsonb(d.get("sensitivity_control"))
        items.append(d)
    return {"items": items, "total": total, "page": page}


# ── Create ──

@router.post("", status_code=201)
async def create_document(req: DocumentCreate, user=Depends(get_current_user)):
    pool = await get_pool()
    s = get_settings()
    trace_id = str(uuid.uuid4())
    actor = {"id": user.get("id"), "email": user.get("email"), "role": user.get("role")}
    async with pool.acquire() as conn:
        default_org = await get_default_org_required()
        org_id = default_org["id"]
        count = await conn.fetchval("SELECT COUNT(*) FROM documents WHERE org_id = $1", org_id)
        reg_num = f"{org_id}-{count + 1:05d}"

        await log_integration_event(
            trace_id=trace_id,
            actor_user_id=user.get("id"),
            actor_email=user.get("email"),
            actor_role=user.get("role"),
            organization_id=org_id,
            entity_type="document",
            entity_id=reg_num,
            action="opendms.doc.create.requested",
            target_system="sdk",
            request_method="POST",
            request_path="/api/documents/create",
            request_payload_summary=summarize_payload({"title": req.title, "registrationNumber": reg_num}),
        )

        doc_did = None
        sdk_result = None
        if s.sdk_enabled:
            sdk_result = await sdk_client.create_document(
                title=req.title,
                classification=req.metadata.get("classification", ""),
                reg_number=reg_num,
                metadata={
                    **req.metadata,
                    "semanticSummary": req.semantic_summary,
                    "sensitivityControl": req.sensitivity_control,
                },
                trace_id=trace_id,
                actor=actor,
            )
            if sdk_result:
                trace_id = sdk_result.get("trace_id") or trace_id
                doc_did = sdk_result.get("docDid")

        semantic_summary = req.semantic_summary or (sdk_result or {}).get("semanticSummary")
        sensitivity_control = req.sensitivity_control or (sdk_result or {}).get("sensitivityControl")
        ai_summary_status = _derive_ai_summary_status(req, sdk_result)

        row = await conn.fetchrow(
            """INSERT INTO documents (title, registration_number, doc_did, status, org_id,
                   register_id, classification_id, content_summary, metadata, semantic_summary, sensitivity_control, ai_summary_status, created_by)
               VALUES ($1,$2,$3,'registered',$4,$5,$6,$7,$8,$9,$10,$11,$12)
               RETURNING id, title, registration_number, doc_did, status, org_id, semantic_summary, sensitivity_control, ai_summary_status, created_at""",
            req.title, reg_num, doc_did, org_id, req.register_id,
            req.classification_id, req.content_summary,
            json.dumps(req.metadata), json.dumps(semantic_summary) if semantic_summary is not None else None,
            json.dumps(sensitivity_control) if sensitivity_control is not None else None,
            ai_summary_status,
            user["id"])

        await conn.execute(
            "INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details) VALUES ($1,$2,$3,$4,$5)",
            row["id"], "DocumentCreated", user["id"], doc_did is not None,
            json.dumps({"registration_number": reg_num, "sdk_did": doc_did, "semanticSummary": semantic_summary, "sensitivityControl": sensitivity_control, "aiSummaryStatus": ai_summary_status}))

    await log_integration_event(
        trace_id=trace_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        actor_role=user.get("role"),
        organization_id=row["org_id"],
        entity_type="document",
        entity_id=str(row["id"]),
        entity_did=doc_did,
        action="opendms.doc.create.completed",
        target_system="sdk",
        request_method="POST",
        request_path="/api/documents/create",
        response_status=sdk_result.get("_meta", {}).get("status_code", 200) if sdk_result else 502,
        response_summary=summarize_payload(sdk_result or {"detail": "SDK unavailable"}),
        success=sdk_result is not None,
        error_message=None if sdk_result else "SDK document creation unavailable",
    )

    result = dict(row)
    result["semantic_summary"] = _decode_jsonb(result.get("semantic_summary"))
    result["sensitivity_control"] = _decode_jsonb(result.get("sensitivity_control"))
    result["sdk_result"] = sdk_result
    result["trace_id"] = trace_id
    return result


# ── File upload ──

@router.post("/{doc_id}/upload")
async def upload_file(doc_id: int, file: UploadFile = File(...), user=Depends(get_current_user)):
    default_org = await get_default_org_required()
    workspace_org_id = default_org["id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT * FROM documents WHERE id = $1 AND org_id = $2", doc_id, workspace_org_id)
    if not doc: raise HTTPException(404, "Document not found")

    storage = get_storage()
    content = await file.read()
    key = generate_storage_key(doc["org_id"] or 0, file.filename)
    await storage.put(key, content, file.content_type or "")

    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET storage_key=$1, storage_backend=$2, file_name=$3, file_size=$4, mime_type=$5 WHERE id=$6",
            key, get_settings().storage_backend, file.filename, len(content), file.content_type, doc_id)

    return {"status": "uploaded", "key": key, "size": len(content), "filename": file.filename}


@router.get("/{doc_id}/download")
async def download_file(doc_id: int, user=Depends(get_current_user)):
    default_org = await get_default_org_required()
    workspace_org_id = default_org["id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT storage_key, file_name, mime_type FROM documents WHERE id = $1 AND org_id = $2", doc_id, workspace_org_id)
    if not doc or not doc["storage_key"]: raise HTTPException(404, "No file attached")

    from fastapi.responses import Response
    storage = get_storage()
    data = await storage.get(doc["storage_key"])
    if not data: raise HTTPException(404, "File not found in storage")
    return Response(content=data, media_type=doc["mime_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{doc["file_name"]}"'})


# ── Get detail ──

@router.get("/{doc_id}")
async def get_document(doc_id: int, user=Depends(get_current_user)):
    default_org = await get_default_org_required()
    workspace_org_id = default_org["id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            """SELECT d.*, o.name as org_name, r.name as register_name, c.name as classification_name,
                      u.full_name as assigned_name, cr.full_name as creator_name
               FROM documents d LEFT JOIN organizations o ON d.org_id = o.id
               LEFT JOIN registers r ON d.register_id = r.id LEFT JOIN classifications c ON d.classification_id = c.id
               LEFT JOIN users u ON d.assigned_to = u.id LEFT JOIN users cr ON d.created_by = cr.id
               WHERE d.id = $1 AND d.org_id = $2""", doc_id, workspace_org_id)
        if not doc: raise HTTPException(404, "Document not found")
        events = await conn.fetch(
            """SELECT de.*, u.full_name as actor_name FROM document_events de
               LEFT JOIN users u ON de.actor_id = u.id WHERE de.document_id = $1 ORDER BY de.created_at""", doc_id)
    result = dict(doc)
    result["metadata"] = _decode_jsonb(result["metadata"])
    result["semantic_summary"] = _decode_jsonb(result.get("semantic_summary"))
    result["sensitivity_control"] = _decode_jsonb(result.get("sensitivity_control"))
    result["events"] = [dict(e) for e in events]
    return result


@router.post("/{doc_id}/extract-summary")
async def extract_summary_for_document(doc_id: int, file: UploadFile = File(...), user=Depends(get_current_user)):
    default_org = await get_default_org_required()
    workspace_org_id = default_org["id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT id, org_id FROM documents WHERE id = $1 AND org_id = $2", doc_id, workspace_org_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    content = await file.read()
    result = await sdk_client.extract_summary(content, file.filename or "document.bin", metadata={"documentId": doc_id}, actor=user)
    if not result:
        raise HTTPException(502, "Summary extraction unavailable")

    semantic_summary = result.get("semanticSummary")
    sensitivity_control = result.get("sensitivityControl")
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET semantic_summary = $1, sensitivity_control = $2, ai_summary_status = $3 WHERE id = $4",
            json.dumps(semantic_summary) if semantic_summary is not None else None,
            json.dumps(sensitivity_control) if sensitivity_control is not None else None,
            "GENERATED",
            doc_id,
        )
    return {
        "documentId": doc_id,
        "semanticSummary": semantic_summary,
        "sensitivityControl": sensitivity_control,
        "trace_id": result.get("trace_id"),
        "route": result.get("route"),
    }


@router.post("/extract-summary-preview")
async def extract_summary_preview(
    file: Optional[UploadFile] = File(default=None),
    metadata: str = Form(default="{}"),
    user=Depends(get_current_user),
):
    parsed_metadata = {}
    if metadata:
        try:
            parsed_metadata = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, f"Invalid metadata JSON: {exc}")

    if file is None:
        raise HTTPException(400, "File is required for preview extraction")

    content = await file.read()
    result = await sdk_client.extract_summary(content, file.filename or "document.bin", metadata=parsed_metadata, actor=user)
    if not result:
        raise HTTPException(502, "Summary extraction unavailable")

    return {
        "semanticSummary": result.get("semanticSummary"),
        "sensitivityControl": result.get("sensitivityControl"),
        "route": result.get("route"),
        "trace_id": result.get("trace_id"),
    }


# ── Lifecycle transitions ──

async def _transition(doc_id: int, event_type: str, new_status: str, user: dict, sdk_fn, sdk_args: dict, extra_details: dict = None, action_name: str = "opendms.doc.lifecycle"):
    default_org = await get_default_org_required()
    workspace_org_id = default_org["id"]
    pool = await get_pool()
    trace_id = str(uuid.uuid4())
    actor = {"id": user.get("id"), "email": user.get("email"), "role": user.get("role")}
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT id, doc_did, status, org_id FROM documents WHERE id = $1 AND org_id = $2", doc_id, workspace_org_id)
        if not doc: raise HTTPException(404, "Document not found")
        doc_data = dict(doc)

        await log_integration_event(
            trace_id=trace_id,
            actor_user_id=user.get("id"),
            actor_email=user.get("email"),
            actor_role=user.get("role"),
            organization_id=doc_data.get("org_id"),
            entity_type="document",
            entity_id=str(doc_id),
            entity_did=doc_data.get("doc_did"),
            action=f"{action_name}.requested",
            target_system="sdk",
            request_method="POST",
            request_path=f"/api/documents/{doc_data.get('doc_did')}/{new_status}",
            request_payload_summary=summarize_payload(sdk_args),
        )

        vc_submitted = False
        sdk_result = None
        if get_settings().sdk_enabled and doc["doc_did"]:
            sdk_result = await sdk_fn(doc["doc_did"], **sdk_args, trace_id=trace_id, actor=actor)
            vc_submitted = sdk_result is not None
            if sdk_result:
                trace_id = sdk_result.get("trace_id") or trace_id

        update_cols = ["status = $1"]
        update_params = [new_status]
        idx = 2
        if extra_details and "assigned_to" in extra_details:
            update_cols.append(f"assigned_to = ${idx}"); update_params.append(extra_details["assigned_to"]); idx += 1
        update_params.append(doc_id)
        await conn.execute(f"UPDATE documents SET {', '.join(update_cols)} WHERE id = ${idx}", *update_params)

        await conn.execute(
            "INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details) VALUES ($1,$2,$3,$4,$5)",
            doc_id, event_type, user["id"], vc_submitted, json.dumps(extra_details or {}))

    await log_integration_event(
        trace_id=trace_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        actor_role=user.get("role"),
        organization_id=doc_data.get("org_id"),
        entity_type="document",
        entity_id=str(doc_id),
        entity_did=doc_data.get("doc_did"),
        action=f"{action_name}.completed",
        target_system="sdk",
        request_method="POST",
        request_path=f"/api/documents/{doc_data.get('doc_did')}/{new_status}",
        response_status=sdk_result.get("_meta", {}).get("status_code", 200) if sdk_result else 502,
        response_summary=summarize_payload(sdk_result or {"detail": "SDK unavailable"}),
        success=vc_submitted,
        error_message=None if vc_submitted else "SDK lifecycle call failed or disabled",
    )
    return {"status": new_status, "vc_submitted": vc_submitted, "trace_id": trace_id}


@router.post("/{doc_id}/send")
async def send_document(doc_id: int, req: DocumentSend, user=Depends(get_current_user)):
    return await _transition(doc_id, "DocumentSent", "sent", user,
        sdk_client.send_document, {"recipient_did": req.recipient_org_did, "method": req.delivery_method},
        {"recipient": req.recipient_org_did, "method": req.delivery_method}, action_name="opendms.doc.send")


@router.post("/{doc_id}/receive")
async def receive_document(doc_id: int, req: DocumentReceive, user=Depends(get_current_user)):
    return await _transition(doc_id, "DocumentReceived", "received", user,
        sdk_client.receive_document, {"sender_did": req.sender_org_did, "local_reg": req.local_registration_number or ""},
        {"sender": req.sender_org_did, "local_reg": req.local_registration_number}, action_name="opendms.doc.receive")


@router.post("/{doc_id}/assign")
async def assign_document(doc_id: int, req: DocumentAssign, user=Depends(get_current_user)):
    pool = await get_pool()
    async with pool.acquire() as conn:
        assignee = await conn.fetchrow("SELECT id, full_name FROM users WHERE id = $1", req.user_id)
    if not assignee: raise HTTPException(404, "User not found")
    return await _transition(doc_id, "DocumentAssigned", "assigned", user,
        sdk_client.assign_document, {"assignee": assignee["full_name"], "department": req.department or ""},
        {"user_id": req.user_id, "assignee": assignee["full_name"], "department": req.department, "assigned_to": req.user_id}, action_name="opendms.doc.assign")


@router.post("/{doc_id}/decide")
async def decide_document(doc_id: int, req: DocumentDecide, user=Depends(get_current_user)):
    return await _transition(doc_id, "DocumentDecided", "decided", user,
        sdk_client.decide_document, {"decision": req.decision, "resolution": req.resolution or ""},
        {"decision": req.decision, "resolution": req.resolution}, action_name="opendms.doc.decide")


@router.post("/{doc_id}/archive")
async def archive_document(doc_id: int, archive_reference: Optional[str] = None, user=Depends(get_current_user)):
    return await _transition(doc_id, "DocumentArchived", "archived", user,
        sdk_client.archive_document, {"ref": archive_reference or ""},
        {"archive_reference": archive_reference}, action_name="opendms.doc.archive")


@router.get("/{doc_id}/track")
async def track_document(doc_id: int, user=Depends(get_current_user)):
    """Track document via VeriDocs Registry (through SDK)."""
    default_org = await get_default_org_required()
    workspace_org_id = default_org["id"]
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow("SELECT doc_did, org_id FROM documents WHERE id = $1 AND org_id = $2", doc_id, workspace_org_id)
    if not doc or not doc["doc_did"]: raise HTTPException(404, "No DID assigned")
    doc_data = dict(doc)
    trace_id = str(uuid.uuid4())
    await log_integration_event(
        trace_id=trace_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        actor_role=user.get("role"),
        organization_id=doc_data.get("org_id"),
        entity_type="document",
        entity_id=str(doc_id),
        entity_did=doc_data.get("doc_did"),
        action="opendms.doc.track.requested",
        target_system="sdk",
        request_method="GET",
        request_path=f"/api/documents/{doc.get('doc_did')}/track",
    )
    result = await sdk_client.track_document(doc_data["doc_did"], trace_id=trace_id, actor=user)
    if not result:
        await log_integration_event(
            trace_id=trace_id,
            actor_user_id=user.get("id"),
            actor_email=user.get("email"),
            actor_role=user.get("role"),
            organization_id=doc_data.get("org_id"),
            entity_type="document",
            entity_id=str(doc_id),
            entity_did=doc_data.get("doc_did"),
            action="opendms.doc.track.completed",
            target_system="sdk",
            request_method="GET",
            request_path=f"/api/documents/{doc.get('doc_did')}/track",
            success=False,
            response_status=502,
            error_message="Tracking unavailable",
        )
        raise HTTPException(502, "Tracking unavailable")
    trace_id = result.get("trace_id") or trace_id
    await log_integration_event(
        trace_id=trace_id,
        actor_user_id=user.get("id"),
        actor_email=user.get("email"),
        actor_role=user.get("role"),
        organization_id=doc_data.get("org_id"),
        entity_type="document",
        entity_id=str(doc_id),
        entity_did=doc_data.get("doc_did"),
        action="opendms.doc.track.completed",
        target_system="sdk",
        request_method="GET",
        request_path=f"/api/documents/{doc.get('doc_did')}/track",
        response_status=result.get("_meta", {}).get("status_code", 200),
        response_summary=summarize_payload(result),
        success=True,
    )
    result["trace_id"] = trace_id
    return result
