"""Savienojums ar LNA (laboratorijā — LNA pieņemšanas simulators, lna-simulator/) — 7. solis.

- iesniegt: iznīcināšanas aktu (P4b), uzskaites sarakstu (P5), gada nodošanas vienošanos (P6 PlanCheck);
- nodot: OPEX pakotni augšupielādē LNA S3 ievades krātuvē (<iestāde>/<pakotne>.zip un .zip.sha256) un iesniedz;
- sekot: fona uzdevums ik pēc LNA_POLL_S sekundēm nolasa lēmumus un turpina procesu lietotāja uzdevumā
  (AwaitLNA / AgreePlan) ar to pašu DVS pārbaudi, ko izmanto manuāla ievade.

Ja LNA savienojums nav konfigurēts (OPENDMS_LNA_URL), viss paliek kā līdz šim: lēmumu ievada lietotājs.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import date
from typing import Optional

import httpx

from opendms.database import get_pool

logger = logging.getLogger(__name__)

POLL_S = int(os.environ.get("OPENDMS_LNA_POLL_S", "20"))
SYSTEM_USER = {"id": None, "email": "lna-savienojums", "role": "admin"}
STEP = {"akts": "AwaitLNA", "saraksts": "AwaitLNA", "nodosana": "AwaitLNA", "plans": "AgreePlan"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS lna_submissions (
    id BIGSERIAL PRIMARY KEY,
    org_id BIGINT NOT NULL REFERENCES organizations(id),
    kind TEXT NOT NULL,                 -- akts | saraksts | plans | nodosana
    object_id BIGINT,
    session_id TEXT,
    remote_id TEXT,
    status TEXT NOT NULL DEFAULT 'Iesniegts',
    decision JSONB,
    error TEXT,
    resumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    decided_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_lna_sub_open ON lna_submissions(status) WHERE resumed_at IS NULL;
"""


def cfg() -> dict:
    return {"url": os.environ.get("OPENDMS_LNA_URL", "").rstrip("/"), "token": os.environ.get("OPENDMS_LNA_TOKEN", ""),
            "org": os.environ.get("OPENDMS_LNA_ORG", ""),
            "s3_endpoint": os.environ.get("OPENDMS_LNA_S3_ENDPOINT", ""), "s3_bucket": os.environ.get("OPENDMS_LNA_S3_BUCKET", "lna-ievade"),
            "s3_access_key": os.environ.get("OPENDMS_LNA_S3_ACCESS_KEY", ""), "s3_secret_key": os.environ.get("OPENDMS_LNA_S3_SECRET_KEY", "")}


def configured() -> bool:
    c = cfg()
    return bool(c["url"] and c["token"] and c["org"])


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def _post(body: dict) -> dict:
    c = cfg()
    async with httpx.AsyncClient(timeout=300) as h:
        r = await h.post(f"{c['url']}/api/v1/iesniegumi", json=body, headers={"Authorization": f"Bearer {c['token']}"})
        if r.status_code >= 400:
            raise RuntimeError(f"LNA atteica iesniegumu ({r.status_code}): {r.text[:300]}")
        return r.json()


async def _record(org_id: int, kind: str, object_id: Optional[int], session_id: Optional[str], remote: dict) -> int:
    pool = await get_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """INSERT INTO lna_submissions (org_id, kind, object_id, session_id, remote_id, status, decision, decided_at)
               VALUES ($1,$2,$3,$4,$5,$6,$7, CASE WHEN $6 <> 'Sanemts' THEN NOW() END) RETURNING id""",
            org_id, kind, object_id, session_id, remote["id"], remote["statuss"],
            json.dumps(remote.get("lemums"), ensure_ascii=False) if remote.get("lemums") else None)


async def submit_xml(org_id: int, kind: str, object_id: int, xml: bytes, session_id: Optional[str]) -> dict:
    r = await _post({"veids": kind, "atsauce": str(object_id), "xml": xml.decode("utf-8")})
    await _record(org_id, kind, object_id, session_id, r)
    return r


async def submit_plan(org_id: int, year: int, cases: int, session_id: Optional[str]) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:   # viens atvērts plāna pieprasījums gadam
        prev = await conn.fetchrow("""SELECT * FROM lna_submissions WHERE org_id = $1 AND kind = 'plans' AND object_id = $2
                                        AND resumed_at IS NULL ORDER BY id DESC LIMIT 1""", org_id, year)
    if prev:
        if session_id and prev["session_id"] != session_id:
            async with pool.acquire() as conn:
                await conn.execute("UPDATE lna_submissions SET session_id = $2 WHERE id = $1", prev["id"], session_id)
        return {"id": prev["remote_id"], "statuss": prev["status"]}
    r = await _post({"veids": "plans", "atsauce": str(year), "gads": year, "apjoms": {"lietas": cases}})
    await _record(org_id, "plans", year, session_id, r)
    return r


async def deliver(org_id: int, package_id: int, zip_bytes: bytes, sha256: str, name: str, session_id: Optional[str]) -> dict:
    import boto3
    from botocore.config import Config
    c = cfg()
    if not (c["s3_endpoint"] and c["s3_access_key"] and c["s3_secret_key"]):
        raise RuntimeError("LNA S3 ievades krātuve nav konfigurēta")
    s3 = boto3.session.Session().client("s3", endpoint_url=c["s3_endpoint"], region_name="us-east-1",
                                        aws_access_key_id=c["s3_access_key"], aws_secret_access_key=c["s3_secret_key"],
                                        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}))
    key = f"{c['org']}/{name}.zip"
    await asyncio.to_thread(s3.put_object, Bucket=c["s3_bucket"], Key=key, Body=zip_bytes, ContentType="application/zip")
    await asyncio.to_thread(s3.put_object, Bucket=c["s3_bucket"], Key=key + ".sha256",
                            Body=f"{sha256}  {name}.zip\n".encode(), ContentType="text/plain")
    r = await _post({"veids": "nodosana", "atsauce": str(package_id), "s3Key": key})
    await _record(org_id, "nodosana", package_id, session_id, r)
    return {**r, "s3Key": key}


# ── lēmumi → procesa turpināšana ──

def resume_output(kind: str, d: dict) -> dict:
    lem = d.get("lemums")
    ref = d.get("atsauce")
    if kind == "plans":
        return {"planaDatums": d.get("vienosanasDatums") or date.today().isoformat(), "planaAtsauce": ref,
                "piezimes": f"Nodošanas laiks {d.get('nodosanasLaiks')}" if d.get("nodosanasLaiks") else None}
    notes = "; ".join(d.get("piezimes") or []) or None
    if kind == "nodosana" and d.get("pienemsanasAkts"):
        pa = d["pienemsanasAkts"]
        notes = f"{pa.get('lnaStrukturvieniba')}, {pa.get('atbildigais')}" + (f"; {notes}" if notes else "")
    return {"lnaLemums": lem, "lnaAtsauce": ref, "piezimes": notes}


async def poll_once() -> dict:
    """Nolasa neizlemtos iesniegumus; izlemtos turpina procesā, ja sesija gaida attiecīgo uzdevumu."""
    if not configured():
        return {"konfigurets": False}
    from fastapi import HTTPException
    from opendms.routers.archive_scheme import ResumeIn, resume_session
    c = cfg()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = [dict(r) for r in await conn.fetch(
            "SELECT * FROM lna_submissions WHERE resumed_at IS NULL AND session_id IS NOT NULL ORDER BY id LIMIT 50")]
    done = 0
    for s in rows:
        d = s["decision"]
        d = json.loads(d) if isinstance(d, str) else d
        if s["status"] == "Sanemts":
            try:
                async with httpx.AsyncClient(timeout=30) as h:
                    r = await h.get(f"{c['url']}/api/v1/iesniegumi/{s['remote_id']}", headers={"Authorization": f"Bearer {c['token']}"})
                r.raise_for_status()
                remote = r.json()
            except Exception as e:
                logger.info("LNA statuss %s: %s", s["remote_id"], e)
                continue
            if remote["statuss"] == "Sanemts":
                continue
            d = remote.get("lemums") or {}
            async with pool.acquire() as conn:
                await conn.execute("UPDATE lna_submissions SET status = $2, decision = $3, decided_at = NOW() WHERE id = $1",
                                   s["id"], remote["statuss"], json.dumps(d, ensure_ascii=False))
        async with pool.acquire() as conn:
            waiting = await conn.fetchval("SELECT waiting_for FROM uapf_sessions WHERE session_id = $1 AND state = 'suspended'", s["session_id"])
        if waiting != STEP[s["kind"]]:
            continue                                   # process vēl nav nonācis līdz gaidīšanai (vai jau turpināts)
        try:
            await resume_session(s["session_id"], ResumeIn(output=resume_output(s["kind"], d or {})), user=SYSTEM_USER)
            err = None
        except HTTPException as e:
            err = str(e.detail)
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
        async with pool.acquire() as conn:
            await conn.execute("UPDATE lna_submissions SET resumed_at = CASE WHEN $2::text IS NULL THEN NOW() END, error = $2 WHERE id = $1",
                               s["id"], err)
        if err:
            logger.warning("LNA lēmumu nevarēja ievadīt procesā %s: %s", s["session_id"], err)
        else:
            done += 1
    return {"konfigurets": True, "parbauditi": len(rows), "turpinati": done}


async def run_forever() -> None:
    await asyncio.sleep(10)
    while True:
        try:
            await poll_once()
        except Exception as e:  # noqa: BLE001
            logger.warning("LNA sekošana: %s", e)
        await asyncio.sleep(POLL_S)


async def list_submissions(org_id: int, limit: int = 50) -> list[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""SELECT id, kind, object_id, session_id, remote_id, status, decision, error, created_at, decided_at, resumed_at
                                     FROM lna_submissions WHERE org_id = $1 ORDER BY id DESC LIMIT $2""", org_id, limit)
    out = []
    for r in rows:
        d = dict(r)
        d["decision"] = json.loads(d["decision"]) if isinstance(d["decision"], str) else d["decision"]
        out.append(d)
    return out
