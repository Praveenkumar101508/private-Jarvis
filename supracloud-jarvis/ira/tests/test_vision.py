"""Prompts 3.1 & 3.3 — local vision-language model path + /chat/vision wiring.

The VL model call is mocked (no Ollama / no pulled model needed). Covers: fail-soft
when no vision model is configured, fail-soft on a backend error, a successful
completion/stream, and that /chat/vision streams through the helper.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import utils.llm as llm

_st = sys.modules.get("sentence_transformers")
if _st is not None and not hasattr(_st, "SentenceTransformer"):
    _st.SentenceTransformer = object


async def _collect(agen):
    return [t async for t in agen]


def test_vision_complete_failsoft_when_unconfigured(monkeypatch):
    monkeypatch.setattr(llm, "_vision_client_and_model", lambda: (None, None))
    out = asyncio.run(llm.vision_complete(prompt="describe", image_b64="x"))
    assert "unavailable" in out.lower()


def test_vision_complete_success(monkeypatch):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="A red apple"))])))))
    monkeypatch.setattr(llm, "_vision_client_and_model", lambda: (client, "qwen2.5vl"))
    out = asyncio.run(llm.vision_complete(prompt="what is it?", image_b64="x"))
    assert out == "A red apple"


def test_vision_complete_failsoft_on_error(monkeypatch):
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(side_effect=RuntimeError("model not pulled")))))
    monkeypatch.setattr(llm, "_vision_client_and_model", lambda: (client, "qwen2.5vl"))
    out = asyncio.run(llm.vision_complete(prompt="?", image_b64="x"))
    assert out.startswith("Vision unavailable")


def test_stream_vision_failsoft_when_unconfigured(monkeypatch):
    monkeypatch.setattr(llm, "_vision_client_and_model", lambda: (None, None))
    toks = asyncio.run(_collect(llm.stream_vision_tokens(prompt="p", image_b64="x")))
    assert any("unavailable" in t.lower() for t in toks)


def test_stream_vision_success(monkeypatch):
    async def _chunks():
        for c in ["Hel", "lo"]:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=c))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value=_chunks()))))
    monkeypatch.setattr(llm, "_vision_client_and_model", lambda: (client, "m"))
    toks = asyncio.run(_collect(llm.stream_vision_tokens(prompt="p", image_b64="x")))
    assert "".join(toks) == "Hello"


def test_chat_vision_route_streams_via_helper(monkeypatch):
    import api.routes.chat as chatmod
    from api.routes.chat import chat_vision, VisionRequest

    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv1"))
    monkeypatch.setattr("memory.store.save_message", AsyncMock())

    async def _fake_stream(**kwargs):
        for t in ["It ", "is ", "a cat."]:
            yield t
    monkeypatch.setattr("utils.llm.stream_vision_tokens", _fake_stream)

    async def _run():
        resp = await chat_vision(
            VisionRequest(message="what is this?", image_b64="abc", mime_type="image/png"),
            _user="owner",
        )
        chunks = []
        async for ev in resp.body_iterator:
            chunks.append(ev.decode() if isinstance(ev, (bytes, bytearray)) else str(ev))
        return "".join(chunks)

    blob = asyncio.run(_run())
    assert "a cat." in blob
    assert '"agent": "vision"' in blob or "vision" in blob
