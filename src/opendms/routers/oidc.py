"""OpenID Connect login.

Sits alongside the local password login rather than replacing it, so a
misconfigured provider cannot lock an operator out of an instance that holds
its organisation's signing key.

Unlike the registry, this service has a real user table with roles and
organisation scoping, so an OIDC login resolves to an actual user row. What
the provider establishes is identity and nothing else: the role comes from
the local record, or from OIDC_DEFAULT_ROLE for someone seen for the first
time. A provider cannot make anyone an administrator here.

Enabled only when OIDC_ENABLED and the issuer, client id and secret are all
present; otherwise the routes report 404 and nothing changes.
"""

import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import urllib.parse
import urllib.request

import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from opendms.database import get_pool
from opendms.middleware.auth import create_token, hash_password

router = APIRouter(prefix="/api/auth/oidc", tags=["Auth"])

ROLES = ("superadmin", "admin", "operator", "viewer")


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


def enabled() -> bool:
    return (
        _env("OIDC_ENABLED").lower() in ("1", "true", "yes")
        and bool(_env("OIDC_ISSUER"))
        and bool(_env("OIDC_CLIENT_ID"))
        and bool(_env("OIDC_CLIENT_SECRET"))
    )


_meta: dict = {}


def _discover() -> dict:
    issuer = _env("OIDC_ISSUER").rstrip("/")
    if issuer in _meta:
        return _meta[issuer]
    with urllib.request.urlopen(f"{issuer}/.well-known/openid-configuration", timeout=10) as r:
        _meta[issuer] = json.loads(r.read().decode("utf-8"))
    return _meta[issuer]


_pending: dict = {}


def _prune() -> None:
    now = dt.datetime.utcnow()
    for k, v in list(_pending.items()):
        if (now - v["created"]).total_seconds() > 600:
            _pending.pop(k, None)


@router.get("/config", summary="Whether OIDC login is offered")
def config():
    return {"enabled": enabled(), "label": _env("OIDC_LABEL", "SSO")}


@router.get("/login", summary="Begin OIDC login")
def login():
    if not enabled():
        raise HTTPException(404, "OIDC is not configured")
    meta = _discover()
    _prune()
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).decode().rstrip("=")
    _pending[state] = {"verifier": verifier, "created": dt.datetime.utcnow()}
    params = {
        "client_id": _env("OIDC_CLIENT_ID"),
        "response_type": "code",
        "scope": _env("OIDC_SCOPE", "openid email profile"),
        "redirect_uri": _env("OIDC_REDIRECT_URI"),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return RedirectResponse(
        meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(params),
        status_code=302,
    )


async def _resolve_user(email: str, name: str) -> dict:
    """Find the local user for this identity, or provision a minimal one.

    The provider establishes who someone is. It does not decide what they may
    do: an existing user keeps the role already recorded against them, and a
    new one gets OIDC_DEFAULT_ROLE, which defaults to the least privileged.
    A random password is stored because the column is NOT NULL; it is never
    used and cannot be logged in with, since the local login compares against
    a hash of something nobody knows.
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, email, full_name, role, org_id, is_active FROM users WHERE email = $1",
            email,
        )
        if row:
            if not row["is_active"]:
                raise HTTPException(403, "This account is disabled")
            return dict(row)

        if _env("OIDC_AUTO_PROVISION", "true").lower() not in ("1", "true", "yes"):
            raise HTTPException(
                403, "No account exists for this identity and automatic creation is off"
            )

        role = _env("OIDC_DEFAULT_ROLE", "viewer")
        if role not in ROLES:
            role = "viewer"
        org_id = _env("OIDC_DEFAULT_ORG_ID") or None

        row = await conn.fetchrow(
            """INSERT INTO users (email, password_hash, full_name, role, org_id)
               VALUES ($1, $2, $3, $4, $5)
               RETURNING id, email, full_name, role, org_id, is_active""",
            email,
            hash_password(secrets.token_urlsafe(32)),
            name or email,
            role,
            int(org_id) if org_id else None,
        )
        return dict(row)


@router.get("/callback", summary="Complete OIDC login")
async def callback(request: Request):
    if not enabled():
        raise HTTPException(404, "OIDC is not configured")
    code = request.query_params.get("code") or ""
    state = request.query_params.get("state") or ""
    if not code or state not in _pending:
        raise HTTPException(400, "Invalid or expired login attempt")
    verifier = _pending.pop(state)["verifier"]

    meta = _discover()
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _env("OIDC_REDIRECT_URI"),
        "client_id": _env("OIDC_CLIENT_ID"),
        "client_secret": _env("OIDC_CLIENT_SECRET"),
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(
        meta["token_endpoint"], data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            tok = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise HTTPException(502, f"Token exchange failed: {e}")

    id_token = tok.get("id_token")
    if not id_token:
        raise HTTPException(502, "Provider returned no id_token")

    try:
        jwks = pyjwt.PyJWKClient(meta["jwks_uri"])
        key = jwks.get_signing_key_from_jwt(id_token).key
        claims = pyjwt.decode(
            id_token, key, algorithms=["RS256", "ES256"],
            audience=_env("OIDC_CLIENT_ID"), issuer=meta["issuer"],
        )
    except Exception as e:
        raise HTTPException(401, f"Could not verify id_token: {e}")

    email = (claims.get("email") or claims.get("preferred_username") or "").strip().lower()
    if not email:
        raise HTTPException(401, "Provider supplied neither an email nor a username")

    user = await _resolve_user(email, (claims.get("name") or "").strip())
    token = create_token(user["id"], user["email"], user["role"], user["org_id"])
    payload = {
        "id": user["id"], "email": user["email"], "full_name": user["full_name"],
        "role": user["role"], "org_id": user["org_id"],
    }
    # The console keeps its session in localStorage, so hand it over there.
    html = (
        "<!doctype html><meta charset='utf-8'><title>...</title><script>"
        "try{localStorage.setItem('opendms_token'," + json.dumps(token) + ");"
        "localStorage.setItem('opendms_user'," + json.dumps(json.dumps(payload)) + ");}"
        "catch(e){}location.replace('/');</script>"
        "<p>Notiek pieteiksanas...</p>"
    )
    return HTMLResponse(html)
