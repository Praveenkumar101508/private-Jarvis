"""Phase 4 — both engines (Ollama-direct and Cortex) return non-empty output, and
the voice path pins the fast (qwen3:8b) tier.

No real Ollama or Cortex is needed: the Ollama OpenAI client and the `cortex -z`
subprocess are mocked. This asserts the two bridges IRA toggles between with
IRA_USE_CORTEX both produce a usable reply, and that fast/deep tiers resolve to the
right Ollama tags after the Phase 4 model split.
"""
import os

# Settings require these to be present; prime them before importing config-backed code.
for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import utils.llm as llm
import cortex_bridge
from cortex_bridge import CortexBridge, CortexConfig
from config import get_settings


# ── Ollama-direct engine (IRA_USE_CORTEX=false) ───────────────────────────────

class _FakeCompletions:
    last_model: str | None = None

    def __init__(self, text: str):
        self._text = text

    async def create(self, **kwargs):
        _FakeCompletions.last_model = kwargs.get("model")
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self._text))]
        )


def _fake_client(text: str):
    return SimpleNamespace(chat=SimpleNamespace(completions=_FakeCompletions(text)))


async def test_ollama_voice_engine_returns_nonempty_fast_8b(monkeypatch):
    """The default (voice) tier returns text AND resolves to the fast 8B model."""
    monkeypatch.setattr(llm, "_use_ollama", lambda: True)
    monkeypatch.setattr(llm, "get_fast_client", lambda: _fake_client("It is three o'clock."))
    out = await llm.chat_complete(
        [{"role": "user", "content": "what time is it"}], use_deep=False
    )
    assert out.strip(), "Ollama fast engine returned empty output"
    assert _FakeCompletions.last_model == get_settings().ollama_model_fast == "qwen3:8b"


async def test_ollama_deep_engine_resolves_14b(monkeypatch):
    """The deep tier resolves to the 14B model (kept distinct from the fast tier)."""
    monkeypatch.setattr(llm, "_use_ollama", lambda: True)
    monkeypatch.setattr(llm, "get_deep_client", lambda: _fake_client("A considered answer."))
    out = await llm.chat_complete(
        [{"role": "user", "content": "explain quantum tunnelling"}], use_deep=True
    )
    assert out.strip()
    assert _FakeCompletions.last_model == get_settings().ollama_model_deep == "qwen3:14b"


# ── Cortex engine (IRA_USE_CORTEX=true) ───────────────────────────────────────

def test_cortex_engine_returns_nonempty(monkeypatch):
    """`cortex -z` (mocked subprocess) yields a non-empty final reply."""
    run = MagicMock(
        return_value=SimpleNamespace(stdout="It is three o'clock.", stderr="", returncode=0)
    )
    monkeypatch.setattr(cortex_bridge.subprocess, "run", run)
    out = CortexBridge(CortexConfig()).ask("what time is it", system="Reply in one sentence.")
    assert out.strip(), "Cortex engine returned empty output"
    # The system prompt is prepended to the one-shot prompt (no separate channel).
    assert run.call_args.args[0][-1].startswith("Reply in one sentence.")
