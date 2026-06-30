"""M3 — the IRA_* model-selection settings are registered on config.Settings.

Proves the env vars the model-selection layer reads also have a validated,
central home with safe local-first defaults.
"""
import pytest

from config import Settings

_SECRETS = dict(
    ira_secret_key="ci-secret",
    ira_admin_password="ci-admin",
    postgres_password="ci-db",
    redis_password="ci-redis",
)


def test_defaults_are_local_first():
    s = Settings(**_SECRETS)
    assert s.ira_model_profile == "balanced_local"
    assert s.ira_allow_external_api is False
    assert s.ira_require_api_consent is True
    assert s.ira_privacy_mode == "local_first"
    assert s.ira_use_model_router is True


def test_env_overrides_are_read(monkeypatch):
    monkeypatch.setenv("IRA_MODEL_PROFILE", "low_resource")
    monkeypatch.setenv("IRA_ALLOW_EXTERNAL_API", "true")
    monkeypatch.setenv("IRA_PRIVACY_MODE", "local_only")
    monkeypatch.setenv("IRA_USE_MODEL_ROUTER", "false")
    s = Settings(**_SECRETS)
    assert s.ira_model_profile == "low_resource"
    assert s.ira_allow_external_api is True
    assert s.ira_privacy_mode == "local_only"
    assert s.ira_use_model_router is False
