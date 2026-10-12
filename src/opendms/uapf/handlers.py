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
from datetime import datetime, timezone
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

async def _fetch_template(inp: dict) -> dict:
    from opendms.uapf.templates import latest
    tid = inp.get("templateId")
    if not tid:
        raise ValueError("template fetch needs templateId (from the SelectTemplate decision)")
    pool = await get_pool()
    async with pool.acquire() as conn:
        t = await latest(conn, tid)
    if not t:
        raise LookupError(f"Template not in the OpenDMS template library: {tid}")
    return {"output": {"templateId": t["template_id"], "templateVersion": t["version"],
                       "templateTitle": t["title"], "templateBody": t["body"],
                       "templateSynthetic": t["synthetic"]}}


async def handle_document_fetch(ctx: dict) -> dict:
    """
    Fetch a document's content + metadata.

    Input:  { documentDid?: str, documentId?: int }  (one is required)
    Output: { documentId, documentDid, title, content, mimeType, metadata, ...}
    """
    inp = ctx.get("input") or {}
    doc_did = inp.get("documentDid")
    doc_id = inp.get("documentId")

    # The package bound this step to the template library: fetch the current
    # version of the template the DMN picked, not the document.
    if str((ctx.get("target") or {}).get("id", "")).endswith("template-library"):
        return await _fetch_template(inp)

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

    # Fallback for documents without an attached file (e.g. seeded demo data
    # created via /api/uapf/seed-demo-data which only sets content_summary).
    # We want the AI extraction step to still have meaningful text to work on.
    if not content_text:
        content_text = (doc.get("content_summary") or "").strip()
        # Also include the title — it often carries the strongest topic signal
        if doc.get("title"):
            content_text = f"{doc['title']}\n\n{content_text}"

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

    # Deterministic PII regex signals — consumed by the
    # assess-personal-data-risk DMN decision. Computed always, on the raw
    # content, independent of the LLM redaction path below.
    from opendms.ai import _LV_PERSONAS_KODS, _EMAIL_RE, _PHONE_RE, _IBAN_RE
    _pk = bool(_LV_PERSONAS_KODS.search(content))
    _iban = bool(_IBAN_RE.search(content))
    _email = bool(_EMAIL_RE.search(content))
    _phone = bool(_PHONE_RE.search(content))
    _cats = [c for c in (("personas_kods" if _pk else None),
                         ("financial_account" if _iban else None),
                         ("email" if _email else None),
                         ("phone" if _phone else None)) if c]
    _pii = {
        "personasKodaPresent": _pk,
        "financialDataPresent": _iban,
        "contactDataPresent": _email or _phone,
        "piiCategoryCount": len(_cats),
        "detectedEntityTypes": _cats,
    }

    if not content:
        # Edge case: if document.fetch returned no content, propagate empty.
        return {"output": {"redactedContent": "", "detectedCategories": [], "languageDetected": "und", **_pii}}

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
                **_pii,
            }
        }

    return {"output": {**result, **_pii}}


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
  "mentionsChild": <bool>,
  "discriminationGround": <bool>,
  "socialRights": <bool>,
  "civilPolitical": <bool>,
  "publicAuthorityConduct": <bool>,
  "respondentType": "iestade|privatpersona|tiesa|nav-zinams",
  "courtPending": <bool>,
  "competentAuthorityKnown": <bool>,
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
  - mentionsChild: same as mentionsChildren
  - discriminationGround: a protected ground (sex, race, disability, age, religion,
    orientation ...) is named as the reason for unequal treatment
  - socialRights: social, economic or cultural rights (benefits, housing, health care,
    education, pensions, work)
  - civilPolitical: civil and political rights (fair trial, privacy, expression,
    assembly, liberty, property)
  - publicAuthorityConduct: the complaint is about how a state or municipal body acted
    or failed to act
  - respondentType: who the complaint is against — "iestade" (state or municipal body),
    "privatpersona" (private person or company), "tiesa" (a court or a court ruling),
    "nav-zinams" (cannot tell)
  - courtPending: the same matter is being heard in court now
  - competentAuthorityKnown: another body clearly competent for the matter is named or obvious

No markdown, no preamble, no commentary. Booleans must be true/false (not strings)."""


INCOMING_FACETS_PROMPT = """You read a document received by a Latvian public institution
(already PII-redacted) and answer a few yes/no questions about it.

Respond ONLY with JSON:
{
  "prasaAtbildi": <bool>,            // the sender asks for an answer, decision or action
  "irZinojums": <bool>,              // it is only for information (notice, report, FYI)
  "irTermins": <bool>,               // the text sets or mentions a deadline for the institution
  "terminsDokumenta": <bool>,        // the deadline is given in the document itself
  "iesniegumsNoFiziskasPersonas": <bool>, // the sender is a private individual (iesniegums)
  "kopsavilkums": "<one sentence in Latvian>"
}
No markdown, no commentary."""

INCOMING_BOOL_KEYS = ("prasaAtbildi", "irZinojums", "irTermins", "terminsDokumenta",
                      "iesniegumsNoFiziskasPersonas")


def _incoming_facets_by_keywords(text: str) -> dict:
    """Deterministic fallback when the model is unavailable."""
    t = (text or "").lower()
    no_answer = any(k in t for k in ("atbilde nav nepieciešama", "atbilde nav vajadzīga", "informācijai", "zināšanai"))
    asks = (not no_answer) and any(k in t for k in ("lūdzam", "lūdzu", "sniegt atbildi", "izvērtēšanai", "izskatīt"))
    deadline = any(k in t for k in ("līdz ", "termiņ"))
    return {
        "prasaAtbildi": asks,
        "irZinojums": no_answer or "paziņojum" in t,
        "irTermins": deadline,
        "terminsDokumenta": deadline,
        "iesniegumsNoFiziskasPersonas": "iesniegum" in t and "iestāde" not in t,
        "kopsavilkums": "",
        "_faktiAvots": "atslēgvārdi (valodas modelis nav pieejams)",
    }


async def _incoming_document_facets(text: str) -> dict:
    if not text:
        out = _incoming_facets_by_keywords("")
        out["_warning"] = "no text to extract from"
        return out
    result = await _complete_json(INCOMING_FACETS_PROMPT, f"--- DOKUMENTS ---\n{text}\n--- BEIGAS ---")
    if not result:
        return _incoming_facets_by_keywords(text)
    out = {}
    for k in INCOMING_BOOL_KEYS:
        v = result.get(k)
        if isinstance(v, str):
            v = v.lower() in ("true", "yes", "1", "jā")
        out[k] = bool(v)
    out["kopsavilkums"] = str(result.get("kopsavilkums") or "")[:400]
    out["_faktiAvots"] = "valodas modelis"
    return out


P1_FALLBACK = {
    "mentionsChild": False, "discriminationGround": False, "socialRights": False,
    "civilPolitical": False, "publicAuthorityConduct": False,
    "respondentType": "nav-zinams", "courtPending": False, "competentAuthorityKnown": False,
}


async def handle_ai_extract(ctx: dict) -> dict:
    """
    Extract structured facets from document text.

    Schema-driven: the invoking BPMN task's uapf:schemaRef selects the
    extraction contract:
      - .../vdvc-semantic-summary.schema.json -> VDVC semantic metadata
        (Primary Topic, Summary, Keywords ... — the Generate Metadata flow)
      - anything else -> Tiesibsargs triage facets (mentions*, urgency ...
        — the iesnieguma-izskatisana classification DMN)

    Input: { content: str, redactedContent?: str }
    """
    inp = ctx.get("input") or {}
    schema_ref = ctx.get("schema_ref") or ""
    # Prefer the redacted form if both are present
    text = inp.get("redactedContent") or inp.get("content") or ""

    MAX_CHARS = 15000
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS]

    # ---- VDVC semantic-metadata extraction (selected by uapf:schemaRef) ----
    if "semantic-summary" in schema_ref or "vdvc" in schema_ref.lower():
        if not text:
            return {"output": {"_warning": "no text to extract from"}}
        from opendms.ai import _get_semantic_prompt
        prompt = await _get_semantic_prompt()
        sem = await _complete_json(
            prompt, f"--- DOCUMENT TEXT ---\n{text}\n--- END ---"
        )
        if not sem:
            return {"output": {"_warning": "AI semantic extraction unavailable",
                               "aiConfidenceScore": 0.0, "outputPiiErrorCount": 0}}
        # Surface the human-validation-gate DMN inputs as flat session
        # variables: outputPiiErrorCount is the deterministic post-extraction
        # PII re-scan, aiConfidenceScore is lifted out of semanticSummary.
        from opendms.ai import scan_response_for_pii
        _ss = sem.get("semanticSummary") or {}
        try:
            _conf = float(_ss.get("aiConfidenceScore"))
        except (TypeError, ValueError):
            _conf = 0.0
        _pii_errs = scan_response_for_pii(sem)
        return {"output": {
            **sem,
            "aiConfidenceScore": _conf,
            "outputPiiErrorCount": len(_pii_errs),
            "detectedLanguage": _ss.get("detectedLanguage") or "und",
        }}

    # ---- Incoming-document facets for the DVS flows (VDVC/RS sanemto) ----
    if "ienakosa-dokumenta-pazimes" in schema_ref:
        return {"output": await _incoming_document_facets(text)}

    # ---- Tiesibsargs triage facets (default contract) ----
    if not text:
        return {
            "output": {
                "mentionsChildren": False, "mentionsDiscrimination": False,
                "mentionsPrisons": False, "mentionsPolice": False,
                "mentionsHealth": False, "mentionsSocialServices": False,
                "mentionsPrivacy": False, "mentionsPublicAdministration": False,
                "vulnerablePerson": False, "urgency": False, "ongoingHarm": False,
                **P1_FALLBACK,
                "languageDetected": "und",
                "_warning": "no text to extract from",
            }
        }

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
                **P1_FALLBACK,
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
    # P1 facets (lv.tiesibsargs.iesnieguma-virzisana) — defaulted from the
    # triage facets when the model leaves them out.
    p1_defaults = {
        "mentionsChild": coerced["mentionsChildren"],
        "discriminationGround": coerced["mentionsDiscrimination"],
        "socialRights": coerced["mentionsSocialServices"] or coerced["mentionsHealth"],
        "civilPolitical": coerced["mentionsPrivacy"] or coerced["mentionsPolice"] or coerced["mentionsPrisons"],
        "publicAuthorityConduct": coerced["mentionsPublicAdministration"],
        "courtPending": False,
        "competentAuthorityKnown": False,
    }
    for k, dflt in p1_defaults.items():
        v = result.get(k)
        if isinstance(v, str):
            v = v.lower() in ("true", "yes", "1")
        coerced[k] = bool(v) if v is not None else dflt
    rt = str(result.get("respondentType") or "").strip().lower()
    coerced["respondentType"] = rt if rt in ("iestade", "privatpersona", "tiesa", "nav-zinams") else (
        "iestade" if coerced["publicAuthorityConduct"] else "nav-zinams")
    coerced["languageDetected"] = result.get("languageDetected") or "und"
    return {"output": coerced}


# ─────────────────────────────────────────────────────────────
# data.write@1
# ─────────────────────────────────────────────────────────────

# Decision outputs of the lab process packages, recorded as they come.
PROCESS_RESULT_KEYS = (
    # lv.tiesibsargs.iesnieguma-virzisana
    "topic", "confidence", "topicConfidence", "jurisdiction", "reason", "priority",
    "responseDays", "slaHours", "outcome", "department", "role", "reviewerRole",
    # VDVC / RS incoming flows
    "klasifikacijasIndekss", "klasifikacijasNosaukums", "strukturvieniba", "loma",
    "plusma", "termins", "glabasanasTermins",
    # P2 response draft
    "templateId", "templateVersion", "missingElements",
    # human step
    "decision", "comment",
)


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

    # Whatever the package's DMN tables decided, as plain fields — so a process
    # changed in ProcessGit shows its new outputs without host changes.
    decision_fields = {
        k: inp.get(k) for k in PROCESS_RESULT_KEYS if inp.get(k) is not None
    }
    sla_hours = inp.get("slaHours")
    if sla_hours is None and inp.get("responseDays") is not None:
        sla_hours = int(float(inp.get("responseDays")) * 24)
    reviewer_role = inp.get("reviewerRole") or inp.get("role") or inp.get("loma")
    topic_conf = inp.get("topicConfidence") if inp.get("topicConfidence") is not None else inp.get("confidence")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Pre-create uapf_sessions row to satisfy FK. The run-now handler in
        # uapf_admin.py only inserts the session row AFTER engine.start_session
        # returns, but the engine calls back to this capability DURING the
        # start_session call — so the session row doesn't exist yet. Insert
        # with state='running'; the run-now handler will UPDATE it on return.
        if session_id:
            # Placeholders for package_id/process_id (NOT NULL) — the run-now
            # handler's ON CONFLICT UPDATE overwrites them with real values.
            await conn.execute(
                """INSERT INTO uapf_sessions
                       (session_id, document_id, package_id, process_id, state, started_at)
                   VALUES ($1, $2, '<pending>', '<pending>', 'running', NOW())
                   ON CONFLICT (session_id) DO NOTHING""",
                session_id, int(document_id),
            )

        row = None
        if inp.get("topic") and inp.get("priority"):
            row = await conn.fetchrow(
              """INSERT INTO complaint_classifications (
                     document_id, session_id, topic, topic_confidence,
                     priority, sla_hours, department, reviewer_role, raw_facets
                 ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                 RETURNING id, created_at""",
              int(document_id), session_id,
              inp.get("topic"), float(topic_conf or 0.0),
              inp.get("priority"), int(sla_hours or 0),
              inp.get("department"), reviewer_role,
              json.dumps(raw_facets),
            )

        if inp.get("draftText"):
            await conn.execute(
                "UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
                json.dumps({"uapf_draft": {
                    "templateId": inp.get("templateId"), "templateVersion": inp.get("templateVersion"),
                    "templateSynthetic": inp.get("templateSynthetic"),
                    "text": inp.get("draftText"), "source": inp.get("draftSource"),
                    "elementsChecked": inp.get("elementsChecked"),
                    "missingElements": inp.get("missingElements"),
                    "sessionId": session_id,
                }}), int(document_id))

        # Mirror to document metadata for visibility in OpenDMS UI
        await conn.execute(
            """UPDATE documents SET metadata = metadata || $1::jsonb
               WHERE id = $2""",
            json.dumps({
                "uapf_classification": {
                    "topic": inp.get("topic"),
                    "topicConfidence": topic_conf,
                    "priority": inp.get("priority"),
                    "slaHours": sla_hours,
                    "department": inp.get("department"),
                    "reviewerRole": reviewer_role,
                    "sessionId": session_id,
                },
                "uapf_result": {
                    **decision_fields,
                    "sessionId": session_id,
                    "stepId": ctx.get("step_id"),
                    "recordedAt": datetime.now(timezone.utc).isoformat(),
                },
            }),
            int(document_id),
        )

    return {
        "output": {
            "recordId": row["id"] if row else None,
            "persistedAt": (row["created_at"] if row else datetime.now(timezone.utc)).isoformat(),
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
    step = ctx.get("step_id")
    event_type = inp.get("eventType") or (f"uapf.{step}" if step else "iesniegums.classified")
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
        **{k: inp.get(k) for k in PROCESS_RESULT_KEYS if inp.get(k) is not None},
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
# Dokumentu metadatu standarts v2.0 — identifier, storage, package
#
# The rules (document type, nomenclature case, retention, access) come from
# the process package — typically its DMN tables — as session variables. The
# host only applies the standard: identifier format, package layout, schemas.
# ─────────────────────────────────────────────────────────────

def _document_id(ctx: dict) -> int:
    inp = ctx.get("input") or {}
    doc_id = inp.get("documentId")
    if doc_id is None:
        raise ValueError("documentId is required (it is in the session input of every trigger)")
    return int(doc_id)


async def handle_identifier_assign(ctx: dict) -> dict:
    """
    identifier.assign@1 — give the document its LV-DOK identifier and each
    file its LV-DATNE identifier; record DokumentsRegistrets. Idempotent.

    Input:  { documentId }
    Output: { dokumentaId, datnuId[], jaunsIdentifikators, orgKods }
    """
    from opendms.standard.service import assign_identifiers
    return {"output": await assign_identifiers(_document_id(ctx))}


async def handle_storage_prepare(ctx: dict) -> dict:
    """
    storage.prepare@1 — create the package folder in document storage and
    copy the document's files into its datnes/ folder.

    Input:  { documentId }
    Output: { pakotnesMape, pakotnesAtslega, datnes[] }
    """
    from opendms.standard.service import prepare_storage
    return {"output": await prepare_storage(_document_id(ctx))}


async def handle_package_build(ctx: dict) -> dict:
    """
    package.build@1 — write metadati.xml, izsekosana.xml and SHA256SUMS,
    validate the package against the standard's schemas and file checksums.
    Fails the step if the package does not conform.

    Input:  { documentId, plus rule variables from the process:
              dokumentaVeidaKods, dokumentaVeidaNosaukums, lietasIndekss,
              lietasNosaukums, glabasanasTerminsGadi, glabasanasPastavigi,
              glabasanasTriggeris, iznicinasanasDarbiba, informacijasStatuss,
              saturPersonasDatus, piekluvesPamatojums, nomenklaturasShemasId }
    Output: { pakotnesMape, dokumentaId, datnes[], derigs, problemas[] }
    """
    from opendms.standard.service import build_package, rules_from_variables
    inp = ctx.get("input") or {}
    return {"output": await build_package(_document_id(ctx), rules_from_variables(inp))}


async def handle_document_list(ctx: dict) -> dict:
    """
    Recent documents of this organisation, newest first. Read-only.

    Input:  { limit?: int (1-50, default 10), status?: str, query?: str (title contains),
              sinceDays?: int }
    Output: { total, returned, documents: [{ documentId, registrationNumber, title, status,
              createdAt, documentUid, sender, files }] }
    """
    from opendms.org_context import get_default_org

    inp = ctx.get("input") or {}
    try:
        limit = max(1, min(50, int(inp.get("limit") or 10)))
    except (TypeError, ValueError):
        limit = 10
    org = await get_default_org()
    where, args = [], []
    if org:
        args.append(org["id"]); where.append(f"d.org_id = ${len(args)}")
    if inp.get("status"):
        args.append(str(inp["status"])); where.append(f"d.status = ${len(args)}")
    if inp.get("query"):
        args.append(f"%{inp['query']}%"); where.append(f"d.title ILIKE ${len(args)}")
    if inp.get("sinceDays"):
        args.append(int(inp["sinceDays"])); where.append(f"d.created_at >= NOW() - make_interval(days => ${len(args)})")
    cond = ("WHERE " + " AND ".join(where)) if where else ""

    pool = await get_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(f"SELECT COUNT(*) FROM documents d {cond}", *args)
        rows = await conn.fetch(
            f"""SELECT d.id, d.registration_number, d.title, d.status, d.created_at, d.doc_uid,
                       d.metadata->'sender'->>'name' AS sender,
                       (SELECT COUNT(*) FROM document_files f WHERE f.document_id = d.id) AS files
                  FROM documents d {cond}
                 ORDER BY d.created_at DESC, d.id DESC
                 LIMIT {limit}""", *args)
    docs = [{
        "documentId": r["id"], "registrationNumber": r["registration_number"], "title": r["title"],
        "status": r["status"], "createdAt": r["created_at"].isoformat() if r["created_at"] else None,
        "documentUid": r["doc_uid"], "sender": r["sender"], "files": r["files"],
    } for r in rows]
    return {"output": {"total": total, "returned": len(docs), "documents": docs}}


# ─────────────────────────────────────────────────────────────
# ai.draft@1 / ai.verify@1 — response draft from a template (P2)
# ─────────────────────────────────────────────────────────────

class _Blank(dict):
    def __missing__(self, key):
        return "[…]"


ELEMENT_MARKERS = {
    "rekviziti": "Rekvizīti",
    "normativa-atsauce": "Normatīvā atsauce",
    "parsudzibas-kartiba": "Pārsūdzības kārtība",
    "kompetenta-iestade": "Kompetentā iestāde",
}

VALUE_LV = {
    "bernu-tiesibas": "bērnu tiesības", "diskriminacijas-noversana": "diskriminācijas novēršana",
    "laba-parvaldiba": "laba pārvaldība", "socialas-tiesibas": "sociālās tiesības",
    "civilas-tiesibas": "civilās un politiskās tiesības", "neskaidrs": "neskaidrs jautājums",
}


async def handle_ai_draft(ctx: dict) -> dict:
    """Fill the template with the case facts; the model writes one neutral
    sentence on the substance of the complaint (from redacted text only)."""
    inp = ctx.get("input") or {}
    body = inp.get("templateBody") or ""
    if not body:
        raise ValueError("ai.draft needs templateBody (from the template fetch step)")
    values = _Blank(
        datums=datetime.now(timezone.utc).strftime("%d.%m.%Y"),
        registracijas_nr=inp.get("registrationNumber") or "[…]",
        joma=VALUE_LV.get(inp.get("topic"), inp.get("topic") or "[…]"),
        nodala=inp.get("department") or "[…]",
        termins=inp.get("responseDays") or "[…]",
        pamatojums=(inp.get("reason") or "[…]").lower(),
        kompetenta_iestade=inp.get("competentAuthority") or "[norādīt kompetento iestādi]",
    )
    draft = body.format_map(values)

    substance, source = "", "veidne"
    doc_id = inp.get("documentId")
    if doc_id:
        try:
            fetched = (await handle_document_fetch({"input": {"documentId": doc_id}}))["output"]
            red = (await handle_ai_redact({"input": {"content": fetched.get("content") or ""}}))["output"]
            text = (red.get("redactedContent") or "")[:6000]
            if text:
                res = await _complete_json(
                    "Tu raksti valsts iestādes atbildes projektu. Atbildi tikai ar JSON "
                    '{"butiba": "<viens neitrāls teikums latviski par iesnieguma būtību, bez personas datiem>"}',
                    f"--- IESNIEGUMS (personas dati aizklāti) ---\n{text}\n--- BEIGAS ---")
                if res and res.get("butiba"):
                    substance, source = str(res["butiba"])[:400], "veidne + valodas modelis"
        except Exception as e:  # the draft still stands on the template alone
            logger.warning("ai.draft: substance sentence skipped: %s", e)
    if substance:
        # after the Rekvizīti block (or at the end if the template has none)
        at = draft.find("\n\n", max(draft.find("Rekvizīti"), 0))
        line = f"\n\nIesnieguma būtība: {substance}"
        draft = draft[:at] + line + draft[at:] if at >= 0 else draft + line
    return {"output": {"draftText": draft, "draftSource": source}}


async def handle_ai_verify(ctx: dict) -> dict:
    """Deterministic check that the draft contains every required element."""
    inp = ctx.get("input") or {}
    draft = inp.get("draftText") or ""
    required = inp.get("element") or []
    if isinstance(required, str):
        required = [required]
    missing = [e for e in required if ELEMENT_MARKERS.get(e, e).lower() not in draft.lower()]
    return {"output": {"elementsChecked": required, "missingElements": missing,
                       "elementsOk": not missing}}


# ─────────────────────────────────────────────────────────────
# task.request@1 — a human step (BPMN userTask)
#
# The host accepts the task and answers {status: "pending"}; the engine
# suspends the session. The reviewer decides in OpenDMS, which resumes the
# session with {decision, comment} (see routers/uapf_admin.py).
# ─────────────────────────────────────────────────────────────

async def handle_task_request(ctx: dict) -> dict:
    inp = ctx.get("input") or {}
    session_id = ctx.get("session_id")
    step_id = ctx.get("step_id")
    document_id = inp.get("documentId")
    if not document_id:
        raise ValueError("task.request requires documentId in input")

    proposal = {k: inp.get(k) for k in PROCESS_RESULT_KEYS if inp.get(k) is not None}
    review = {
        "status": "gaida",
        "sessionId": session_id,
        "stepId": step_id,
        "role": inp.get("role") or inp.get("loma") or inp.get("reviewerRole"),
        "department": inp.get("department") or inp.get("strukturvieniba"),
        "proposal": proposal,
        "requestedAt": datetime.now(timezone.utc).isoformat(),
    }
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE documents SET metadata = metadata || $1::jsonb WHERE id = $2",
            json.dumps({"uapf_review": review}), int(document_id),
        )
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, 'uapf.review.requested', NULL, FALSE, $2)""",
            int(document_id), json.dumps(review),
        )
    return {"output": {"status": "pending", "reviewTaskId": f"{session_id}:{step_id}"}}


# ─────────────────────────────────────────────────────────────
# vc.issue@1 — attest the document's registration in the register
#
# A document created through OpenDMS is normally already in the register
# (DocumentCreated VC, did:web:dokregistrs…:doc:<uuid>). Then this step only
# confirms it. If it is not, the SDK registers it now.
# ─────────────────────────────────────────────────────────────

async def handle_vc_issue(ctx: dict) -> dict:
    inp = ctx.get("input") or {}
    document_id = inp.get("documentId")
    if not document_id:
        raise ValueError("vc.issue requires documentId in input")
    pool = await get_pool()
    async with pool.acquire() as conn:
        doc = await conn.fetchrow(
            "SELECT id, title, registration_number, doc_did, metadata FROM documents WHERE id = $1",
            int(document_id))
    if not doc:
        raise LookupError(f"Document not found: {document_id}")
    if doc["doc_did"]:
        return {"output": {"documentDid": doc["doc_did"], "vcIssued": True, "vcEvent": "DocumentCreated",
                           "jauns": False}}

    from opendms import sdk_client
    res = await sdk_client.create_document(
        title=doc["title"], classification=str(inp.get("klasifikacijasIndekss") or ""),
        reg_number=doc["registration_number"] or "", metadata={}, trace_id=ctx.get("session_id"),
        include_error_payload=True)
    status = (res or {}).get("_meta", {}).get("status_code", 502)
    did = (res or {}).get("docDid") if status in (200, 201) else None
    if not did:
        return {"output": {"documentDid": None, "vcIssued": False,
                           "_warning": f"register did not accept the document (HTTP {status})"}}
    async with pool.acquire() as conn:
        await conn.execute("UPDATE documents SET doc_did = $1 WHERE id = $2", did, int(document_id))
        await conn.execute(
            """INSERT INTO document_events (document_id, event_type, actor_id, vc_submitted, details)
               VALUES ($1, 'DocumentCreated', NULL, TRUE, $2)""",
            int(document_id), json.dumps({"sdk_did": did, "sessionId": ctx.get("session_id")}))
    return {"output": {"documentDid": did, "vcIssued": True, "vcEvent": "DocumentCreated", "jauns": True}}


# ─────────────────────────────────────────────────────────────
# classification.lookup@1 — SIMULATED until the real scheme is connected
# ─────────────────────────────────────────────────────────────

async def handle_classification_lookup(ctx: dict) -> dict:
    from opendms.uapf.classification_sim import lookup

    inp = ctx.get("input") or {}
    parts = [inp.get("title") or "", inp.get("redactedContent") or inp.get("content") or ""]
    summary = inp.get("semanticSummary")
    if isinstance(summary, dict):
        parts.append(str(summary.get("summary") or ""))
    return {"output": lookup("\n".join(parts))}


# ─────────────────────────────────────────────────────────────
# Registry — maps capability ref → handler
# ─────────────────────────────────────────────────────────────

HANDLERS = {
    "document/list":  (handle_document_list,  {"namespace": "document", "operation": "list",  "version": 1,
                                               "summary": "List this organisation's recent documents (number, title, status, date, sender). Use to answer what is new."}),
    "document/fetch": (handle_document_fetch, {"namespace": "document", "operation": "fetch", "version": 1,
                                               "summary": "Read one document's metadata and text by documentId."}),
    "ai/redact":      (handle_ai_redact,      {"namespace": "ai",       "operation": "redact", "version": 1}),
    "ai/extract":     (handle_ai_extract,     {"namespace": "ai",       "operation": "extract","version": 1}),
    "data/write":     (handle_data_write,     {"namespace": "data",     "operation": "write",  "version": 1}),
    "event/emit":     (handle_event_emit,     {"namespace": "event",    "operation": "emit",   "version": 1}),
    "identifier/assign": (handle_identifier_assign, {"namespace": "identifier", "operation": "assign",  "version": 1}),
    "storage/prepare":   (handle_storage_prepare,   {"namespace": "storage",    "operation": "prepare", "version": 1}),
    "package/build":     (handle_package_build,     {"namespace": "package",    "operation": "build",   "version": 1}),
    "vc/issue":          (handle_vc_issue,          {"namespace": "vc",         "operation": "issue",   "version": 1,
                                                     "summary": "Make sure the document's registration is attested in the document register (DID/VC)."}),
    "ai/draft":          (handle_ai_draft,          {"namespace": "ai",         "operation": "draft",   "version": 1,
                                                     "summary": "Draft a response from a library template and the case facts."}),
    "ai/verify":         (handle_ai_verify,         {"namespace": "ai",         "operation": "verify",  "version": 1,
                                                     "summary": "Check a draft contains the required elements."}),
    "task/request":      (handle_task_request,      {"namespace": "task",       "operation": "request", "version": 1,
                                                     "summary": "Hand a step to a person; the session waits for their decision."}),
    "classification/lookup": (handle_classification_lookup, {"namespace": "classification", "operation": "lookup", "version": 1,
                                                     "summary": "Find the classification scheme entry, unit and retention (SIMULATED scheme)."}),
}


# ─────────────────────────────────────────────────────────────
# connector/* — external system connectors
#
# Generated from the connector registry rather than hand-listed, so the host
# manifest cannot drift away from the drivers that actually exist. Placeholder
# connectors are registered too: a process author needs to see the capability
# in the manifest and get a structured "not implemented, here is what is
# missing" answer, instead of a 422 that looks like a typo in the BPMN.
# ─────────────────────────────────────────────────────────────

def _connector_handler(capability_key: str):
    async def handler(ctx: dict) -> dict:
        from opendms.connectors.runtime import run_capability

        result = await run_capability(
            capability_key,
            ctx.get("input") or {},
            {
                "session_id": ctx.get("session_id"),
                "step_id": ctx.get("step_id"),
                "trace_id": ctx.get("session_id"),
            },
        )
        return {"output": result.as_dict()}

    handler.__name__ = "handle_" + capability_key.replace("/", "_").replace(".", "_").replace("-", "_")
    return handler


def _register_connector_capabilities() -> None:
    from opendms.connectors import advertised_capabilities

    for cap in advertised_capabilities():
        key = f"{cap['namespace']}/{cap['operation']}"
        HANDLERS[key] = (_connector_handler(key), dict(cap))


_register_connector_capabilities()

ADVERTISED_CAPABILITIES = [ref for _, ref in HANDLERS.values()]
