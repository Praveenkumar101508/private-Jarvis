"""
JWT authentication middleware.

Two token types:
  - Bearer JWT  → standard API access (issued at /auth/token)
  - API Key     → for service-to-service calls (X-API-Key header)

All chat and agent endpoints require a valid token.
The /health endpoint is always public.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from config import get_settings

ALGORITHM = "HS256"
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)


# ── Token models ──────────────────────────────────────────────────────────────

class TokenPayload(BaseModel):
    sub: str
    exp: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


# ── Password utilities ────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


# ── JWT issue / verify ────────────────────────────────────────────────────────

def create_token(username: str) -> TokenResponse:
    cfg = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(hours=cfg.token_expire_hours)
    payload = {"sub": username, "exp": expire}
    token = jwt.encode(payload, cfg.jarvis_secret_key, algorithm=ALGORITHM)
    return TokenResponse(
        access_token=token,
        expires_in=cfg.token_expire_hours * 3600,
    )


def decode_token(token: str) -> TokenPayload:
    cfg = get_settings()
    try:
        data = jwt.decode(token, cfg.jarvis_secret_key, algorithms=[ALGORITHM])
        return TokenPayload(**data)
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── FastAPI dependency ─────────────────────────────────────────────────────────

async def require_auth(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    """Dependency: returns the authenticated username or raises 401."""
    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)
    return payload.sub


# ── Login endpoint helper ──────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> bool:
    """Validate credentials against the configured admin account."""
    cfg = get_settings()
    if username != cfg.jarvis_admin_username:
        return False
    # Compare against the plaintext password from env (acceptable for single-user self-hosted)
    return password == cfg.jarvis_admin_password
