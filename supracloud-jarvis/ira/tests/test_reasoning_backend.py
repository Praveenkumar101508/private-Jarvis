"""V1·Phase 2 — the reasoning-backend abstraction makes Cortex genuinely optional
and fixes the VLLM_API_KEY-required-on-Ollama papercut.

These tests are the spec for "Cortex optional":
  * IRA starts on `mock` with no keys at all.
  * IRA starts on `ollama` with no VLLM key.
  * `vllm` / `cortex` REFUSE to start when their secret / binary is missing.
  * Routing works against the typed interface (a consumer that only knows
    ReasoningBackend gets a usable reply from the mock).
"""
import os
import pytest

from reasoning import (
    CortexBackend,
    LocalLLMBackend,
    MockBackend,
    ReasoningBackendError,
    get_reasoning_backend,
    make_backend,
)

# Infra secrets a full Settings needs (auth/db/redis) — NOT the vLLM backend key.
_INFRA_ENV = {
    "IRA_SECRET_KEY": "ci-secret",
    "IRA_ADMIN_PASSWORD": "ci-admin",
    "POSTGRES_PASSWORD": "ci-db",
    "REDIS_PASSWORD": "ci-redis",
}


def _clear_settings():
    from config import get_settings

    get_settings.cache_clear()


# ── Selection ──────────────────────────────────────────────────────────────

def test_make_backend_by_name():
    assert isinstance(make_backend("ollama"), LocalLLMBackend)
    assert isinstance(make_backend("vllm"), LocalLLMBackend)
    assert isinstance(make_backend("cortex"), CortexBackend)
    assert isinstance(make_backend("mock"), MockBackend)


def test_unknown_backend_rejected():
    with pytest.raises(ReasoningBackendError):
        make_backend("gpt5-cloud")


def test_env_selects_backend(monkeypatch):
    monkeypatch.setenv("IRA_LLM_BACKEND", "mock")
    assert get_reasoning_backend().name == "mock"


# ── Per-backend secret validation ──────────────────────────────────────────

def test_mock_starts_with_no_keys(monkeypatch):
    """`mock` needs nothing — no env at all."""
    for k in (*_INFRA_ENV, "VLLM_API_KEY", "IRA_LLM_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    backend = get_reasoning_backend("mock")  # validate=True by default
    assert isinstance(backend, MockBackend)


def test_ollama_starts_without_vllm_key(monkeypatch):
    """`ollama` is the local-first default and must not require a vLLM key."""
    monkeypatch.delenv("VLLM_API_KEY", raising=False)
    backend = get_reasoning_backend("ollama")
    assert backend.name == "ollama"  # validate() did not raise


def test_vllm_refuses_without_key():
    with pytest.MonkeyPatch.context() as mp:
        for k, v in _INFRA_ENV.items():
            mp.setenv(k, v)
        mp.delenv("VLLM_API_KEY", raising=False)
        mp.setenv("LLM_BACKEND", "ollama")  # keep Settings itself valid
        _clear_settings()
        with pytest.raises(ReasoningBackendError):
            get_reasoning_backend("vllm")
    _clear_settings()


def test_cortex_refuses_when_binary_missing(monkeypatch):
    # No cortex binary is installed in the test env; point the bin at a sure-miss.
    monkeypatch.setenv("IRA_CORTEX_BIN", "/nonexistent/cortex-binary-xyz")
    with pytest.raises(ReasoningBackendError):
        get_reasoning_backend("cortex")


# ── Routing against the typed interface ────────────────────────────────────

async def _route(backend, system: str, prompt: str) -> str:
    """A tiny consumer that only knows the ReasoningBackend contract."""
    return await backend.complete(system, prompt, use_deep=False)


@pytest.mark.asyncio
async def test_routing_against_mock_interface():
    backend = get_reasoning_backend("mock")
    out = await _route(backend, "system", "hello world")
    assert "hello world" in out
    assert out.startswith("[mock:")


@pytest.mark.asyncio
async def test_mock_reply_is_injectable():
    backend = MockBackend(reply="canned")
    assert await backend.complete("s", "p") == "canned"


# ── Config papercut: vLLM key required ONLY when vLLM is selected ───────────

def test_settings_load_on_ollama_without_vllm_key():
    env = {**_INFRA_ENV, "LLM_BACKEND": "ollama"}
    with pytest.MonkeyPatch.context() as mp:
        for k in ("VLLM_API_KEY",):
            mp.delenv(k, raising=False)
        for k, v in env.items():
            mp.setenv(k, v)
        _clear_settings()
        from config import get_settings

        s = get_settings()
        assert s.llm_backend == "ollama"
        assert s.vllm_api_key == ""  # blank is fine on the local-first path
    _clear_settings()


def test_settings_reject_vllm_backend_without_key():
    env = {**_INFRA_ENV, "LLM_BACKEND": "vllm"}
    with pytest.MonkeyPatch.context() as mp:
        mp.delenv("VLLM_API_KEY", raising=False)
        for k, v in env.items():
            mp.setenv(k, v)
        _clear_settings()
        from config import get_settings

        with pytest.raises(RuntimeError):
            get_settings()
    _clear_settings()
