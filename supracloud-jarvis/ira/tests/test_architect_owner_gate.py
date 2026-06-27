"""Phase 2 — the architect self-modification path is owner-only.

is_architect_trigger / is_implement_trigger / is_apply_trigger can generate and
git-apply code against IRA's own source. A non-owner must never reach
stream_architect_proposal / stream_auto_implement / apply_implementation — they
get a polite security_gate refusal instead. The owner path is unaffected.

dev_mode is True here so the restricted-domain gate is skipped; any refusal must
therefore come from the new architect owner-gate, not the older keyword gate.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

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


async def _drain(resp) -> str:
    chunks = []
    async for ev in resp.body_iterator:
        chunks.append(ev.decode() if isinstance(ev, (bytes, bytearray)) else str(ev))
    return "".join(chunks)


def _common_mocks(monkeypatch, *, architect=False, implement=False, apply=False):
    monkeypatch.setattr(chatmod, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv1"))
    monkeypatch.setattr(chatmod, "retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr(chatmod, "_USE_CORTEX", False)
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "conversational", "use_deep_model": False}))
    monkeypatch.setattr("agents.architect_agent.is_architect_trigger", lambda q: architect)
    monkeypatch.setattr("agents.architect_agent.is_implement_trigger", lambda q: implement)
    monkeypatch.setattr("agents.architect_agent.is_apply_trigger", lambda q: apply)


def test_nonowner_implement_is_refused(monkeypatch):
    _common_mocks(monkeypatch, implement=True)
    impl = MagicMock()           # must never be invoked for a non-owner
    monkeypatch.setattr("agents.architect_agent.stream_auto_implement", impl)

    async def run():
        resp = await chat_stream(
            ChatRequest(message="architect implement dark mode", session_id="s1"),
            _user="intruder",
        )
        return await _drain(resp)

    blob = asyncio.run(run())
    assert '"agent": "security_gate"' in blob
    impl.assert_not_called()


def test_nonowner_apply_is_refused(monkeypatch):
    _common_mocks(monkeypatch, apply=True)
    apply_impl = AsyncMock()     # must never be invoked for a non-owner
    monkeypatch.setattr("utils.auto_implement.apply_implementation", apply_impl)

    async def run():
        resp = await chat_stream(
            ChatRequest(message="architect apply", session_id="s1"),
            _user="intruder",
        )
        return await _drain(resp)

    blob = asyncio.run(run())
    assert '"agent": "security_gate"' in blob
    apply_impl.assert_not_called()


def test_owner_apply_passes_the_gate(monkeypatch):
    """The owner reaches the real apply path — gate does not block the owner."""
    _common_mocks(monkeypatch, apply=True)
    monkeypatch.setattr("api.routes.architect._get_state",
                        AsyncMock(return_value={"implementation": "PATCH-DIFF", "pending_apply": True}))
    monkeypatch.setattr("api.routes.architect._set_state", AsyncMock())
    apply_impl = AsyncMock(return_value=SimpleNamespace(
        success=True, message="✅ applied", error=None,
    ))
    monkeypatch.setattr("utils.auto_implement.apply_implementation", apply_impl)

    async def run():
        resp = await chat_stream(
            ChatRequest(message="architect apply", session_id="s1"),
            _user="owner",
        )
        return await _drain(resp)

    blob = asyncio.run(run())
    assert apply_impl.called, "owner must reach apply_implementation (gate must not block the owner)"
    assert '"agent": "security_gate"' not in blob
