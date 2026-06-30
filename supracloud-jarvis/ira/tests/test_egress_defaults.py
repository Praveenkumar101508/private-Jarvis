"""V1·Phase 4 — honest defaults: external egress is OFF unless explicitly enabled.

IRA is local-first. With no opt-in env, the default config must not make any
external call: web search is disabled, the image provider is local, and the cloud
provider tokens (Replicate / Apify) are empty.
"""
import os

import pytest

_INFRA_ENV = {
    "IRA_SECRET_KEY": "ci-secret",
    "IRA_ADMIN_PASSWORD": "ci-admin",
    "POSTGRES_PASSWORD": "ci-db",
    "REDIS_PASSWORD": "ci-redis",
    "LLM_BACKEND": "ollama",
}


def _clear_settings():
    from config import get_settings

    get_settings.cache_clear()


def _default_settings():
    """Settings with ONLY infra secrets set — i.e. no egress opt-in at all."""
    with pytest.MonkeyPatch.context() as mp:
        for k in ("WEB_SEARCH_ENABLED", "IMAGE_GEN_PROVIDER", "REPLICATE_API_TOKEN",
                  "APIFY_API_TOKEN", "VLLM_API_KEY"):
            mp.delenv(k, raising=False)
        for k, v in _INFRA_ENV.items():
            mp.setenv(k, v)
        _clear_settings()
        from config import get_settings

        return get_settings()


def test_web_search_off_by_default():
    s = _default_settings()
    assert s.web_search_enabled is False
    _clear_settings()


def test_image_provider_is_local_by_default():
    s = _default_settings()
    assert s.image_gen_provider in {"sd_webui", "comfyui"}
    assert s.image_gen_provider != "replicate"
    _clear_settings()


def test_cloud_tokens_empty_by_default():
    s = _default_settings()
    assert s.replicate_api_token == ""
    assert s.apify_api_token == ""
    assert s.tavily_api_key == ""
    assert s.serper_api_key == ""
    _clear_settings()


@pytest.mark.asyncio
async def test_web_search_makes_no_call_when_disabled(monkeypatch):
    """With the default (disabled) config, web_search returns [] WITHOUT dispatching
    to any provider — proven by making every provider call explode if reached."""
    _default_settings()  # primes the cached Settings with egress off

    import utils.search_tools as st

    def _boom(*a, **k):  # any provider dispatch is a failure here
        raise AssertionError("external search provider was called while disabled")

    for fn in ("_ddg_search", "_searxng_search", "_tavily_search", "_serper_search"):
        if hasattr(st, fn):
            monkeypatch.setattr(st, fn, _boom)

    out = await st.web_search("anything at all")
    assert out == []
    _clear_settings()


@pytest.mark.asyncio
async def test_web_search_dispatches_when_opted_in(monkeypatch):
    """Opt-in works: enabling the flag lets the dispatch run (proving the gate is the
    only thing standing between default-off and a real call)."""
    with pytest.MonkeyPatch.context() as mp:
        for k, v in _INFRA_ENV.items():
            mp.setenv(k, v)
        mp.setenv("WEB_SEARCH_ENABLED", "true")
        mp.setenv("WEB_SEARCH_PROVIDER", "duckduckgo")
        _clear_settings()

        import utils.search_tools as st

        sentinel = [{"title": "t", "url": "u", "snippet": "s"}]
        monkeypatch.setattr(st, "_ddg_search", lambda q, n: sentinel)

        out = await st.web_search("hello")
        assert out == sentinel
    _clear_settings()
