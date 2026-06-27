"""Phase 5 — weaker-than-they-look guards: fail-closed auth + dev-mode bind guard.

(a) auth revocation must be able to FAIL CLOSED on a Redis error (opt-in flag),
    while preserving the default fail-open availability behaviour.
(d) the DEV_MODE startup guard must not trust the IRA_DOMAIN label alone — a
    non-loopback API bind host with DEV_MODE on is refused unless explicitly allowed.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import api.middleware.auth as auth
from config import Settings, _is_loopback_host


# ── (a) fail-closed revocation ────────────────────────────────────────────────

def _patch_redis_raises(monkeypatch):
    def _boom():
        raise ConnectionError("redis down")
    monkeypatch.setattr("utils.redis_client.get_redis", _boom)


def _patch_fail_closed(monkeypatch, value: bool):
    monkeypatch.setattr(auth, "get_settings",
                        lambda: SimpleNamespace(auth_fail_closed_on_redis=value))


def test_is_revoked_fails_open_by_default(monkeypatch):
    _patch_redis_raises(monkeypatch)
    _patch_fail_closed(monkeypatch, False)
    assert asyncio.run(auth._is_revoked("jti-1")) is False     # fail open: not revoked


def test_is_revoked_fails_closed_when_enabled(monkeypatch):
    _patch_redis_raises(monkeypatch)
    _patch_fail_closed(monkeypatch, True)
    assert asyncio.run(auth._is_revoked("jti-1")) is True       # fail closed: treat as revoked


def test_token_version_fails_open_by_default(monkeypatch):
    _patch_redis_raises(monkeypatch)
    _patch_fail_closed(monkeypatch, False)
    assert asyncio.run(auth._get_token_version("user")) == 0    # fail open: version 0


def test_token_version_fails_closed_when_enabled(monkeypatch):
    _patch_redis_raises(monkeypatch)
    _patch_fail_closed(monkeypatch, True)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(auth._get_token_version("user"))
    assert ei.value.status_code == 503


# ── (d) dev-mode bind-host guard ──────────────────────────────────────────────

def test_loopback_helper():
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("localhost")
    assert _is_loopback_host("::1")
    assert not _is_loopback_host("0.0.0.0")     # all interfaces — exposed
    assert not _is_loopback_host("10.0.0.5")    # RFC1918 — exposed on LAN
    assert not _is_loopback_host("example.com")


_BASE = dict(
    ira_secret_key="x", ira_admin_password="y", postgres_password="z",
    redis_password="w", vllm_api_key="v", ira_domain="localhost",
)


def test_dev_mode_with_nonloopback_bind_is_refused():
    with pytest.raises(RuntimeError) as ei:
        Settings(dev_mode=True, api_bind_host="0.0.0.0",
                 allow_dev_mode_exposed=False, **_BASE)
    assert "non-loopback" in str(ei.value).lower() or "API_BIND_HOST" in str(ei.value)


def test_dev_mode_nonloopback_allowed_with_optin():
    s = Settings(dev_mode=True, api_bind_host="0.0.0.0",
                 allow_dev_mode_exposed=True, **_BASE)
    assert s.dev_mode and s.allow_dev_mode_exposed


def test_dev_mode_loopback_bind_is_fine():
    s = Settings(dev_mode=True, api_bind_host="127.0.0.1",
                 allow_dev_mode_exposed=False, **_BASE)
    assert s.api_bind_host == "127.0.0.1"
