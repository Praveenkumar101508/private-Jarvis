"""Prompt 4.4 — the voice owner-gate decision (fail-closed)."""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
from unittest.mock import AsyncMock

import voice.biometrics as bio
from voice.gate import decide_access, gate_from_audio


def test_decide_access_owner_gets_full():
    d = decide_access(True)
    assert d["is_owner"] is True
    assert d["clearance"] == "admin"
    assert d["restricted_allowed"] is True


def test_decide_access_non_owner_is_limited():
    d = decide_access(False)
    assert d["is_owner"] is False
    assert d["clearance"] == "public"
    assert d["restricted_allowed"] is False


def test_gate_from_audio_owner(monkeypatch):
    monkeypatch.setattr(bio, "is_owner_authenticated", AsyncMock(return_value=True))
    d = asyncio.run(gate_from_audio(b"x" * 32000, session_id="s1"))
    assert d["is_owner"] is True and d["clearance"] == "admin"


def test_gate_from_audio_non_owner(monkeypatch):
    monkeypatch.setattr(bio, "is_owner_authenticated", AsyncMock(return_value=False))
    d = asyncio.run(gate_from_audio(b"x" * 32000))
    assert d["is_owner"] is False and d["restricted_allowed"] is False


def test_gate_from_audio_fails_closed_on_error(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("model unavailable")
    monkeypatch.setattr(bio, "is_owner_authenticated", boom)
    d = asyncio.run(gate_from_audio(b"x" * 32000))
    assert d["is_owner"] is False     # any error -> NOT owner
