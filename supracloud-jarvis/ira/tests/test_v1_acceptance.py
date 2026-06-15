"""Prompt 5.4 — v1 acceptance test (the Definition of Done).

Each test below is one DoD item; run with `-v` and the test names form a pass/fail
checklist. External services (gateway, DB, SMTP, channels, LLM) are mocked, so the
suite proves the pillars work together WITHOUT any non-local network call.

Definition of Done:
  1. owner-gated access works
  2. a 3-turn chat keeps a stable thread + owner memory scope (remembers turn 1)
  3. >=3 real actions succeed (create task, draft+confirm+send email, calendar)
  4. image + document understanding return answers
  5. a public web search/read returns results via the LOCAL backends only
  6. each pillar reports healthy
  7. no non-local network calls are required (sovereignty guards clean for local cfg)

MANUAL (Shadow-only, not automatable here): live voice round-trip (mic -> STT ->
brain -> TTS -> speaker), biometric owner recognition, and the real SearXNG/Crawl4AI
+ Ollama VL model runs. See RELEASE.md for the manual demo script.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

_st = sys.modules.get("sentence_transformers")
if _st is not None and not hasattr(_st, "SentenceTransformer"):
    _st.SentenceTransformer = object


class _Owner:
    ira_admin_username = "owner"
    calcom_api_key = "cal-key"
    smtp_host = "smtp.example.com"
    smtp_port = 587
    smtp_user = "u@example.com"
    smtp_password = "pw"


def _run(coro):
    return asyncio.run(coro)


# ── DoD 1: owner-gated access ─────────────────────────────────────────────────

def test_dod_1_owner_gated_access(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Owner())
    from api.routes.calendar import create_event, CreateEventRequest
    body = CreateEventRequest(event_type_id=1, start="2026-06-01T10:00:00Z", name="N", email="e@x.com")
    with pytest.raises(HTTPException) as ei:
        _run(create_event(body, _user="not-the-owner"))
    assert ei.value.status_code == 403


# ── DoD 2: 3-turn chat keeps thread memory (IRA-owned on the Cortex path) ─────

def test_dod_2_three_turn_memory_continuity(monkeypatch):
    import api.routes.chat as chatmod
    from api.routes.chat import ChatRequest, chat

    store: list[dict] = []  # the Postgres conversation history

    async def fake_recent(conv_id, limit=10):
        return list(store)

    async def fake_save(conv_id, role, content, **kw):
        store.append({"role": role, "content": content})

    captured: dict = {}

    def fake_run_skill(skill, message, *, context_blocks=None, **kwargs):
        captured["blocks"] = context_blocks
        return f"reply to: {message}"

    monkeypatch.setattr(chatmod, "_USE_CORTEX", True)
    monkeypatch.setattr(chatmod, "get_settings", lambda: _Owner())
    monkeypatch.setattr(chatmod, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(chatmod, "cache_set", AsyncMock())
    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv-stable"))
    monkeypatch.setattr(chatmod, "get_recent_messages", fake_recent)
    monkeypatch.setattr("memory.store.save_message", fake_save)
    monkeypatch.setattr("skills._common.run_skill", fake_run_skill)
    monkeypatch.setattr("agents.supervisor.classify",
                        AsyncMock(return_value={"active_agent": "conversational", "use_deep_model": False}))

    for turn in ("My demo is at 4pm.", "Thanks.", "When is my demo?"):
        resp = _run(chat(ChatRequest(message=turn, session_id="s1"), _user="owner"))
        assert resp.model_used == "cortex"

    # Turn 3 fed the earlier fact into the skill context, and every turn was persisted.
    assert "4pm" in "\n".join(captured["blocks"] or [])
    assert sum(1 for m in store if m["role"] == "user") == 3


# ── DoD 3: >=3 real actions succeed ───────────────────────────────────────────

class _FakeConn:
    def __init__(self, row): self._row = row
    async def execute(self, *a, **k): return "INSERT 0 1"
    async def fetchrow(self, *a, **k): return self._row


class _FakeAcquire:
    def __init__(self, row): self._row = row
    async def __aenter__(self): return _FakeConn(self._row)
    async def __aexit__(self, *a): return False


def test_dod_3_actions_task_email_calendar(monkeypatch):
    # (a) create a task — real create_task code path, DB mocked.
    import tasks.manager as taskmod
    row = {"id": "t1", "title": "Ship v1", "status": "pending"}
    monkeypatch.setattr(taskmod, "acquire", lambda: _FakeAcquire(row))
    task = _run(taskmod.create_task("Ship v1"))
    assert task["title"] == "Ship v1"

    # (b) email with approval — draft then confirm -> sent (SMTP mocked).
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Owner())
    monkeypatch.setattr("utils.email_send.get_settings", lambda: _Owner())
    sent = []
    monkeypatch.setattr("utils.email_send._send_sync", lambda to, s, b, c: sent.append((to, s)))
    from api.routes.actions import send_email_action, EmailRequest
    draft = _run(send_email_action(EmailRequest(to="a@b.com", subject="hi", body="x"), _user="owner"))
    assert draft["status"] == "confirmation_required" and not sent
    res = _run(send_email_action(
        EmailRequest(to="a@b.com", subject="hi", body="x", confirm_token=draft["token"]), _user="owner"))
    assert res["status"] == "sent" and sent == [("a@b.com", "hi")]

    # (c) calendar create with approval (Cal.com mocked).
    import api.routes.calendar as calmod
    monkeypatch.setattr("actions.get_settings", lambda: _Owner())
    monkeypatch.setattr(calmod, "create_calcom_event", AsyncMock(return_value={"id": "evt1"}))
    from api.routes.calendar import create_event, CreateEventRequest
    cbody = dict(event_type_id=1, start="2026-06-01T10:00:00Z", name="N", email="e@x.com")
    cdraft = _run(create_event(CreateEventRequest(**cbody), _user="owner"))
    cres = _run(create_event(CreateEventRequest(confirm_token=cdraft["token"], **cbody), _user="owner"))
    assert cres == {"id": "evt1"}


# ── DoD 4: image + document understanding ─────────────────────────────────────

def test_dod_4_image_and_document(monkeypatch):
    import utils.llm as llm
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="a red bicycle"))])))))
    monkeypatch.setattr(llm, "_vision_client_and_model", lambda: (client, "qwen2.5vl"))
    answer = _run(llm.vision_complete(prompt="what is in the image?", image_b64="x"))
    assert "bicycle" in answer

    from api.routes.chat import _extract_document_text
    text = _extract_document_text(b"The capital of France is Paris.", "n.txt", "text/plain")
    assert "Paris" in text


# ── DoD 5: public web search via LOCAL backends ───────────────────────────────

def test_dod_5_local_web_research(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Owner())
    import api.routes.research as rmod
    monkeypatch.setattr(rmod, "ensure_conversation", AsyncMock(return_value="c1"))
    monkeypatch.setattr("channels.search", AsyncMock(return_value="LOCAL-SEARXNG-RESULT"))

    captured = {}

    async def fake_stream(messages, **kw):
        captured["messages"] = messages
        for t in ["here ", "you go"]:
            yield t

    monkeypatch.setattr(rmod, "stream_tokens", fake_stream)
    from api.routes.research import research, ResearchRequest

    async def go():
        resp = await research(ResearchRequest(message="search the web for python"), _user="owner")
        out = []
        async for ev in resp.body_iterator:
            out.append(ev.decode() if isinstance(ev, (bytes, bytearray)) else str(ev))
        return "".join(out)

    blob = _run(go())
    assert "LOCAL-SEARXNG-RESULT" in json.dumps(captured["messages"])
    assert "here " in blob


# ── DoD 6: each pillar reports healthy ────────────────────────────────────────

def test_dod_6_pillars_healthy(monkeypatch):
    import api.routes.health as hmod
    from api.routes.health import health_detail, ServiceStatus

    class _Cfg(_Owner):
        ira_version = "1.0.0"
        ollama_base_url = "http://localhost:11434/v1"
        embedding_model = "bge"
        ollama_vision_model = "qwen2.5vl"
        livekit_api_key = "lk"

    monkeypatch.setattr(hmod, "get_settings", lambda: _Cfg())
    for fn in ("_check_postgres", "_check_redis", "_check_ollama", "_check_cortex"):
        monkeypatch.setattr(hmod, fn, AsyncMock(return_value=ServiceStatus(status="ok", latency_ms=1)))
    monkeypatch.setattr("channels.doctor", AsyncMock(return_value={"search": {"ok": True}}))
    out = _run(health_detail())
    assert out["status"] == "ok"
    assert set(out["pillars"]) == {"brain", "memory", "vision", "voice", "web_research", "actions"}


# ── DoD 7: no non-local network calls required (sovereignty) ──────────────────

def test_dod_7_sovereignty_local_only_clean():
    from config import cortex_local_only_warning, research_backends_warning
    # Default local config raises no leak warning...
    assert cortex_local_only_warning(True, "http://127.0.0.1:8642/v1") is None
    assert research_backends_warning("http://localhost:8888", "http://localhost:11235") is None
    # ...and a non-local endpoint IS flagged (the guard actually fires).
    assert cortex_local_only_warning(True, "https://portal.nousresearch.com/v1") is not None
    assert research_backends_warning("https://searx.be", "") is not None


# ── voice: Shadow-only, manual ────────────────────────────────────────────────

@pytest.mark.skip(reason="MANUAL (Shadow): live voice loop + biometric recognition — see RELEASE.md")
def test_dod_voice_manual_on_shadow():
    pass


if __name__ == "__main__":
    print("=" * 70)
    print("IRA v1 — Definition of Done acceptance checklist")
    print("=" * 70)
    raise SystemExit(pytest.main([__file__, "-v"]))
