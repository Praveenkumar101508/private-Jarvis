"""V2·Phase 1 — IRA_MODE=portable_demo composes the V1-hardened settings and is a
guard rail: it refuses to start if any hardened default is overridden to unsafe."""
import pytest

_INFRA = {
    "IRA_SECRET_KEY": "ci-secret",
    "IRA_ADMIN_PASSWORD": "ci-admin",
    "POSTGRES_PASSWORD": "ci-db",
    "REDIS_PASSWORD": "ci-redis",
}


def _clear():
    from config import get_settings

    get_settings.cache_clear()


def _settings(env: dict):
    with pytest.MonkeyPatch.context() as mp:
        # start from a clean slate for the egress/backend levers
        for k in ("WEB_SEARCH_ENABLED", "IRA_USE_CORTEX", "VLLM_API_KEY",
                  "ANDROID_ACTUATOR_ENABLED", "DEV_MODE", "API_BIND_HOST", "LLM_BACKEND"):
            mp.delenv(k, raising=False)
        for k, v in {**_INFRA, **env}.items():
            mp.setenv(k, v)
        _clear()
        from config import get_settings

        return get_settings()


def test_portable_demo_loads_with_safe_defaults():
    s = _settings({"IRA_MODE": "portable_demo"})
    assert s.ira_mode == "portable_demo"
    assert s.web_search_enabled is False
    assert s.llm_backend == "ollama"
    assert s.dev_mode is False
    assert s.api_bind_host == "127.0.0.1"
    _clear()


@pytest.mark.parametrize("bad", [
    {"WEB_SEARCH_ENABLED": "true"},
    {"LLM_BACKEND": "vllm", "VLLM_API_KEY": "k"},
    {"IRA_USE_CORTEX": "true"},
    {"ANDROID_ACTUATOR_ENABLED": "true"},
    {"DEV_MODE": "true", "API_BIND_HOST": "127.0.0.1"},
    {"API_BIND_HOST": "0.0.0.0"},
])
def test_portable_demo_refuses_unsafe_override(bad):
    with pytest.raises(RuntimeError):
        _settings({"IRA_MODE": "portable_demo", **bad})
    _clear()


def test_standard_mode_unaffected():
    # standard mode imposes no portable guard rail
    s = _settings({"IRA_MODE": "standard", "WEB_SEARCH_ENABLED": "true"})
    assert s.web_search_enabled is True
    _clear()
