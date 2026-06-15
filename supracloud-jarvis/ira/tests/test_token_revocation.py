"""P2.1 — Tests for JWT token revocation, short expiry, and refresh tokens.

All Redis calls are mocked so these tests run without a live Redis instance.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REQUIRED_ENV = {
    "IRA_SECRET_KEY": "ci-test-secret-key-for-jwt",
    "IRA_ADMIN_PASSWORD": "ci-test-password",
    "POSTGRES_PASSWORD": "ci-db-pass",
    "REDIS_PASSWORD": "ci-redis-pass",
    "VLLM_API_KEY": "ci-vllm-key",
    "DEV_MODE": "false",
}


def _clear():
    from config import get_settings
    get_settings.cache_clear()
    # Clear lru_cache on auth helpers
    try:
        from api.middleware import auth as _auth
        _auth._admin_password_hash.cache_clear()
        _auth._dummy_hash.cache_clear()
    except Exception:
        pass


def _make_redis_mock(*, exists_result=0):
    """Return an AsyncMock that mimics aioredis.Redis."""
    r = AsyncMock()
    r.exists = AsyncMock(return_value=exists_result)
    r.setex = AsyncMock(return_value=True)
    r.get = AsyncMock(return_value=None)
    r.incr = AsyncMock(return_value=1)
    return r


# ── create_token / create_login_tokens ────────────────────────────────────────

def test_create_token_has_jti():
    """Access token must carry a jti claim."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import create_token
        resp = create_token("admin")
        from jose import jwt as _jwt
        from config import get_settings
        data = _jwt.decode(resp.access_token, get_settings().ira_secret_key, algorithms=["HS256"])
        assert "jti" in data and data["jti"]
        _clear()


def test_create_token_short_expiry():
    """Access token should expire in ≤ 60 minutes by default."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import create_token
        resp = create_token("admin")
        assert resp.expires_in <= 3600, "Access token should expire in ≤ 60 min"
        _clear()


def test_create_token_type_is_access():
    """Token must have tok='access'."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import create_token
        resp = create_token("admin")
        from jose import jwt as _jwt
        from config import get_settings
        data = _jwt.decode(resp.access_token, get_settings().ira_secret_key, algorithms=["HS256"])
        assert data.get("tok") == "access"
        _clear()


# ── decode_token ──────────────────────────────────────────────────────────────

def test_decode_valid_token():
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import create_token, decode_token
        resp = create_token("admin")
        payload = decode_token(resp.access_token)
        assert payload.sub == "admin"
        assert payload.jti
        _clear()


def test_decode_expired_token_raises():
    """Expired tokens must be rejected."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from config import get_settings
        from jose import jwt as _jwt
        cfg = get_settings()
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        token = _jwt.encode(
            {"sub": "admin", "exp": past, "jti": str(uuid.uuid4()), "tok": "access"},
            cfg.ira_secret_key, algorithm="HS256",
        )
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            from api.middleware.auth import decode_token
            decode_token(token)
        assert exc_info.value.status_code == 401
        _clear()


# ── revocation ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_revoked_jti_is_rejected():
    """require_auth must reject a token whose jti is in the revocation list."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import create_token, _REVOKED_PREFIX

        resp = create_token("admin")
        from jose import jwt as _jwt
        from config import get_settings
        data = _jwt.decode(resp.access_token, get_settings().ira_secret_key, algorithms=["HS256"])
        jti = data["jti"]

        # Redis says this jti is revoked
        redis_mock = _make_redis_mock(exists_result=1)

        with patch("utils.redis_client.get_redis", return_value=redis_mock):
            from fastapi.security import HTTPAuthorizationCredentials
            from fastapi import HTTPException
            creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=resp.access_token)
            with pytest.raises(HTTPException) as exc_info:
                from api.middleware.auth import require_auth
                await require_auth(creds)
            assert exc_info.value.status_code == 401
            assert "revoked" in exc_info.value.detail.lower()

        # Confirm Redis was queried for the right key
        redis_mock.exists.assert_called_once_with(f"{_REVOKED_PREFIX}{jti}")
        _clear()


@pytest.mark.asyncio
async def test_valid_token_not_in_revocation_list_is_accepted():
    """A valid, non-revoked token must be accepted."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import create_token
        resp = create_token("admin")

        redis_mock = _make_redis_mock(exists_result=0)
        redis_mock.get = AsyncMock(return_value="0")  # token version = 0

        with patch("utils.redis_client.get_redis", return_value=redis_mock):
            from fastapi.security import HTTPAuthorizationCredentials
            creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=resp.access_token)
            from api.middleware.auth import require_auth
            username = await require_auth(creds)
        assert username == "admin"
        _clear()


@pytest.mark.asyncio
async def test_revoke_token_sets_redis_key():
    """revoke_token must write the jti to Redis with a TTL."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        redis_mock = _make_redis_mock()
        with patch("utils.redis_client.get_redis", return_value=redis_mock):
            from api.middleware.auth import revoke_token, _REVOKED_PREFIX
            jti = str(uuid.uuid4())
            await revoke_token(jti, 900)
        redis_mock.setex.assert_called_once_with(f"{_REVOKED_PREFIX}{jti}", 900, "1")
        _clear()


# ── logout revokes all (token version bump) ───────────────────────────────────

@pytest.mark.asyncio
async def test_bump_token_version_invalidates_old_token():
    """After bumping version, an old token's ver < current_ver → rejected."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import create_token

        # Token carries ver=0
        resp = create_token("admin")

        # After bump, Redis returns version=1
        redis_mock = _make_redis_mock(exists_result=0)
        redis_mock.get = AsyncMock(return_value="1")  # current version > token's ver

        with patch("utils.redis_client.get_redis", return_value=redis_mock):
            from fastapi.security import HTTPAuthorizationCredentials
            from fastapi import HTTPException
            creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=resp.access_token)
            with pytest.raises(HTTPException) as exc_info:
                from api.middleware.auth import require_auth
                await require_auth(creds)
        assert exc_info.value.status_code == 401
        assert "invalidated" in exc_info.value.detail.lower()
        _clear()


@pytest.mark.asyncio
async def test_bump_token_version_calls_redis_incr():
    """bump_token_version must INCR the version key in Redis."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        redis_mock = _make_redis_mock()
        with patch("utils.redis_client.get_redis", return_value=redis_mock):
            from api.middleware.auth import bump_token_version, _TOKEN_VER_PREFIX
            await bump_token_version("admin")
        redis_mock.incr.assert_called_once_with(f"{_TOKEN_VER_PREFIX}admin")
        _clear()


# ── refresh token type guard ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_refresh_token_cannot_access_api():
    """A refresh token must be rejected by require_auth (wrong tok type)."""
    with patch.dict(os.environ, _REQUIRED_ENV, clear=False):
        _clear()
        from api.middleware.auth import _make_refresh_token
        refresh_tok, _, _ = _make_refresh_token("admin")

        redis_mock = _make_redis_mock(exists_result=0)
        with patch("utils.redis_client.get_redis", return_value=redis_mock):
            from fastapi.security import HTTPAuthorizationCredentials
            from fastapi import HTTPException
            creds = HTTPAuthorizationCredentials(scheme="bearer", credentials=refresh_tok)
            with pytest.raises(HTTPException) as exc_info:
                from api.middleware.auth import require_auth
                await require_auth(creds)
        assert exc_info.value.status_code == 401
        assert "refresh token" in exc_info.value.detail.lower()
        _clear()


# ── Constant-time check ───────────────────────────────────────────────────────
# Bcrypt is mocked throughout — the passlib/bcrypt versions in CI don't
# cooperate (passlib's wrap-bug detection fires with a 216-byte test password
# that newer bcrypt rejects). The real bcrypt path works on the Shadow box.

_FAKE_HASH = "$2b$12$fakehashforunittestingonlyXXXXXXXXXXXXXXXXXXXXX"


def test_authenticate_user_wrong_username_returns_false():
    """authenticate_user must return False for wrong username (verify still called)."""
    with patch.dict(os.environ, {**_REQUIRED_ENV, "IRA_ADMIN_USERNAME": "admin"}, clear=False):
        _clear()
        with patch("api.middleware.auth._admin_password_hash", return_value=_FAKE_HASH), \
             patch("api.middleware.auth._dummy_hash", return_value=_FAKE_HASH), \
             patch("api.middleware.auth.verify_password", return_value=False) as mock_verify:
            from api.middleware.auth import authenticate_user
            result = authenticate_user("notadmin", "wrongpass")
        assert result is False
        assert mock_verify.called, "verify_password must run even for wrong username (constant-time)"
        _clear()


def test_authenticate_user_correct_credentials_returns_true():
    """authenticate_user returns True for correct username + password."""
    with patch.dict(os.environ, {**_REQUIRED_ENV, "IRA_ADMIN_USERNAME": "admin"}, clear=False):
        _clear()
        with patch("api.middleware.auth._admin_password_hash", return_value=_FAKE_HASH), \
             patch("api.middleware.auth._dummy_hash", return_value=_FAKE_HASH), \
             patch("api.middleware.auth.verify_password", return_value=True):
            from api.middleware.auth import authenticate_user
            result = authenticate_user("admin", "ci-test-password")
        assert result is True
        _clear()
