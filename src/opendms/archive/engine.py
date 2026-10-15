"""Arhivēšana no publicētā UAPF pakotnes (ProcessGit kisc/dokumentu-arhivesana) — 5. solis.

Noteikumi (DMN) un procesi (BPMN) izpildās DVS UAPF dzinējā. Lokālās Python kopijas lēmumiem
(registration.check_minimum, registration.file_action) paliek tikai rezervei, ja dzinējs nav pieejams;
tad atbilde norāda avotu "lokāli".
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from opendms.config import get_settings
from opendms.database import get_pool

logger = logging.getLogger(__name__)

PKG = "lv.kisc.dokumentu-arhivesana"
SOURCE_URL = "/api/v1/repos/kisc/dokumentu-arhivesana/archive/main.zip"

SCHEMA = """
ALTER TABLE uapf_sessions ADD COLUMN IF NOT EXISTS case_id BIGINT REFERENCES standard_cases(id) ON DELETE SET NULL;
ALTER TABLE uapf_sessions ADD COLUMN IF NOT EXISTS waiting_for TEXT;
CREATE INDEX IF NOT EXISTS idx_uapf_sessions_case ON uapf_sessions(case_id);
"""


def _engine() -> str:
    return get_settings().uapf_engine_url.rstrip("/")


def _headers() -> dict:
    t = get_settings().uapf_engine_auth_token
    return {"Content-Type": "application/json", **({"Authorization": f"Bearer {t}"} if t else {})}


async def package_info() -> Optional[dict]:
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{_engine()}/uapf/packages", headers=_headers())
            r.raise_for_status()
            return next((p for p in r.json() if p.get("packageId") == PKG), None)
    except Exception as e:
        logger.info("UAPF dzinējs nav pieejams: %s", e)
        return None


async def install() -> dict:
    """Uzstādīt / atjaunināt pakotni no ProcessGit (tāpat kā UAPF cilnē 'sync')."""
    s = get_settings()
    url = s.processgit_url.rstrip("/") + SOURCE_URL
    async with httpx.AsyncClient(timeout=120) as c:
        r = await c.post(f"{_engine()}/uapf/admin/install-from-url",
                         json={"sourceUrl": url, "packageId": PKG,
                               **({"authToken": s.processgit_token} if s.processgit_token else {})})
        if r.status_code >= 400:
            raise RuntimeError(f"Dzinējs neuzstādīja pakotni: {r.text[:300]}")
        out = r.json()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""INSERT INTO uapf_package_sources (package_id, source_url, last_synced_at) VALUES ($1, $2, NOW())
                              ON CONFLICT (package_id) DO UPDATE SET source_url = EXCLUDED.source_url, last_synced_at = NOW()""",
                           PKG, url)
    return out


async def decide(decision_id: str, inputs: dict) -> Optional[dict]:
    """DMN no pakotnes. None, ja dzinējs vai pakotne nav pieejama."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(f"{_engine()}/uapf/evaluate-decision", headers=_headers(),
                             json={"packageId": PKG, "decisionId": decision_id, "input": inputs})
            if r.status_code >= 400:
                logger.warning("lēmums %s: %s", decision_id, r.text[:200])
                return None
            d = r.json()
    except Exception as e:
        logger.info("lēmums %s nav izpildīts dzinējā: %s", decision_id, e)
        return None
    rules = [x for e in d.get("explanations") or [] for x in e.get("rulesFired") or []]
    return {"outputs": d.get("outputs") or {}, "noteikumi": rules, "avots": f"{PKG}/{decision_id}"}


# ── procesu sesijas ──

async def _record(session: dict, process_id: str, case_id: Optional[int], document_id: Optional[int], inp: dict,
                  error: Optional[str] = None) -> None:
    pool = await get_pool()
    sid = session.get("sessionId") or f"sess_failed_{process_id}_{case_id or document_id}"
    state = session.get("state") or ("failed" if error else "unknown")
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO uapf_sessions (session_id, document_id, case_id, package_id, process_id, state, waiting_for,
                                          input_payload, output_payload, error_message, completed_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10, CASE WHEN $6 IN ('completed','failed','aborted') THEN NOW() END)
               ON CONFLICT (session_id) DO UPDATE SET state = EXCLUDED.state, waiting_for = EXCLUDED.waiting_for,
                   output_payload = EXCLUDED.output_payload, error_message = EXCLUDED.error_message,
                   completed_at = CASE WHEN EXCLUDED.state IN ('completed','failed','aborted') THEN NOW() END""",
            sid, document_id, case_id, PKG, process_id, state, session.get("waitingFor"),
            json.dumps(inp, ensure_ascii=False, default=str),
            json.dumps(session.get("output"), ensure_ascii=False, default=str) if session.get("output") is not None else None,
            error)


def _view(session: dict, process_id: str) -> dict:
    out = session.get("output") or {}
    return {"sesija": session.get("sessionId"), "process": process_id, "stavoklis": session.get("state"),
            "gaida": session.get("waitingFor"), "rezultats": out, "kluda": session.get("error")}


async def start(process_id: str, inp: dict, case_id: Optional[int] = None, document_id: Optional[int] = None) -> dict:
    from opendms.uapf.manifest import build_host_manifest
    body = {"packageId": PKG, "processId": process_id, "input": inp, "hostManifest": build_host_manifest()}
    try:
        async with httpx.AsyncClient(timeout=300) as c:
            r = await c.post(f"{_engine()}/uapf/start-session", headers=_headers(), json=body)
            if r.status_code >= 400:
                raise RuntimeError(r.text[:400])
            session = r.json()
    except Exception as e:
        await _record({}, process_id, case_id, document_id, inp, str(e))
        raise RuntimeError(f"Process {process_id} netika palaists: {e}")
    await _record(session, process_id, case_id, document_id, inp)
    return _view(session, process_id)


async def resume(session_id: str, output: dict) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM uapf_sessions WHERE session_id = $1", session_id)
    if not row:
        raise RuntimeError("Sesija nav atrasta")
    async with httpx.AsyncClient(timeout=300) as c:
        r = await c.post(f"{_engine()}/uapf/sessions/{session_id}/resume", headers=_headers(), json={"output": output})
        if r.status_code >= 400:
            raise RuntimeError(f"Sesiju nevar turpināt: {r.text[:300]}")
        session = r.json()
    session.setdefault("sessionId", session_id)
    inp = row["input_payload"]
    await _record(session, row["process_id"], row["case_id"], row["document_id"],
                  json.loads(inp) if isinstance(inp, str) else (inp or {}))
    return _view(session, row["process_id"])


async def case_sessions(case_id: int, limit: int = 10) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """SELECT session_id, process_id, state, waiting_for, output_payload, error_message, started_at, completed_at
                 FROM uapf_sessions WHERE case_id = $1 ORDER BY started_at DESC LIMIT $2""", case_id, limit)
    out = []
    for r in rows:
        d = dict(r)
        p = d.pop("output_payload")
        d["rezultats"] = json.loads(p) if isinstance(p, str) else p
        out.append(d)
    return out


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


def as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "jā", "ja", "yes")
