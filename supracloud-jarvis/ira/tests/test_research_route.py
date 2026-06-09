"""Prompt 3B.2 — the /research route feeds channel text into the brain and streams.

Channels and the LLM stream are mocked. Covers: a search query routes to the search
channel and the clean text reaches the prompt; a message with a URL routes to read;
and the doctor endpoint returns per-channel status.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import json
import sys
from unittest.mock import AsyncMock

_st = sys.modules.get("sentence_transformers")
if _st is not None and not hasattr(_st, "SentenceTransformer"):
    _st.SentenceTransformer = object

import api.routes.research as rmod
from api.routes.research import research, research_doctor, ResearchRequest


async def _drain(resp) -> str:
    chunks = []
    async for ev in resp.body_iterator:
        chunks.append(ev.decode() if isinstance(ev, (bytes, bytearray)) else str(ev))
    return "".join(chunks)


def test_search_feeds_channel_text_to_brain_and_streams(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings",
                        lambda: type("C", (), {"ira_admin_username": "owner"})())
    monkeypatch.setattr(rmod, "ensure_conversation", AsyncMock(return_value="c1"))
    monkeypatch.setattr("channels.search", AsyncMock(return_value="SEARXNG-RESULT-TEXT"))

    captured = {}

    async def fake_stream(messages, **kwargs):
        captured["messages"] = messages
        for t in ["ans", "wer"]:
            yield t

    monkeypatch.setattr(rmod, "stream_tokens", fake_stream)

    async def run():
        resp = await research(ResearchRequest(message="search the web for python"), _user="owner")
        return await _drain(resp)

    blob = asyncio.run(run())
    assert "SEARXNG-RESULT-TEXT" in json.dumps(captured["messages"])  # channel text fed to brain
    assert "ans" in blob and "wer" in blob                            # streamed answer
    assert '"agent": "research"' in blob


def test_message_with_url_routes_to_read(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings",
                        lambda: type("C", (), {"ira_admin_username": "owner"})())
    monkeypatch.setattr(rmod, "ensure_conversation", AsyncMock(return_value="c1"))
    read_mock = AsyncMock(return_value="PAGE-TEXT")
    monkeypatch.setattr("channels.read", read_mock)

    async def fake_stream(messages, **kwargs):
        for t in ["ok"]:
            yield t

    monkeypatch.setattr(rmod, "stream_tokens", fake_stream)

    async def run():
        resp = await research(ResearchRequest(message="read https://example.com/post"), _user="owner")
        return await _drain(resp)

    asyncio.run(run())
    read_mock.assert_awaited_once()
    assert read_mock.call_args.args[0] == "https://example.com/post"


def test_research_doctor_returns_channel_status(monkeypatch):
    monkeypatch.setattr("channels.doctor", AsyncMock(return_value={"search": {"ok": True}}))
    out = asyncio.run(research_doctor(_user="owner"))
    assert out == {"channels": {"search": {"ok": True}}}
