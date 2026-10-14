"""Datu glabātuve — which storage this DVS uses, and the S3 connector it can use.

Active backend: on-disk (default) or S3. The S3 connector settings come from
the GUI (stored here, secret encrypted) or, if never saved, from the
environment (OPENDMS_STORAGE_S3_*). Switching the active backend is a separate,
later step: it needs the existing files and metadata moved first.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any, Optional

from opendms.config import get_settings
from opendms.database import get_pool

SECRET_REF = "storage-s3"


def _j(v):
    return json.loads(v) if isinstance(v, str) else v


async def ensure_schema() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS storage_settings (
                id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
                s3_endpoint TEXT, s3_bucket TEXT, s3_region TEXT, s3_access_key TEXT,
                last_test JSONB, updated_by TEXT, updated_at TIMESTAMPTZ DEFAULT NOW()
            );
            ALTER TABLE storage_settings ADD COLUMN IF NOT EXISTS last_export JSONB""")


async def s3_config(with_secret: bool = False) -> dict[str, Any]:
    await ensure_schema()
    s = get_settings()
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM storage_settings WHERE id = 1")
    if row and row["s3_endpoint"]:
        cfg = {"endpoint": row["s3_endpoint"], "bucket": row["s3_bucket"], "region": row["s3_region"] or "us-east-1",
               "accessKey": row["s3_access_key"], "source": "saglabāts DVS",
               "lastTest": json.loads(row["last_test"]) if isinstance(row["last_test"], str) else row["last_test"],
               "lastExport": _j(row["last_export"]),
               "updatedBy": row["updated_by"], "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else None}
        from opendms.connectors.secrets import get_secret
        secret = (await get_secret(SECRET_REF)).get("secretKey")
    else:
        cfg = {"endpoint": s.storage_s3_endpoint, "bucket": s.storage_s3_bucket if s.storage_s3_endpoint else None,
               "region": s.storage_s3_region, "accessKey": s.storage_s3_access_key, "source": "vide (env)",
               "lastTest": json.loads(row["last_test"]) if row and isinstance(row["last_test"], str) else (row["last_test"] if row else None),
               "lastExport": _j(row["last_export"]) if row else None}
        secret = s.storage_s3_secret_key
    cfg["secretSet"] = bool(secret)
    if with_secret:
        cfg["secretKey"] = secret
    return cfg


async def save_s3(endpoint: str, bucket: str, region: str, access_key: str, secret_key: Optional[str], who: str) -> None:
    await ensure_schema()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO storage_settings (id, s3_endpoint, s3_bucket, s3_region, s3_access_key, updated_by, updated_at)
               VALUES (1, $1, $2, $3, $4, $5, NOW())
               ON CONFLICT (id) DO UPDATE SET s3_endpoint = $1, s3_bucket = $2, s3_region = $3,
                   s3_access_key = $4, updated_by = $5, updated_at = NOW()""",
            endpoint.strip(), bucket.strip(), (region or "us-east-1").strip(), access_key.strip(), who)
    if secret_key and secret_key.strip():
        from opendms.connectors.secrets import put_secret
        await put_secret(SECRET_REF, {"secretKey": secret_key.strip()})


def _client(cfg: dict):
    import boto3
    from botocore.config import Config
    return boto3.session.Session().client(
        "s3", endpoint_url=cfg["endpoint"], region_name=cfg.get("region") or "us-east-1",
        aws_access_key_id=cfg["accessKey"], aws_secret_access_key=cfg["secretKey"],
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"},
                      connect_timeout=5, read_timeout=15, retries={"max_attempts": 1}))


def _test_sync(cfg: dict) -> dict:
    """Write, read, version-check and delete one test object. Each check reported separately."""
    steps, ok = [], True

    def step(name, fn):
        nonlocal ok
        t = time.perf_counter()
        try:
            detail = fn()
            steps.append({"solis": name, "ok": True, "ms": round((time.perf_counter() - t) * 1000), "info": detail})
        except Exception as e:
            ok = False
            code = getattr(e, "response", {}).get("Error", {}).get("Code") if hasattr(e, "response") else None
            steps.append({"solis": name, "ok": False, "ms": round((time.perf_counter() - t) * 1000),
                          "kluda": code or f"{type(e).__name__}: {str(e)[:200]}"})
        return ok

    c = _client(cfg)
    b = cfg["bucket"]
    key = f"_parbaude/opendms-{uuid.uuid4().hex[:8]}.txt"
    body = f"OpenDMS savienojuma pārbaude {time.strftime('%Y-%m-%d %H:%M:%S')}".encode()
    if not step("Konteiners pieejams", lambda: c.head_bucket(Bucket=b) and "ok"):
        return {"ok": False, "soli": steps}
    step("Rakstīšana", lambda: c.put_object(Bucket=b, Key=key, Body=body).get("VersionId") and "versija piešķirta" or "ierakstīts")
    step("Lasīšana", lambda: "saturs sakrīt" if c.get_object(Bucket=b, Key=key)["Body"].read() == body else (_ for _ in ()).throw(ValueError("saturs atšķiras")))
    step("Versiju glabāšana", lambda: c.get_bucket_versioning(Bucket=b).get("Status") or "izslēgta")
    step("Objektu bloķēšana", lambda: c.get_object_lock_configuration(Bucket=b)["ObjectLockConfiguration"].get("ObjectLockEnabled", "nav"))

    def _count():
        r = c.list_objects_v2(Bucket=b, MaxKeys=1000)
        return f"{r.get('KeyCount', 0)} objekti{' (vairāk nekā 1000)' if r.get('IsTruncated') else ''}"
    step("Saraksts", _count)

    def _cleanup():
        vs = c.list_object_versions(Bucket=b, Prefix=key).get("Versions", [])
        for v in vs:
            c.delete_object(Bucket=b, Key=key, VersionId=v["VersionId"])
        if not vs:
            c.delete_object(Bucket=b, Key=key)
        return "pārbaudes objekts dzēsts"
    step("Tīrīšana", _cleanup)
    return {"ok": ok, "soli": steps}


async def test(cfg: dict) -> dict:
    missing = [k for k in ("endpoint", "bucket", "accessKey", "secretKey") if not cfg.get(k)]
    if missing:
        return {"ok": False, "soli": [{"solis": "Iestatījumi", "ok": False, "kluda": "trūkst: " + ", ".join(missing)}]}
    try:
        res = await asyncio.to_thread(_test_sync, cfg)
    except Exception as e:
        res = {"ok": False, "soli": [{"solis": "Savienojums", "ok": False, "kluda": f"{type(e).__name__}: {str(e)[:200]}"}]}
    res["laiks"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    res["endpoint"], res["bucket"] = cfg["endpoint"], cfg["bucket"]
    return res


async def record_test(result: dict) -> None:
    await ensure_schema()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""INSERT INTO storage_settings (id, last_test) VALUES (1, $1)
                              ON CONFLICT (id) DO UPDATE SET last_test = $1""", json.dumps(result, ensure_ascii=False))


async def active() -> dict:
    """What this DVS stores on now, and how much."""
    s = get_settings()
    pool = await get_pool()
    async with pool.acquire() as conn:
        files = await conn.fetchrow("SELECT COUNT(*) n, COALESCE(SUM(file_size),0) bytes FROM document_files")
        docs = await conn.fetchval("SELECT COUNT(*) FROM documents")
        pkgs = await conn.fetchval("SELECT COUNT(*) FROM documents WHERE metadata ? 'standartaPakotne'")
    label = {"local": "Diskā (servera failu sistēmā)", "s3": "S3", "azure": "Azure Blob"}.get(s.storage_backend, s.storage_backend)
    return {"backend": s.storage_backend, "nosaukums": label,
            "vieta": s.storage_local_path if s.storage_backend == "local" else s.storage_s3_endpoint,
            "dokumenti": docs, "datnes": files["n"], "datnuApjoms": int(files["bytes"]), "pakotnes": pkgs}
