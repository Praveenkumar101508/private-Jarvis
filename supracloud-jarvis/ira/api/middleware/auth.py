"""
JWT authentication middleware.

Token model (P2.1):
  - Access tokens: 30-min expiry, carry `jti` (JWT ID) and per-user `ver`
  - Refresh tokens: 7-day expiry, carry `jti`; only valid at /auth/refresh
  - Revocation: Redis key  ira:revoked:{jti}  with TTL = token remaining life
  - Revoke-all:  Redis key  ira:token_ver:{username}  (INCR to invalidate all)

Two credential types:
  - Bearer JWT  → standard API access (issued at /auth/token)
  - API Key     → for service-to-service calls (X-API-Key header)

Dev mode: when DEV_MODE=true, require_auth returns the admin username
without checking any token. NEVER enable in production.
"""

from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache as _lru_cache

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from config import get_settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_bearer = HTTPBearer(auto_error=False)

# Redis key prefixes
_REVOKED_PREFIX = "ira:revoked:"
_TOKEN_VER_PREFIX = "ira:token_ver:"


# ── Token models ──────────────────────────────────────────────────────────────

class TokenPayload(BaseModel):
    sub: str
    exp: datetime
    jti: str = ""
    tok: str = "access"   # "access" | "refresh"
    ver: int = 0          # per-user version bump counter (revoke-all)


class TokenResponse(BaseModel):
    """Slim response — single access token (used by /auth/refresh)."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class LoginResponse(BaseModel):
    """Full login response — access + refresh tokens."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int          # access token seconds remaining
    refresh_expires_in: int  # refresh token seconds remaining


# ── Password utilities ────────────────────────────────────────────────────────

def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


# ── Redis revocation helpers ──────────────────────────────────────────────────

async def _is_revoked(jti: str) -> bool:
    """True if the jti is in the Redis revocation set. Fail-open on Redis error."""
    if not jti:
        return False
    try:
        from utils.redis_client import get_redis
        return bool(await get_redis().exists(f"{_REVOKED_PREFIX}{jti}"))
    except Exception as e:
        logger.warning("Redis revocation check failed (fail-open): %s", e)
        return False


async def revoke_token(jti: str, ttl_seconds: int) -> None:
    """Add jti to the revocation list. TTL should match remaining token life."""
    if not jti or ttl_seconds <= 0:
        return
    try:
        from utils.redis_client import get_redis
        await get_redis().setex(f"{_REVOKED_PREFIX}{jti}", ttl_seconds, "1")
    except Exception as e:
        logger.warning("Redis revoke_token failed: %s", e)


async def _get_token_version(username: str) -> int:
    """Current per-user token version (0 = never bumped)."""
    try:
        from utils.redis_client import get_redis
        v = await get_redis().get(f"{_TOKEN_VER_PREFIX}{username}")
        return int(v) if v else 0
    except Exception:
        return 0


async def bump_token_version(username: str) -> None:
    """Increment token version — invalidates ALL existing access tokens for user."""
    try:
        from utils.redis_client import get_redis
        await get_redis().incr(f"{_TOKEN_VER_PREFIX}{username}")
    except Exception as e:
        logger.warning("Redis bump_token_version failed: %s", e)


# ── JWT issue helpers ─────────────────────────────────────────────────────────

def _make_access_token(username: str, ver: int = 0) -> tuple[str, str, datetime]:
    """Returns (encoded_token, jti, expiry_utc)."""
    cfg = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=cfg.access_token_expire_minutes)
    jti = str(uuid.uuid4())
    payload = {"sub": username, "exp": expire, "jti": jti, "tok": "access", "ver": ver}
    token = jwt.encode(payload, cfg.ira_secret_key, algorithm=ALGORITHM)
    return token, jti, expire


def _make_refresh_token(username: str) -> tuple[str, str, datetime]:
    """Returns (encoded_token, jti, expiry_utc)."""
    cfg = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(days=cfg.refresh_token_expire_days)
    jti = str(uuid.uuid4())
    payload = {"sub": username, "exp": expire, "jti": jti, "tok": "refresh"}
    token = jwt.encode(payload, cfg.ira_secret_key, algorithm=ALGORITHM)
    return token, jti, expire


async def create_login_tokens(username: str) -> LoginResponse:
    """Issue access + refresh tokens. Call this at /auth/token login."""
    ver = await _get_token_version(username)
    access_token, _, access_exp = _make_access_token(username, ver=ver)
    refresh_token, _, refresh_exp = _make_refresh_token(username)
    now = datetime.now(timezone.utc)
    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=max(0, int((access_exp - now).total_seconds())),
        refresh_expires_in=max(0, int((refresh_exp - now).total_seconds())),
    )


def create_token(username: str) -> TokenResponse:
    """Synchronous single-token issue (backward compat / testing only).

    Does not embed a per-user version because no Redis is available. For
    production login use create_login_tokens() which is async and embeds ver.
    """
    token, _, expire = _make_access_token(username)
    now = datetime.now(timezone.utc)
    return TokenResponse(
        access_token=token,
        expires_in=max(0, int((expire - now).total_seconds())),
    )


# ── JWT decode ────────────────────────────────────────────────────────────────

def decode_token(token: str) -> TokenPayload:
    """Validate JWT signature + expiry. Returns the payload."""
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
    """Dependency: returns the authenticated username or raises 401.

    Checks (in order):
      1. DEV_MODE bypass (local only)
      2. JWT signature + expiry
      3. Token type (refresh tokens may not be used for API access)
      4. jti revocation list (Redis)
      5. Per-user token version (revoke-all)
    """
    cfg = get_settings()

    if cfg.dev_mode:
        return cfg.ira_admin_username

    if creds is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(creds.credentials)

    if payload.tok == "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token cannot be used for API access — use /auth/refresh",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.jti and await _is_revoked(payload.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    current_ver = await _get_token_version(payload.sub)
    if current_ver > payload.ver:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="All tokens invalidated — please log in again",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload.sub


def is_owner(username: str) -> bool:
    """True when `username` is the verified system owner (admin)."""
    return username == get_settings().ira_admin_username


# ── Login endpoint helper ──────────────────────────────────────────────────────

@_lru_cache(maxsize=1)
def _admin_password_hash() -> str:
    """Hash the admin password once on first use and cache it in-process."""
    return hash_password(get_settings().ira_admin_password)


@_lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Stable dummy hash for constant-time comparison when username is wrong."""
    return hash_password("dummy_constant_time_placeholder_xK9mQ2")


def authenticate_user(username: str, password: str) -> bool:
    """Validate credentials against the configured admin account.

    Always runs bcrypt regardless of whether the username matches to prevent
    username enumeration via response-time differences.
    """
    cfg = get_settings()
    if cfg.dev_mode:
        return True

    username_matches = secrets.compare_digest(
        username.encode("utf-8"),
        cfg.ira_admin_username.encode("utf-8"),
    )
    hash_to_check = _admin_password_hash() if username_matches else _dummy_hash()
    password_matches = verify_password(password, hash_to_check)
    return username_matches and password_matches
