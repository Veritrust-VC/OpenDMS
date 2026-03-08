"""JWT authentication middleware."""

import hashlib, logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
import jwt as pyjwt
from opendms.config import get_settings
from opendms.database import get_pool

logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


def create_token(user_id: int, email: str, role: str, org_id: Optional[int] = None) -> str:
    s = get_settings()
    payload = {
        "sub": str(user_id), "email": email, "role": role,
        "org_id": org_id,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_expire_minutes),
        "iat": datetime.now(timezone.utc),
    }
    return pyjwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def decode_token(token: str) -> dict:
    s = get_settings()
    return pyjwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])


async def get_current_user(creds: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if not creds:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = decode_token(creds.credentials)
        pool = await get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT id, email, full_name, role, org_id, is_active FROM users WHERE id = $1",
                int(payload["sub"]),
            )
        if not user or not user["is_active"]:
            raise HTTPException(401, "User inactive or not found")
        return dict(user)
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except Exception as e:
        raise HTTPException(401, f"Invalid token: {e}")


def require_role(*roles):
    """Dependency factory: require user to have one of the given roles."""
    async def checker(user=Depends(get_current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, f"Requires role: {', '.join(roles)}")
        return user
    return checker
