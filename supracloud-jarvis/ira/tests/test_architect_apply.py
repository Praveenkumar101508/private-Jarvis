"""Prompt 1.5 — the chat `architect apply` branch must really apply, not dry-run.

Regression for the bug where chat_stream's apply branch called apply_implementation()
with the default dry_run=True (validate-only) while streaming "Applying…" and clearing
pending state as if applied. The explicit, human-gated `architect apply` is the REAL
local apply (git apply -> commit -> restart, NO remote push), so it must pass
dry_run=False — matching POST /architect/apply.

The broad proposal regex also matches the word "architect", so the architect/implement
predicates are mocked off here to make the apply branch reachable in isolation.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

_st = sys.modules.get("sentence_transformers")
if _st is not None and not hasattr(_st, "SentenceTransformer"):
    _st.SentenceTransformer = object

import api.routes.chat as chatmod
from api.routes.chat import ChatRequest, chat_stream


class _Cfg:
    ira_admin_username = "owner"
    ira_voice_service_username = "ira-voice"
    dev_mode = True            # skips the biometric/restricted-domain gate
    owner_name = "Praveen"


async def _drive_apply(monkeypatch, *, success: bool):
    monkeypatch.setattr(chatmod, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv1"))
    monkeypatch.setattr(chatmod, "retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr(chatmod, "_USE_HERMES", False)
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "conversational", "use_deep_model": False}))

    # Make the apply branch reachable: proposal/implement predicates off, apply on.
    monkeypatch.setattr("agents.architect_agent.is_architect_trigger", lambda q: False)
    monkeypatch.setattr("agents.architect_agent.is_implement_trigger", lambda q: False)
    monkeypatch.setattr("agents.architect_agent.is_apply_trigger", lambda q: True)

    monkeypatch.setattr("api.routes.architect._get_state",
                        AsyncMock(return_value={"implementation": "PATCH-DIFF", "pending_apply": True}))
    set_state = AsyncMock()
    monkeypatch.setattr("api.routes.architect._set_state", set_state)

    apply_impl = AsyncMock(return_value=SimpleNamespace(
        success=success, message="✅ applied" if success else "❌ failed", error=None,
    ))
    monkeypatch.setattr("utils.auto_implement.apply_implementation", apply_impl)

    resp = await chat_stream(ChatRequest(message="architect apply", session_id="s1"), _user="owner")
    async for _ in resp.body_iterator:   # drive the SSE generator to run apply_stream
        pass
    return apply_impl, set_state


def test_apply_passes_dry_run_false_and_clears_state_on_success(monkeypatch):
    apply_impl, set_state = asyncio.run(_drive_apply(monkeypatch, success=True))

    assert apply_impl.called, "apply branch must call apply_implementation"
    assert apply_impl.call_args.kwargs.get("dry_run") is False, \
        "explicit `architect apply` must really apply (dry_run=False), not validate-only"

    # On success the pending state is cleared (truthful with the 'Applying…' message).
    assert set_state.called
    _user_arg, saved = set_state.call_args.args
    assert saved["pending_apply"] is False
    assert saved["implementation"] is None


def test_apply_failure_keeps_pending_state(monkeypatch):
    apply_impl, set_state = asyncio.run(_drive_apply(monkeypatch, success=False))
    assert apply_impl.call_args.kwargs.get("dry_run") is False
    # A failed apply must NOT clear the pending implementation.
    assert not set_state.called
