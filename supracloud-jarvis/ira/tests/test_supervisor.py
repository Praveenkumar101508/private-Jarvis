"""Unit tests for agents/supervisor.py — routing and biometric gate logic."""
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


def _setup_env(extra=None):
    env = {**_REQUIRED_ENV, **(extra or {})}
    return patch.dict(os.environ, env)


def _clear_caches():
    from config import get_settings
    get_settings.cache_clear()
    from utils.yaml_config import load_routing_config
    load_routing_config.cache_clear()


# ── is_restricted_domain ──────────────────────────────────────────────────────

def test_restricted_domain_credentials():
    # "credentials" is an exact phrase in restricted_keywords
    with _setup_env():
        _clear_caches()
        from agents.supervisor import is_restricted_domain
        assert is_restricted_domain("show me my credentials") is True


def test_restricted_domain_api_key():
    # "api key" is an exact phrase in restricted_keywords
    with _setup_env():
        _clear_caches()
        from agents.supervisor import is_restricted_domain
        assert is_restricted_domain("what is my api key for this service") is True


def test_restricted_domain_show_logs():
    # "show logs" is an exact phrase in restricted_keywords
    with _setup_env():
        _clear_caches()
        from agents.supervisor import is_restricted_domain
        assert is_restricted_domain("show logs from nginx") is True


def test_restricted_domain_safe_query():
    with _setup_env():
        _clear_caches()
        from agents.supervisor import is_restricted_domain
        assert is_restricted_domain("what is the weather today") is False


def test_restricted_domain_safe_math():
    with _setup_env():
        _clear_caches()
        from agents.supervisor import is_restricted_domain
        assert is_restricted_domain("what is 2 + 2") is False


def test_restricted_domain_owner_first_name():
    with _setup_env({"OWNER_NAME": "Praveen Kumar Kamineti"}):
        _clear_caches()
        from agents.supervisor import is_restricted_domain
        # owner's first name triggers restriction
        assert is_restricted_domain("praveen's schedule for today") is True


def test_restricted_domain_owner_name_case_insensitive():
    with _setup_env({"OWNER_NAME": "Praveen Kumar"}):
        _clear_caches()
        from agents.supervisor import is_restricted_domain
        assert is_restricted_domain("PRAVEEN update my calendar") is True


# ── classify routing ──────────────────────────────────────────────────────────

def _make_state(query, mode="assistant"):
    return {
        "user_query": query,
        "mode": mode,
        "messages": [], "session_id": "test", "conversation_id": "test",
        "active_agent": "", "use_deep_model": False, "memory_context": "",
        "final_response": "", "stream_tokens": [], "latency_ms": 0,
        "model_used": "", "is_voice": False, "user_id": "test",
        "error": None, "is_owner": False, "clearance_level": "public",
    }


@pytest.mark.asyncio
async def test_classify_security_keyword_hack():
    # "hack" is in security agent_rules
    with _setup_env():
        _clear_caches()
        from agents.supervisor import classify
        result = await classify(_make_state("someone is trying to hack my server"))
        assert result["active_agent"] == "security"


@pytest.mark.asyncio
async def test_classify_executor_keyword():
    # "execute" is in executor agent_rules
    with _setup_env():
        _clear_caches()
        from agents.supervisor import classify
        result = await classify(_make_state("execute this script now"))
        assert result["active_agent"] == "executor"


@pytest.mark.asyncio
async def test_classify_tutor_mode_override():
    # mode=tutor should force tutor agent regardless of keywords
    with _setup_env():
        _clear_caches()
        from agents.supervisor import classify
        result = await classify(_make_state("explain recursion to me", mode="tutor"))
        assert result["active_agent"] == "tutor"


@pytest.mark.asyncio
async def test_classify_returns_valid_agent_for_greeting():
    with _setup_env():
        _clear_caches()
        from agents.supervisor import classify, _VALID_AGENTS
        result = await classify(_make_state("hello"))
        assert result["active_agent"] in _VALID_AGENTS


@pytest.mark.asyncio
async def test_classify_sets_use_deep_model():
    with _setup_env():
        _clear_caches()
        from agents.supervisor import classify
        result = await classify(_make_state("hack attempt detected on firewall"))
        # security agent always uses deep model
        assert "use_deep_model" in result
        assert isinstance(result["use_deep_model"], bool)
