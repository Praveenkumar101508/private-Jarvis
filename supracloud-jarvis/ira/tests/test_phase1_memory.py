"""Phase-1 memory integration test — IRA-owned thread continuity on the Cortex path.

Cortex 0.15.2's `cortex -z` one-shots can't resume a per-conversation session, so the
chat Cortex path (_cortex_route) owns thread memory: it loads recent turns from
Postgres, injects them as context to the skill, and persists each turn. This simulates
a 3-turn conversation and asserts that by turn 3 the earlier fact ("4pm") is fed into
the skill context, and that every turn is persisted. run_skill + the store are mocked,
so no Cortex/Ollama/DB is needed.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import sys
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


def test_three_turns_ira_owned_memory(monkeypatch):
    store: list[dict] = []  # stands in for the Postgres conversation history

    async def fake_recent(conv_id, limit=10):
        return list(store)

    async def fake_save(conv_id, role, content, **kw):
        store.append({"role": role, "content": content})

    captured: dict = {}

    def fake_run_skill(skill, message, *, context_blocks=None, **kwargs):
        captured["blocks"] = context_blocks
        return f"reply to: {message}"

    monkeypatch.setattr(chatmod, "_USE_CORTEX", True)
    monkeypatch.setattr(chatmod, "get_settings", lambda: _Cfg())
    monkeypatch.setattr(chatmod, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(chatmod, "cache_set", AsyncMock())
    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv1"))
    monkeypatch.setattr(chatmod, "get_recent_messages", fake_recent)
    monkeypatch.setattr("memory.store.save_message", fake_save)
    monkeypatch.setattr("skills._common.run_skill", fake_run_skill)
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "conversational", "use_deep_model": False}))

    for turn in ("My demo is at 4pm.", "Thanks.", "When is my demo?"):
        resp = asyncio.run(chat(ChatRequest(message=turn, session_id="s1"), _user="owner"))
        assert resp.model_used == "cortex"

    # By turn 3, the prior turns (incl. the 4pm fact) were fed into the skill context.
    blob = "\n".join(captured["blocks"] or [])
    assert "4pm" in blob, f"recent history not injected: {captured['blocks']!r}"

    # Every turn was persisted (3 user + 3 assistant).
    assert sum(1 for m in store if m["role"] == "user") == 3
    assert sum(1 for m in store if m["role"] == "assistant") == 3
