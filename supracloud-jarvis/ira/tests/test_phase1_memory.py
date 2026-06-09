"""Prompt 1.6 — Phase-1 memory integration test.

Simulates a 3-turn conversation through the Hermes path (chat() with IRA_USE_HERMES
on) and asserts the bridge sends, on EVERY turn:
  - X-Hermes-Session-Id == the (stable) conversation id  -> thread continuity
  - X-Hermes-Session-Key == the owner id                 -> stable memory scope

The gateway HTTP call is mocked at the OpenAI-client level (hermes_bridge.OpenAI), so
we assert on the real headers the bridge emits — no live server, no real model.
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
from api.routes.chat import ChatRequest, chat


class _Cfg:
    ira_admin_username = "owner"
    ira_voice_service_username = "ira-voice"
    dev_mode = True
    owner_name = "Praveen"


def test_three_turns_send_stable_session_id_and_owner_memory_key(monkeypatch):
    # Capture every gateway call's kwargs (incl. extra_headers) via a fake OpenAI client.
    calls: list[dict] = []

    def _fake_openai(*_a, **_k):
        def _create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create)))

    monkeypatch.setattr("hermes_bridge.OpenAI", _fake_openai)

    # Route through the Hermes engine, owner user, stable conversation id.
    monkeypatch.setattr(chatmod, "_USE_HERMES", True)
    monkeypatch.setattr(chatmod, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(chatmod, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(chatmod, "cache_set", AsyncMock())
    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv-stable"))
    monkeypatch.setattr(chatmod, "retrieve", AsyncMock(return_value=[]))
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "conversational", "use_deep_model": False}))

    for turn in ("first message", "second message", "third message"):
        resp = asyncio.run(chat(ChatRequest(message=turn, session_id="s1"), _user="owner"))
        assert resp.model_used == "hermes"

    assert len(calls) == 3, f"expected one gateway call per turn, got {len(calls)}"

    session_ids = {c["extra_headers"]["X-Hermes-Session-Id"] for c in calls}
    session_keys = {c["extra_headers"]["X-Hermes-Session-Key"] for c in calls}

    assert session_ids == {"conv-stable"}, f"session id must be stable across turns, got {session_ids}"
    assert session_keys == {"owner"}, f"memory scope must equal the owner id, got {session_keys}"
