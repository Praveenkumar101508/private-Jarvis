"""P0.2 — Tests for the DEV_MODE boot guard.

Invariant: DEV_MODE=true is only allowed when IRA_DOMAIN is a local/private
address. If someone accidentally sets DEV_MODE=true with a public domain (e.g.
before deploying to a cloud host), the app must refuse to start rather than
expose an unauthenticated admin endpoint on the internet.
"""
import os
import pytest
from unittest.mock import patch

_BASE_ENV = {
    "IRA_SECRET_KEY": "ci-test-secret",
    "IRA_ADMIN_PASSWORD": "ci-test-password",
    "POSTGRES_PASSWORD": "ci-db-pass",
    "REDIS_PASSWORD": "ci-redis-pass",
    "VLLM_API_KEY": "ci-vllm-key",
}


def _clear():
    from config import get_settings
    get_settings.cache_clear()


# ── is_local_domain helper ─────────────────────────────────────────────────────

@pytest.mark.parametrize("domain,expected", [
    ("localhost", True),
    ("127.0.0.1", True),
    ("ira.local", True),
    ("shadow.local", True),
    ("192.168.1.10", True),
    ("10.0.0.1", True),
    ("172.16.0.1", True),
    ("example.com", False),
    ("mybox.tailnet-name.ts.net", False),
    ("ira.mycompany.io", False),
])
def test_is_local_domain(domain, expected):
    env = {**_BASE_ENV, "IRA_DOMAIN": domain, "DEV_MODE": "false"}
    with patch.dict(os.environ, env, clear=False):
        _clear()
        from config import get_settings
        s = get_settings()
        assert s.is_local_domain is expected
        _clear()


# ── DEV_MODE + local domain: must boot ────────────────────────────────────────

@pytest.mark.parametrize("domain", [
    "localhost",
    "127.0.0.1",
    "ira.local",
    "192.168.0.100",
])
def test_dev_mode_on_local_domain_boots(domain):
    env = {**_BASE_ENV, "DEV_MODE": "true", "IRA_DOMAIN": domain}
    with patch.dict(os.environ, env, clear=False):
        _clear()
        from config import get_settings
        s = get_settings()  # must not raise
        assert s.dev_mode is True
        assert s.is_local_domain is True
        _clear()


# ── DEV_MODE + public domain: must refuse ────────────────────────────────────

@pytest.mark.parametrize("domain", [
    "example.com",
    "ira.mycompany.io",
    "shadow.tailnet-name.ts.net",
    "api.jarvis.cloud",
])
def test_dev_mode_on_public_domain_raises(domain):
    env = {**_BASE_ENV, "DEV_MODE": "true", "IRA_DOMAIN": domain}
    with patch.dict(os.environ, env, clear=False):
        _clear()
        from config import get_settings
        with pytest.raises(Exception) as exc_info:
            get_settings()
        msg = str(exc_info.value).lower()
        assert "dev_mode" in msg or "forbidden" in msg or domain.lower() in msg
        _clear()


# ── DEV_MODE=false on public domain: allowed ─────────────────────────────────

def test_dev_mode_false_on_public_domain_boots():
    env = {**_BASE_ENV, "DEV_MODE": "false", "IRA_DOMAIN": "ira.mycompany.io"}
    with patch.dict(os.environ, env, clear=False):
        _clear()
        from config import get_settings
        s = get_settings()  # must not raise
        assert s.dev_mode is False
        _clear()
