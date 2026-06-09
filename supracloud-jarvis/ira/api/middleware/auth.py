"""
JWT authentication middleware.

Two token types:
  - Bearer JWT  → standard API access (issued at /auth/token)
  - API Key     → for service-to-service calls (X-API-Key header)

Dev mode: when DEV_MODE=true, require_auth returns the admin username
without checking any token. NEVER enable in production.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache as _lru_cache

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
    token = jwt.encode(payload, cfg.ira_secret_key, algorithm=ALGORITHM)
    return TokenResponse(
        access_token=token,
        expires_in=cfg.token_expire_hours * 3600,
    )


def decode_token(token: str) -> TokenPayload:
    cfg = get_settings()
    try:
        data = jwt.decode(token, cfg.ira_secret_key, algorithms=[ALGORITHM])
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
    """
    Dependency: returns the authenticated username or raises 401.
    In DEV_MODE, skips token validation and auto-returns the admin username.
    """
    cfg = get_settings()

    # Dev mode: bypass all auth — localhost only, never production
    if cfg.dev_mode:
        return cfg.ira_admin_username

    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(creds.credentials)
    return payload.sub


def is_owner(username: str) -> bool:
    """True when `username` is the verified system owner (admin).

    The shared owner check used by high-stakes action endpoints (calendar, files,
    …) so they can fail-closed for non-owners.
    """
    return username == get_settings().ira_admin_username


# ── Login endpoint helper ──────────────────────────────────────────────────────

@_lru_cache(maxsize=1)
def _admin_password_hash() -> str:
    """Hash the admin password once on first use and cache it in-process."""
    return hash_password(get_settings().ira_admin_password)


@_lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Stable dummy hash used for constant-time comparison when username is wrong."""
    return hash_password("dummy_constant_time_placeholder_xK9mQ2")


def authenticate_user(username: str, password: str) -> bool:
    """
    Validate credentials against the configured admin account.

    Always runs bcrypt regardless of whether the username matches — this
    prevents username enumeration via response-time differences (~1ms early
    return vs ~100ms bcrypt).
    """
    cfg = get_settings()
    if cfg.dev_mode:
        return True  # Accept any credentials in dev mode

    # Constant-time username comparison
    username_matches = secrets.compare_digest(
        username.encode("utf-8"),
        cfg.ira_admin_username.encode("utf-8"),
    )
    # Always run bcrypt — pick real hash if username matched, dummy otherwise
    hash_to_check = _admin_password_hash() if username_matches else _dummy_hash()
    password_matches = verify_password(password, hash_to_check)
    # Both must be True — don't short-circuit to preserve timing
    return username_matches and password_matches
