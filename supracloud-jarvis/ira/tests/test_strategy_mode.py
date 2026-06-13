"""Phase 5 — bounded strategy mode: detector, ranked honest result, graceful degrade.

The model is stubbed (no Ollama). Asserts the JSON extractor, deterministic utility
ranking, the honesty fields, and that junk output degrades instead of crashing.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import json

import pytest

import agents.strategy_mode as sm
from agents.strategy_mode import is_strategy_request, run_strategy


# ── Detector ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "Should I use Postgres or MongoDB for this?",
    "What's the best strategy to grow the consulting arm?",
    "Help me weigh the options for hiring now vs later",
    "pros and cons of going fully remote",
    "decide between Tailscale and a VPN",
])
def test_is_strategy_request_positive(q):
    assert is_strategy_request(q) is True


@pytest.mark.parametrize("q", [
    "what time is it",
    "fix the bug in chat.py",
    "remind me to call the bank",
])
def test_is_strategy_request_negative(q):
    assert is_strategy_request(q) is False


# ── JSON extraction (graceful) ────────────────────────────────────────────────

def test_extract_json_from_fenced_and_prose():
    fenced = "Sure!\n```json\n{\"a\": 1}\n```\nthanks"
    assert sm._extract_json(fenced) == {"a": 1}
    assert sm._extract_json("garbage no json here") is None


# ── run_strategy: ranked, honest, deterministic ───────────────────────────────

_GOOD = json.dumps({
    "options": [
        {"name": "Build in-house", "rationale": "Full control", "success_probability": 0.6, "risk": 0.5, "effort": 0.8},
        {"name": "Buy a SaaS", "rationale": "Fast to ship", "success_probability": 0.7, "risk": 0.3, "effort": 0.2},
    ],
    "assumptions": ["Budget is fixed", "Timeline is 3 months"],
    "confidence": 0.55,
    "what_would_change_it": ["A bigger budget", "A hard compliance requirement"],
})


def _stub_llm(monkeypatch, reply):
    async def _fake(messages, **kw):
        return reply
    monkeypatch.setattr(sm, "chat_complete", _fake)


def test_run_strategy_ranks_by_utility_and_keeps_honesty(monkeypatch):
    _stub_llm(monkeypatch, _GOOD)
    res = asyncio.run(run_strategy("Should we build or buy?"))
    assert res.degraded is False
    assert len(res.options) == 2
    # "Buy a SaaS" (higher success, lower risk/effort) must rank first by utility.
    assert res.best().name == "Buy a SaaS"
    assert res.options[0].utility >= res.options[1].utility
    # Honesty fields preserved.
    assert res.assumptions and res.what_would_change_it and 0 <= res.confidence <= 1
    md = res.to_markdown()
    assert "Buy a SaaS" in md and "Assumptions" in md and "What would change this" in md
    spoken = res.to_spoken_summary()
    assert "Buy a SaaS" in spoken and len(spoken) < 400


def test_run_strategy_degrades_on_junk(monkeypatch):
    _stub_llm(monkeypatch, "I think you should just go for it, honestly!")
    res = asyncio.run(run_strategy("Should we expand?"))
    assert res.degraded is True
    assert res.options == [] and res.confidence == 0.0
    # Never crashes — both renderers return a sane message.
    assert res.to_markdown() and res.to_spoken_summary()


def test_run_strategy_handles_model_error(monkeypatch):
    async def _boom(messages, **kw):
        raise RuntimeError("ollama down")
    monkeypatch.setattr(sm, "chat_complete", _boom)
    res = asyncio.run(run_strategy("Should we pivot?"))
    assert res.degraded is True and res.to_spoken_summary()


def test_utility_is_deterministic_and_bounded():
    u_hi = sm._utility(0.9, 0.1, 0.1)
    u_lo = sm._utility(0.3, 0.9, 0.9)
    assert 0 <= u_lo < u_hi <= 1
