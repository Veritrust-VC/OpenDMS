"""
Capability handlers — host-side logic that the UAPF runtime calls back into.

Each handler implements one capability:
  - document.fetch@1   — read a document's content + metadata from OpenDMS
  - ai.redact@1        — strip PII from text using the configured LLM
  - ai.extract@1       — extract structured facets matching the package's schema
  - data.write@1       — persist a classification record to OpenDMS DB
  - event.emit@1       — publish a domain event to document_events

Handlers receive a CapabilityContext (session_id, step_id, input, guardrails)
and return a dict that will be merged into the UAPF session variables.
"""

import json
import logging
import os
import subprocess
import tempfile
from typing import Any

from opendms.ai import _complete_json
from opendms.database import get_pool

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# document.fetch@1
# ─────────────────────────────────────────────────────────────

async def handle_document_fetch(ctx: dict) -> dict:
    """
    Fetch a document's content + metadata.

    Input:  { documentDid?: str, documentId?: int }  (one is required)
    Output: { documentId, documentDid, title, content, mimeType, metadata, ...}
    """
    inp = ctx.get("input") or {}
    doc_did = inp.get("documentDid")
    doc_id = inp.get("documentId")

    pool = await get_pool()
    async with pool.acquire() as conn:
        if doc_did:
            row = await conn.fetchrow(
                """SELECT id, doc_did, title, registration_number, status, org_id,
                          metadata, semantic_summary, sensitivity_control,
                          storage_key, storage_backend, file_name, mime_type, file_size
                   FROM documents WHERE doc_did = $1""",
                doc_did,
            )
        elif doc_id is not None:
            row = await conn.fetchrow(
                """SELECT id, doc_did, title, registration_number, status, org_id,
                          metadata, semantic_summary, sensitivity_control,
                          storage_key, storage_backend, file_name, mime_type, file_size
                   FROM documents WHERE id = $1""",
                int(doc_id),
            )
        else:
            raise ValueError("document.fetch requires documentDid or documentId")

        if not row:
            raise LookupError(f"Document not found: did={doc_did} id={doc_id}")

    doc = dict(row)
    content_text = ""

    # If a file is attached, read and extract text
    if doc.get("storage_key"):
        from opendms.routers.documents import _extract_text
        from opendms.config import get_settings
        from opendms.storage import LocalStorage, S3Storage

        s = get_settings()
        if s.storage_backend == "s3":
            storage = S3Storage(
                s.storage_s3_endpoint,
                s.storage_s3_bucket,
                s.storage_s3_access_key,
                s.storage_s3_secret_key,
                s.storage_s3_region,
            )
        else:
            storage = LocalStorage(s.storage_local_path)

        try:
            data = await storage.get(doc["storage_key"])
            if data:
                content_text = _extract_text(
                    data, doc.get("mime_type") or "", doc.get("file_name") or ""
                )
        except Exception as e:
            logger.warning("document.fetch: could not read storage: %s", e)

    # Decode JSONB safely
    def _decode(v):
        if isinstance(v, (str, bytes)):
            try:
                return json.loads(v)
            except Exception:
                return v
        return v

    return {
        "output": {
            "documentId": doc["id"],
            "documentDid": doc.get("doc_did"),
            "title": doc.get("title"),
            "registrationNumber": doc.get("registration_number"),
            "content": content_text,
            "mimeType": doc.get("mime_type"),
            "fileName": doc.get("file_name"),
            "fileSize": doc.get("file_size"),
            "metadata": _decode(doc.get("metadata")),
            "semanticSummary": _decode(doc.get("semantic_summary")),
        }
    }


# ─────────────────────────────────────────────────────────────
# ai.redact@1
# ─────────────────────────────────────────────────────────────

REDACTION_SYSTEM_PROMPT = """You are a PII redaction agent for Latvian government documents.

Your task: rewrite the provided text replacing all personally-identifying information
with category placeholders. Latvian-specific PII categories include:

  - personas_kods (11-digit identity code, e.g. "010180-12345") → [PERSONAS_KODS]
  - vārds, uzvārds (personal names) → [VARDS] or [VARDS_UZVARDS]
  - bērna vārds (children's names) → [BERNA_VARDS]
  - adrese (street addresses) → [ADRESE]
  - tālrunis (phone numbers) → [TALRUNIS]
  - e-pasts (email addresses) → [EPASTS]
  - bankas konts / IBAN → [BANKAS_KONTS]
  - veselības dati (health record numbers, diagnoses) → [VESELIBAS_DATI]

Categories to redact (passed in input): the host specifies which categories to apply.

Preserve:
  - The structure, grammar, and meaning of the text
  - Generic role references ("vecmāmiņa", "sociālais darbinieks", "iesniedzējs")
  - Topic keywords needed for downstream classification (children, discrimination,
    healthcare, prisons, police, social services, privacy, public administration)
  - The original language (Latvian, Russian, English, etc.)

Respond ONLY with JSON in this exact shape:
{
  "redactedContent": "the text with PII replaced by placeholders",
  "detectedCategories": ["pii_name", "pii_id_number", ...],
  "languageDetected": "lv|ru|en|..."
}

No markdown, no preamble, no commentary."""


async def handle_ai_redact(ctx: dict) -> dict:
    """
    Redact PII from text before downstream AI processing.

    Input:  { content: str, categories?: [...] }
    Output: { redactedContent, detectedCategories, languageDetected }
    """
    inp = ctx.get("input") or {}
    content = inp.get("content") or ""
    if not content:
        # Edge case: if document.fetch returned no content, propagate empty.
        return {"output": {"redactedContent": "", "detectedCategories": [], "languageDetected": "und"}}

    # Enforce guardrails: text length cap.
    MAX_CHARS = 15000
    if len(content) > MAX_CHARS:
        content = content[:MAX_CHARS]

    user_msg = (
        f"Categories to redact: {inp.get('categories', ['pii_name','pii_id_number','pii_address','pii_financial','pii_health'])}\n\n"
        f"--- TEXT TO REDACT ---\n{content}\n--- END ---"
    )

    result = await _complete_json(REDACTION_SYSTEM_PROMPT, user_msg)
    if not result:
        # AI unavailable — fall back to regex-based scrub for known PII shapes.
        import re
        scrubbed = content
        # Latvian personas_kods
        scrubbed = re.sub(r"\b\d{6}-\d{5}\b", "[PERSONAS_KODS]", scrubbed)
        # Emails
        scrubbed = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[EPASTS]", scrubbed)
        # IBANs
        scrubbed = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b", "[BANKAS_KONTS]", scrubbed)
        return {
            "output": {
                "redactedContent": scrubbed,
                "detectedCategories": ["regex_fallback"],
                "languageDetected": "und",
                "_warning": "AI redaction unavailable; regex fallback applied",
            }
        }

    return {"output": result}


# ─────────────────────────────────────────────────────────────
# ai.extract@1
# ─────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM_PROMPT_TIESIBSARGS = """You are a facet extraction agent for citizen
complaints addressed to the Office of the Ombudsman of Latvia (Tiesībsarga birojs).

Your task: read the (PII-redacted) complaint text and return a structured JSON
object indicating which substantive topics the complaint touches on.

Respond ONLY with JSON in this exact shape, all booleans required:
{
  "mentionsChildren": <bool>,
  "mentionsDiscrimination": <bool>,
  "mentionsPrisons": <bool>,
  "mentionsPolice": <bool>,
  "mentionsHealth": <bool>,
  "mentionsSocialServices": <bool>,
  "mentionsPrivacy": <bool>,
  "mentionsPublicAdministration": <bool>,
  "vulnerablePerson": <bool>,
  "urgency": <bool>,
  "ongoingHarm": <bool>,
  "languageDetected": "lv|ru|en|..."
}

Definitions:
  - mentionsChildren: minor under 18 is the subject, victim, or principal party
  - mentionsDiscrimination: alleges discrimination by race, gender, age, disability,
    religion, sexual orientation, or other protected category
  - mentionsPrisons: occurs in or relates to a prison or detention facility
  - mentionsPolice: relates to police actions, border guard, or other law enforcement
  - mentionsHealth: about healthcare access, quality, or patient rights
  - mentionsSocialServices: about social services, benefits, pensions, or disability rights
  - mentionsPrivacy: alleges privacy violation or improper personal-data processing
  - mentionsPublicAdministration: alleges good-governance violation by a public authority
  - vulnerablePerson: subject is a minor, elderly, disabled, prisoner, or otherwise dependent
  - urgency: text explicitly states urgency or time-sensitivity
  - ongoingHarm: harm is happening now, not historical

No markdown, no preamble, no commentary. Booleans must be true/false (not strings)."""


async def handle_ai_extract(ctx: dict) -> dict:
    """
    Extract structured facets from a redacted complaint text.

    Input:  { content: str, redactedContent?: str }
    Output: { mentionsChildren: bool, ..., languageDetected: str }
    """
    inp = ctx.get("input") or {}
    # Prefer the redacted form if both are present
    text = inp.get("redactedContent") or inp.get("content") or ""
    if not text:
        return {
            "output": {
                "mentionsChildren": False, "mentionsDiscrimination": False,
                "mentionsPrisons": False, "mentionsPolice": False,
                "mentionsHealth": False, "mentionsSocialServices": False,
                "mentionsPrivacy": False, "mentionsPublicAdministration": False,
                "vulnerablePerson": False, "urgency": False, "ongoingHarm": False,
                "languageDetected": "und",
                "_warning": "no text to extract from",
            }
        }

    MAX_CHARS = 15000
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    result = await _complete_json(
        EXTRACTION_SYSTEM_PROMPT_TIESIBSARGS, f"--- COMPLAINT TEXT ---\n{text}\n--- END ---"
    )

    if not result:
        # Conservative fallback: all false. Routes to "other" topic via DMN default rule.
        return {
            "output": {
                "mentionsChildren": False, "mentionsDiscrimination": False,
                "mentionsPrisons": False, "mentionsPolice": False,
                "mentionsHealth": False, "mentionsSocialServices": False,
                "mentionsPrivacy": False, "mentionsPublicAdministration": False,
                "vulnerablePerson": False, "urgency": False, "ongoingHarm": False,
                "languageDetected": "und",
                "_warning": "AI extraction unavailable; conservative defaults applied",
            }
        }

    # Coerce: ensure all keys present, all booleans are real booleans
    BOOL_KEYS = [
        "mentionsChildren", "mentionsDiscrimination", "mentionsPrisons",
        "mentionsPolice", "mentionsHealth", "mentionsSocialServices",
        "mentionsPrivacy", "mentionsPublicAdministration",
        "vulnerablePerson", "urgency", "ongoingHarm",
    ]
    coerced = {}
    for k in BOOL_KEYS:
        v = result.get(k)
        if isinstance(v, str):
            v = v.lower() in ("true", "yes", "1")
        coerced[k] = bool(v)
    coerced["languageDetected"] = result.get("languageDetected") or "und"
    return {"output": coerced}


# ─────────────────────────────────────────────────────────────
# data.write@1
# ─────────────────────────────────────────────────────────────

async def handle_data_write(ctx: dict) -> dict:
    """
    Persist a classification record.

    For the Tiesibsargs package, the input arrives with topic/priority/department
    fields produced by the three DMN tables (merged into session variables).

    Input:  the merged session variables (topic, priority, slaHours, department,
            reviewerRole, plus the facet booleans and any original input fields)
    Output: { recordId, persistedAt }
    """
    inp = ctx.get("input") or {}
    session_id = ctx.get("session_id")
    document_id = inp.get("documentId")

    if not document_id:
        raise ValueError("data.write requires documentId in input (from document.fetch step)")

    raw_facets = {
        k: inp.get(k) for k in (
            "mentionsChildren", "mentionsDiscrimination", "mentionsPrisons",
            "mentionsPolice", "mentionsHealth", "mentionsSocialServices",
            "mentionsPrivacy", "mentionsPublicAdministration",
            "vulnerablePerson", "urgency", "ongoingHarm",
        ) if inp.get(k) is not None
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO complaint_classifications (
                   document_id, session_id, topic, topic_confidence,
                   priority, sla_hours, department, reviewer_role, raw_facets
               ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
               RETURNING id, created_at""",
            int(document_id), session_id,
            inp.get("topic"), float(inp.get("topicConfidence") or 0.0),
            inp.get("priority"), int(inp.get("slaHours") or 0),
            inp.get("department"), inp.get("reviewerRole"),
            json.dumps(raw_facets),
        )

        # Mirror to document metadata for visibility in OpenDMS UI
        await conn.execute(
            """UPDATE documents SET metadata = metadata || $1::jsonb
               WHERE id = $2""",
            json.dumps({
                "uapf_classification": {
                    "topic": inp.get("topic"),
                    "topicConfidence": inp.get("topicConfidence"),
                    "priority": inp.get("priority"),
                    "slaHours": inp.get("slaHours"),
                    "department": inp.get("department"),
                    "reviewerRole": inp.get("reviewerRole"),
                    "sessionId": session_id,
                }
            }),
            int(document_id),
        )

    return {
        "output": {
            "recordId": row["id"],
            "persistedAt": row["created_at"].isoformat(),
        }
    }


# ─────────────────────────────────────────────────────────────
# event.emit@1
# ─────────────────────────────────────────────────────────────

async def handle_event_emit(ctx: dict) -> dict:
    """
    Publish a domain event.

    Input:  { eventType: str, payload?: {...} } -- or the merged session variables,
            in which case eventType defaults to "iesniegums.classified" for the
            Tiesibsargs package.
    Output: { eventId, persistedAt }
    """
    inp = ctx.get("input") or {}
    document_id = inp.get("documentId")
    event_type = inp.get("eventType") or "iesniegums.classified"
    session_id = ctx.get("session_id")

    if not document_id:
        # Soft-fail: log but don't break the session
        logger.warning("event.emit called without documentId; skipping persistence")
        return {"output": {"eventId": None, "persistedAt": None, "_warning": "no documentId"}}

    payload = inp.get("payload") or {
        "topic": inp.get("topic"),
        "priority": inp.get("priority"),
        "slaHours": inp.get("slaHours"),
        "department": inp.get("department"),
        "reviewerRole": inp.get("reviewerRole"),
        "sessionId": session_id,
    }

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, $2, NULL, FALSE, $3)
               RETURNING id, created_at""",
            int(document_id), event_type, json.dumps(payload),
        )

    return {
        "output": {
            "eventId": row["id"],
            "eventType": event_type,
            "persistedAt": row["created_at"].isoformat(),
        }
    }


# ─────────────────────────────────────────────────────────────
# Registry — maps capability ref → handler
# ─────────────────────────────────────────────────────────────

HANDLERS = {
    "document/fetch": (handle_document_fetch, {"namespace": "document", "operation": "fetch", "version": 1}),
    "ai/redact":      (handle_ai_redact,      {"namespace": "ai",       "operation": "redact", "version": 1}),
    "ai/extract":     (handle_ai_extract,     {"namespace": "ai",       "operation": "extract","version": 1}),
    "data/write":     (handle_data_write,     {"namespace": "data",     "operation": "write",  "version": 1}),
    "event/emit":     (handle_event_emit,     {"namespace": "event",    "operation": "emit",   "version": 1}),
}

ADVERTISED_CAPABILITIES = [ref for _, ref in HANDLERS.values()]
