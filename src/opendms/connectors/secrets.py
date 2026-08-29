"""Encrypted secret store for connector credentials.

WHY THIS EXISTS AS A SEPARATE TABLE. The obvious shortcut is to drop the API
token into connections.config alongside the base URL. OpenITSM's Jira handler
does exactly that — its model docstring promises a secret_ref indirection and
the handler then reads cfg["api_token"] straight out of the JSONB blob. That is
fine for a demo and wrong for anything a regulator reads: the config column is
returned by the list endpoint, ends up in logs, and gets dumped by any
`SELECT *`. So credentials live here instead, encrypted, in a table no read API
ever touches.

WHAT IS AND IS NOT PROTECTED. Fernet (AES-128-CBC + HMAC-SHA256) at rest. This
defends against a database dump, a stray SELECT, and a backup landing somewhere
it should not. It does NOT defend against someone who already has the
application's environment, because the key is there — that would need a real
KMS/Vault, which is the Phase-2 note in the connections table comment.

KEY MATERIAL. OPENDMS_CONNECTOR_SECRET_KEY, a urlsafe-base64 32-byte value. If
unset it is derived from jwt_secret via HKDF-SHA256 with a fixed info string, so
a fresh install works without ceremony. Deriving is the weaker option — rotating
the JWT secret then silently orphans every stored credential — so the derived
path logs a warning once and the field is documented in .env.example.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from typing import Any, Optional

from opendms.config import get_settings
from opendms.database import get_pool

logger = logging.getLogger(__name__)

_HKDF_INFO = b"opendms/connector-secrets/v1"
_fernet = None
_warned = False


def _hkdf_sha256(ikm: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 HKDF with an empty salt — enough to domain-separate the key."""
    prk = hmac.new(b"\x00" * 32, ikm, hashlib.sha256).digest()
    okm, block, counter = b"", b"", 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def _get_fernet():
    global _fernet, _warned
    if _fernet is not None:
        return _fernet
    from cryptography.fernet import Fernet  # imported late: optional at import time

    s = get_settings()
    configured = (getattr(s, "connector_secret_key", "") or "").strip()
    if configured:
        key = configured.encode()
    else:
        if not _warned:
            logger.warning(
                "OPENDMS_CONNECTOR_SECRET_KEY is not set — deriving the connector "
                "secret key from jwt_secret. Rotating the JWT secret will make every "
                "stored connector credential undecryptable. Set an explicit key."
            )
            _warned = True
        key = base64.urlsafe_b64encode(_hkdf_sha256(s.jwt_secret.encode(), _HKDF_INFO))
    _fernet = Fernet(key)
    return _fernet


def generate_key() -> str:
    """Mint a key suitable for OPENDMS_CONNECTOR_SECRET_KEY."""
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode()


async def put_secret(ref: str, payload: dict[str, Any], updated_by: Optional[int] = None) -> None:
    """Store (or replace) the credential bundle behind `ref`.

    Blank values are dropped rather than stored, so a GUI save that leaves the
    token field empty means "keep what is there" at the caller's discretion
    without ever writing an empty credential over a good one by accident.
    """
    clean = {k: v for k, v in payload.items() if str(v or "").strip()}
    token = _get_fernet().encrypt(json.dumps(clean).encode()).decode()
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO connection_secrets (ref, ciphertext, updated_by, updated_at)
               VALUES ($1, $2, $3, NOW())
               ON CONFLICT (ref) DO UPDATE
                 SET ciphertext = EXCLUDED.ciphertext,
                     updated_by = EXCLUDED.updated_by,
                     updated_at = NOW()""",
            ref, token, updated_by,
        )


async def get_secret(ref: Optional[str]) -> dict[str, Any]:
    """Return the decrypted bundle, or {} if absent/undecryptable.

    An undecryptable row is logged and treated as absent rather than raised:
    the connector then reports "credential missing" through the normal Result
    path, which is far easier to act on than a 500 from a background task.
    """
    if not ref:
        return {}
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT ciphertext FROM connection_secrets WHERE ref = $1", ref)
    if not row:
        return {}
    try:
        return json.loads(_get_fernet().decrypt(row["ciphertext"].encode()).decode())
    except Exception:
        logger.error("connector secret %s could not be decrypted (wrong or rotated key)", ref)
        return {}


async def delete_secret(ref: Optional[str]) -> None:
    if not ref:
        return
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM connection_secrets WHERE ref = $1", ref)


async def describe_secret(ref: Optional[str]) -> dict[str, bool]:
    """Which credential keys are set — names only, never values.

    This is what the GUI uses to render "API token: set / not set" without the
    API ever being able to hand a credential back to a browser.
    """
    return {k: True for k in (await get_secret(ref)).keys()}
