"""Phase 7.2 — the IRA_USE_CORTEX feature flag routes requests between the legacy
LangGraph engine (run_graph) and the Cortex bridge (router gate -> skills via run_skill).

The bridge is mocked, so no live gateway/model is needed. We assert *which path* runs:
  - flag OFF -> run_graph invoked, the bridge skill is NOT
  - flag ON  -> the bridge skill invoked, run_graph is NOT
  - flag ON + non-owner + restricted domain -> fail-closed refusal, skill never runs

Routing is verified by calling the endpoint functions directly (Depends bypassed) with the
I/O dependencies stubbed. The streaming endpoint (which voice uses over HTTP) shares the
same _cortex_route, so it is exercised too.
"""
import os

# Settings has required fields; set placeholders BEFORE importing the app module so any
# get_settings() at import time succeeds. The tests still mock get_settings per-call.
for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

# conftest.py stubs sentence_transformers as an EMPTY module (for the lightweight test
# env). Importing the full app chain (chat.py -> memory.embeddings) only needs the
# SentenceTransformer *name* at import time; the model loads lazily and is never used
# here (retrieve is mocked). Add a placeholder so the import resolves.
_st = sys.modules.get("sentence_transformers")
if _st is not None and not hasattr(_st, "SentenceTransformer"):
    _st.SentenceTransformer = object

import api.routes.chat as chatmod
from api.routes.chat import ChatRequest, chat, chat_stream


class _Cfg:
    ira_admin_username = "owner"
    ira_voice_service_username = "ira-voice"
    dev_mode = True
    owner_name = "Praveen"


def _stub_io(monkeypatch):
    """Stub the non-routing I/O so we isolate the flag's branch decision."""
    monkeypatch.setattr(chatmod, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(chatmod, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(chatmod, "cache_set", AsyncMock())
    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv1"))
    monkeypatch.setattr(chatmod, "retrieve", AsyncMock(return_value=[]))
    # _cortex_route owns thread memory now: it loads recent turns + persists each turn.
    monkeypatch.setattr(chatmod, "get_recent_messages", AsyncMock(return_value=[]))
    monkeypatch.setattr("memory.store.save_message", AsyncMock())


def test_flag_off_routes_to_legacy_run_graph(monkeypatch):
    _stub_io(monkeypatch)
    monkeypatch.setattr(chatmod, "_USE_CORTEX", False)

    run_graph = AsyncMock(return_value={
        "final_response": "legacy answer", "active_agent": "conversational",
        "model_used": "qwen3-fast", "latency_ms": 1,
    })
    monkeypatch.setattr(chatmod, "run_graph", run_graph)
    run_skill = MagicMock(return_value="cortex answer")
    monkeypatch.setattr("skills._common.run_skill", run_skill)

    resp = asyncio.run(chat(ChatRequest(message="hello there", session_id="s1"), _user="owner"))

    assert run_graph.called, "flag OFF must invoke the legacy run_graph"
    assert not run_skill.called, "flag OFF must NOT invoke the Cortex bridge skill"
    assert resp.response == "legacy answer"


def test_flag_on_routes_to_bridge_skill(monkeypatch):
    _stub_io(monkeypatch)
    monkeypatch.setattr(chatmod, "_USE_CORTEX", True)

    run_graph = AsyncMock(return_value={"final_response": "x", "active_agent": "conversational"})
    monkeypatch.setattr(chatmod, "run_graph", run_graph)
    # classify is reused (read-only) to pick the skill — stub it (deterministic, no model).
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "conversational", "use_deep_model": False}))
    run_skill = MagicMock(return_value="cortex answer")
    monkeypatch.setattr("skills._common.run_skill", run_skill)

    # non-owner + general query -> owner gate allows -> routes to the skill via the bridge
    resp = asyncio.run(chat(ChatRequest(message="hello there", session_id="s1"), _user="randomguy"))

    assert run_skill.called, "flag ON must invoke the Cortex bridge skill"
    assert not run_graph.called, "flag ON must NOT invoke the legacy run_graph"
    assert resp.response == "cortex answer"
    assert resp.model_used == "cortex"


def test_flag_on_streaming_routes_to_bridge(monkeypatch):
    """The streaming endpoint (used by voice over HTTP) also routes via the bridge when ON.
    _cortex_route runs eagerly before the SSE response is returned, so the skill call is
    observable without consuming the stream."""
    _stub_io(monkeypatch)
    monkeypatch.setattr(chatmod, "_USE_CORTEX", True)
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "tutor", "use_deep_model": False}))
    run_skill = MagicMock(return_value="streamed answer")
    monkeypatch.setattr("skills._common.run_skill", run_skill)

    asyncio.run(chat_stream(ChatRequest(message="teach me python", session_id="s2"), _user="randomguy"))

    assert run_skill.called, "flag ON streaming must route through the bridge skill"


def test_flag_on_gate_blocks_non_owner_restricted(monkeypatch):
    """Owner gate stays fail-closed on the new path: non-owner + restricted domain -> refusal,
    the skill is never reached."""
    _stub_io(monkeypatch)
    monkeypatch.setattr(chatmod, "_USE_CORTEX", True)
    run_skill = MagicMock(return_value="should not run")
    monkeypatch.setattr("skills._common.run_skill", run_skill)

    resp = asyncio.run(chat(ChatRequest(message="lockdown the network now", session_id="s1"), _user="randomguy"))

    assert not run_skill.called, "restricted request from a non-owner must not reach the skill"
    assert resp.agent_used == "security_gate"


def test_flag_on_unmapped_classify_falls_back_to_conversational(monkeypatch):
    """If the classifier returns a domain with no matching ira/skills/<name>/ persona
    (e.g. 'expert_mode', 'access_denied'), the ON path must fall back to 'conversational'
    — never raise / 500 on an input the legacy path handled fine."""
    _stub_io(monkeypatch)
    monkeypatch.setattr(chatmod, "_USE_CORTEX", True)
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "expert_mode", "use_deep_model": False}))
    run_skill = MagicMock(return_value="ok")
    monkeypatch.setattr("skills._common.run_skill", run_skill)

    resp = asyncio.run(chat(ChatRequest(message="an ambiguous request", session_id="s9"), _user="randomguy"))

    assert run_skill.called, "ON path must still reach a skill"
    called_skill = run_skill.call_args.args[0]          # run_skill(skill, message, ...)
    assert called_skill == "conversational", f"unmapped domain must fall back to conversational, got {called_skill!r}"
    assert resp.agent_used == "conversational"
