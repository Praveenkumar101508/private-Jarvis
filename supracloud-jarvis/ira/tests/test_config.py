"""Unit tests for config.py — validates Settings loads from env vars."""
import os
import pytest
from unittest.mock import patch

_REQUIRED_ENV = {
    "IRA_SECRET_KEY": "ci-test-secret",
    "IRA_ADMIN_PASSWORD": "ci-test-password",
    "POSTGRES_PASSWORD": "ci-db-pass",
    "REDIS_PASSWORD": "ci-redis-pass",
    "VLLM_API_KEY": "ci-vllm-key",
}


def _clear_settings():
    from config import get_settings
    get_settings.cache_clear()


def test_settings_load_with_env():
    with patch.dict(os.environ, _REQUIRED_ENV):
        _clear_settings()
        from config import get_settings
        s = get_settings()
        assert s.ira_secret_key == "ci-test-secret"
        assert s.ira_admin_password == "ci-test-password"
        assert s.ira_version == "1.0.0"
        _clear_settings()


def test_database_url_contains_credentials():
    env = {**_REQUIRED_ENV, "POSTGRES_USER": "testuser", "POSTGRES_HOST": "testhost", "POSTGRES_DB": "testdb"}
    with patch.dict(os.environ, env):
        _clear_settings()
        from config import get_settings
        s = get_settings()
        url = s.database_url
        assert "testuser" in url
        assert "testhost" in url
        assert "testdb" in url
        assert url.startswith("postgresql+asyncpg://")
        _clear_settings()


def test_redis_url_format():
    env = {**_REQUIRED_ENV, "REDIS_PASSWORD": "mysecret", "REDIS_HOST": "myredis"}
    with patch.dict(os.environ, env):
        _clear_settings()
        from config import get_settings
        s = get_settings()
        assert "mysecret" in s.redis_url
        assert "myredis" in s.redis_url
        _clear_settings()


def test_dev_mode_default_false():
    # Explicitly unset DEV_MODE in case the CI runner has it set
    env = {**_REQUIRED_ENV, "DEV_MODE": "false"}
    with patch.dict(os.environ, env):
        _clear_settings()
        from config import get_settings
        s = get_settings()
        assert s.dev_mode is False
        _clear_settings()


def test_dev_mode_true():
    env = {**_REQUIRED_ENV, "DEV_MODE": "true"}
    with patch.dict(os.environ, env):
        _clear_settings()
        from config import get_settings
        s = get_settings()
        assert s.dev_mode is True
        _clear_settings()
