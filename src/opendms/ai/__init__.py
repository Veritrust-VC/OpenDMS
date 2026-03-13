"""
OpenDMS AI Intelligence — user-facing AI capabilities.

Provides:
  - Document classification suggestion (when creating/receiving documents)
  - Routing recommendation (who should handle this document)
  - Content summarization (generate document summary from file content)

Uses LLM via OpenAI-compatible API (Anthropic, OpenAI, Ollama).
Falls back to rule-based logic when LLM is unavailable.
"""

import json, logging, os, re, hashlib
import time as _time
from typing import Optional
import httpx

logger = logging.getLogger(__name__)

# ── LLM Configuration ──
PROVIDER = os.getenv("OPENDMS_LLM_PROVIDER", "anthropic")
API_KEY = os.getenv("OPENDMS_LLM_API_KEY", "")
BASE_URL = os.getenv("OPENDMS_LLM_BASE_URL", "")
MODEL = os.getenv("OPENDMS_LLM_MODEL", "")

_DEFAULTS = {
    "anthropic": {"base_url": "https://api.anthropic.com", "model": "claude-sonnet-4-20250514"},
    "openai": {"base_url": "https://api.openai.com", "model": "gpt-4o-mini"},
    "ollama": {"base_url": "http://localhost:11434", "model": "llama3.1"},
}


def is_configured() -> bool:
    return bool(API_KEY) or PROVIDER == "ollama"


def _cfg():
    d = _DEFAULTS.get(PROVIDER, _DEFAULTS["anthropic"])
    return {"provider": PROVIDER, "api_key": API_KEY, "base_url": BASE_URL or d["base_url"], "model": MODEL or d["model"]}


async def _complete(system: str, user_msg: str, temperature=0.2, max_tokens=1500) -> Optional[str]:
    cfg = _cfg()
    if not cfg["api_key"] and cfg["provider"] != "ollama":
        return None
    try:
        if cfg["provider"] == "anthropic":
            async with httpx.AsyncClient(timeout=60.0) as c:
                r = await c.post(f"{cfg['base_url']}/v1/messages", headers={
                    "x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01", "content-type": "application/json",
                }, json={"model": cfg["model"], "max_tokens": max_tokens, "temperature": temperature,
                         "system": system, "messages": [{"role": "user", "content": user_msg}]})
                r.raise_for_status()
                return r.json()["content"][0]["text"]
        else:
            url = f"{cfg['base_url']}/api/chat" if cfg["provider"] == "ollama" else f"{cfg['base_url']}/v1/chat/completions"
            headers = {"content-type": "application/json"}
            if cfg["api_key"]:
                headers["authorization"] = f"Bearer {cfg['api_key']}"
            async with httpx.AsyncClient(timeout=60.0) as c:
                r = await c.post(url, headers=headers, json={
                    "model": cfg["model"], "temperature": temperature, "max_tokens": max_tokens,
                    "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                })
                r.raise_for_status()
                data = r.json()
                return data.get("message", {}).get("content") or data.get("choices", [{}])[0].get("message", {}).get("content")
    except Exception as e:
        logger.error("LLM error: %s", e)
        return None


async def _complete_json(system: str, user_msg: str) -> Optional[dict]:
    raw = await _complete(system, user_msg, temperature=0.1)
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
    try:
        return json.loads(text.strip())
    except Exception:
        return None


# ═══════════════════════════════════════════
# Classification Suggestion
# ═══════════════════════════════════════════

async def suggest_classification(title: str, content_summary: str = "",
                                  classifications: list = None) -> Optional[dict]:
    """
    Suggest document classification based on title and content.

    Args:
        title: Document title
        content_summary: Brief content description
        classifications: Available classification codes [{code, name, description}]

    Returns:
        {suggested_code, suggested_name, confidence, reasoning, alternatives}
    """
    if not is_configured():
        return None

    cls_context = ""
    if classifications:
        cls_context = "\n\nAvailable classifications:\n" + "\n".join(
            f"  {c.get('code', '?')}: {c.get('name', '?')}" + (f" — {c.get('description', '')}" if c.get('description') else "")
            for c in classifications[:50]  # Limit context
        )

    system = f"""You are a document classification assistant. Given a document title and optional
content summary, suggest the most appropriate classification from the organization's schema.
{cls_context}

Respond ONLY with JSON:
{{
  "suggested_code": "classification code",
  "suggested_name": "classification name",
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation",
  "alternatives": [{{"code": "...", "name": "...", "reason": "..."}}]
}}"""

    user = f"Title: {title}"
    if content_summary:
        user += f"\nContent: {content_summary}"

    result = await _complete_json(system, user)
    if result:
        result["ai_generated"] = True
    return result


# ═══════════════════════════════════════════
# Routing Recommendation
# ═══════════════════════════════════════════

async def suggest_routing(title: str, classification: str = "",
                          sender: str = "", users: list = None) -> Optional[dict]:
    """
    Suggest who should handle an incoming document.

    Args:
        title: Document title
        classification: Classification code/name
        sender: Sender organization name
        users: Available assignees [{full_name, department, role}]

    Returns:
        {recommended_user, recommended_department, priority, reasoning}
    """
    if not is_configured():
        return None

    users_ctx = ""
    if users:
        users_ctx = "\n\nAvailable assignees:\n" + "\n".join(
            f"  {u.get('full_name', '?')} — {u.get('department', '?')} ({u.get('role', '?')})"
            for u in users[:30]
        )

    system = f"""You are a document routing assistant. Recommend who should handle an incoming document
based on its title, classification, and sender.
{users_ctx}

Respond ONLY with JSON:
{{
  "recommended_user": "full name of best assignee",
  "recommended_department": "department",
  "priority": "low|normal|high|urgent",
  "confidence": 0.0 to 1.0,
  "reasoning": "brief explanation"
}}"""

    user = f"Title: {title}\nClassification: {classification or 'unclassified'}\nSender: {sender or 'unknown'}"

    result = await _complete_json(system, user)
    if result:
        result["ai_generated"] = True
    return result


# ═══════════════════════════════════════════
# Content Summarization
# ═══════════════════════════════════════════

async def summarize_content(text: str, max_length: int = 200) -> Optional[dict]:
    """
    Generate a brief summary of document content.

    Args:
        text: Document text content
        max_length: Target summary length in words

    Returns:
        {summary, key_topics, language_detected}
    """
    if not is_configured() or not text:
        return None

    system = f"""Summarize the following document content in a concise paragraph (max {max_length} words).
Also identify key topics and detect the language.

Respond ONLY with JSON:
{{
  "summary": "concise summary",
  "key_topics": ["topic1", "topic2"],
  "language_detected": "en|lv|etc",
  "word_count": number
}}"""

    # Truncate very long texts
    if len(text) > 10000:
        text = text[:10000] + "\n\n[... truncated ...]"

    result = await _complete_json(system, text)
    if result:
        result["ai_generated"] = True
    return result


# ═══════════════════════════════════════════
# VDVC Semantic Metadata Generation (v1.1)
# ═══════════════════════════════════════════

# PII detection patterns
_LV_PERSONAS_KODS = re.compile(r'\b\d{6}-\d{5}\b')
_EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
_PHONE_RE = re.compile(r'(?:\+371|00371)?\s?\d{8}')
_IBAN_RE = re.compile(r'\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b')

_SEMANTIC_SYSTEM_PROMPT = """You are a government document metadata extraction agent operating within the Latvian public administration document management ecosystem (VDVC).

Your task: analyze the provided document text and generate a structured semantic summary conforming to the VDVC metadata schema v1.1, section 13.

## OUTPUT FORMAT
Respond ONLY with a JSON object. No markdown, no explanations, no preamble.

## MANDATORY GUARDRAILS — VIOLATIONS ARE CRITICAL FAILURES

### GDPR / Personal Data Protection (Regula 2016/679)
1. NEVER include personal names in any output field.
2. NEVER include personal identification codes (personas kods).
3. NEVER include addresses, phone numbers, email addresses, or bank accounts.
4. NEVER include health data, biometric data, or GDPR Art. 9 data.
5. If personal data present, set personalDataRisk to MEDIUM or HIGH, list entity TYPES only.
6. Refer to individuals by ROLE only (e.g., "iesniedzējs" not the actual name).

### EU AI Act Compliance (2024/1689, Art. 13)
7. Always set summarySource to "AI".
8. Always include aiConfidenceScore (0.0–1.0).
9. Always include aiModelVersion with your exact model identifier.

### Content Accuracy
10. Do NOT fabricate information not in the document.
11. If text too short/unclear, set aiConfidenceScore below 0.3.
12. Respond in the SAME LANGUAGE as the document (default: Latvian).

## JSON SCHEMA
{
  "semanticSummary": {
    "primaryTopic": "string", "subTopics": ["string"],
    "summary": "string — max 500 words, NO personal data",
    "documentPurpose": "string", "requestedAction": "string",
    "involvedPartyTypes": ["string — party TYPES not names"],
    "geographicScope": "string", "sectorTags": ["string"],
    "legalDomain": "string",
    "estimatedRiskLevel": "LOW|MEDIUM|HIGH|CRITICAL",
    "urgencyLevel": "LOW|NORMAL|HIGH|URGENT",
    "keywords": ["string — max 20, NO personal data"],
    "detectedLanguage": "ISO 639-1",
    "summarySource": "AI",
    "aiConfidenceScore": 0.0-1.0,
    "aiModelVersion": "your-model-id",
    "humanValidationStatus": "PENDING"
  },
  "sensitivityControl": {
    "personalDataRisk": "NONE|LOW|MEDIUM|HIGH",
    "allowCentralization": true,
    "redactionLevel": "NONE|PARTIAL|FULL",
    "accessRestrictionBasis": "string",
    "classifiedInformation": false,
    "detectedEntityTypes": ["string — entity TYPE names only"]
  }
}"""


async def _get_semantic_prompt() -> str:
    """Load semantic system prompt from DB with hardcoded fallback."""
    try:
        from opendms.routers.ai_instructions import load_instruction

        prompt = await load_instruction("semantic_summary.system_prompt")
        if not prompt:
            return _SEMANTIC_SYSTEM_PROMPT

        schema = await load_instruction("semantic_summary.output_schema")
        if schema:
            return f"{prompt}\n\n## JSON SCHEMA\n{schema}"
        return prompt
    except Exception:
        return _SEMANTIC_SYSTEM_PROMPT


async def _get_user_message(title: str, doc_type: str, reg_number: str, org_name: str, text: str) -> str:
    """Build semantic user message from DB template with fallback."""
    try:
        from opendms.routers.ai_instructions import load_instruction

        template = await load_instruction("semantic_summary.user_message_template")
        if template:
            return (
                template
                .replace("{title}", title)
                .replace("{docType}", doc_type or "unknown")
                .replace("{regNumber}", reg_number or "")
                .replace("{orgName}", org_name or "")
                .replace("{documentText}", text)
            )
    except Exception:
        pass

    return f"""Document Title: {title}
Document Type: {doc_type or 'unknown'}
Registration Number: {reg_number}
Organization: {org_name}

--- DOCUMENT TEXT ---
{text}
--- END ---

Generate the semantic summary JSON for this document."""


def anonymize_text(text: str) -> tuple[str, bool]:
    """Replace PII with placeholders. Returns (anonymized_text, was_anonymized)."""
    original = text
    counter = [0]

    def _replace(pattern, label):
        nonlocal text

        def repl(m):
            counter[0] += 1
            return f"[{label}_{counter[0]}]"

        text = pattern.sub(repl, text)

    _replace(_LV_PERSONAS_KODS, "PERSONAS_KODS")
    _replace(_EMAIL_RE, "EPASTS")
    _replace(_PHONE_RE, "TALRUNIS")
    _replace(_IBAN_RE, "IBAN")
    return text, text != original


def scan_response_for_pii(data: dict) -> list[str]:
    """Post-generation PII scan on AI output. Returns list of error strings."""
    errors = []
    ss = data.get("semanticSummary", {})
    for field in ["primaryTopic", "summary", "documentPurpose", "requestedAction", "legalDomain"]:
        val = ss.get(field, "")
        if not isinstance(val, str):
            continue
        if _LV_PERSONAS_KODS.search(val):
            errors.append(f"PII in {field}: personas kods")
        if _EMAIL_RE.search(val):
            errors.append(f"PII in {field}: email")
    for kw in ss.get("keywords", []):
        if _LV_PERSONAS_KODS.search(str(kw)):
            errors.append("PII in keywords")
    return errors


async def generate_semantic_metadata(
    document_text: str,
    title: str,
    doc_type: str = "",
    reg_number: str = "",
    org_name: str = "",
    allow_centralization: bool = True,
    personal_data_risk: str = "LOW",
) -> Optional[dict]:
    """
    Generate VDVC v1.1 semantic metadata via AI.

    GDPR routing logic:
    - classified → return None (manual only)
    - HIGH/MEDIUM risk + no centralization → local only
    - otherwise → central API with anonymization if needed
    """
    if not document_text or len(document_text.strip()) < 20:
        return None

    start = _time.time()
    text = document_text[:15000]

    route = "CENTRAL"
    anonymized = False

    if personal_data_risk in ("HIGH", "MEDIUM") and not allow_centralization:
        route = "LOCAL"
    elif not allow_centralization:
        route = "LOCAL"

    if route == "CENTRAL" and personal_data_risk in ("HIGH", "MEDIUM"):
        text, anonymized = anonymize_text(text)

    content_hash = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
    user_msg = await _get_user_message(title, doc_type, reg_number, org_name, text)
    user_msg = f"{user_msg}\n\nContent Hash: {content_hash}"
    system_prompt = await _get_semantic_prompt()

    result = await _complete_json(system_prompt, user_msg)

    if not result:
        if route == "CENTRAL":
            route = "LOCAL"
        return None

    pii_errors = scan_response_for_pii(result)
    if pii_errors:
        logger.warning("PII detected in AI response: %s", pii_errors)
        ss = result.get("semanticSummary", {})
        for field in ["primaryTopic", "summary", "documentPurpose", "requestedAction"]:
            val = ss.get(field, "")
            if isinstance(val, str):
                val = _LV_PERSONAS_KODS.sub("[REDACTED]", val)
                val = _EMAIL_RE.sub("[REDACTED]", val)
                ss[field] = val
        ss["humanValidationStatus"] = "REJECTED"
        ss["aiConfidenceScore"] = 0
        result["_pii_errors"] = pii_errors

    elapsed = int((_time.time() - start) * 1000)
    cfg = _cfg()
    result["_processing"] = {
        "route": route,
        "model": cfg["model"],
        "elapsed_ms": elapsed,
        "anonymized": anonymized,
    }

    return result


async def generate_local_briefing(recent_docs: list) -> Optional[dict]:
    """Generate an intelligence briefing from recent document activity using the local LLM."""
    if not is_configured() or not recent_docs:
        return None

    doc_lines = "\n".join(
        f"- {d.get('title', 'Untitled')} | status: {d.get('status', '?')} | topic: {d.get('topic') or 'N/A'}"
        for d in recent_docs[:20]
    )

    system = """You are an intelligence briefing generator for a government document management system.
Analyze the provided list of recent documents and generate a concise briefing summary.
Respond ONLY with a JSON object — no markdown, no commentary:
{
  "summary": "2-3 sentence overview of current document activity",
  "key_topics": ["topic1", "topic2"],
  "document_count": <integer>,
  "notable_items": ["brief item 1", "brief item 2"],
  "source": "local-ai"
}"""

    result = await _complete_json(system, f"Recent documents:\n{doc_lines}")
    if result:
        result["source"] = "local-ai"
    return result
