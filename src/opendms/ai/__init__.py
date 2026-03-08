"""
OpenDMS AI Intelligence — user-facing AI capabilities.

Provides:
  - Document classification suggestion (when creating/receiving documents)
  - Routing recommendation (who should handle this document)
  - Content summarization (generate document summary from file content)

Uses LLM via OpenAI-compatible API (Anthropic, OpenAI, Ollama).
Falls back to rule-based logic when LLM is unavailable.
"""

import json, logging, os
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
