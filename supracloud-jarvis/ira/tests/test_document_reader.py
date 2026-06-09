"""Prompt 3.2 — the document reader extracts text and feeds it to the brain.

Tests the extraction core (txt/markdown, fail-soft on unsupported/binary) and the
upload handler end-to-end with a small sample doc (LLM stream mocked).
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import io
import json
import sys
from unittest.mock import AsyncMock

_st = sys.modules.get("sentence_transformers")
if _st is not None and not hasattr(_st, "SentenceTransformer"):
    _st.SentenceTransformer = object

from api.routes.chat import _extract_document_text


def test_extract_plain_text():
    out = _extract_document_text(b"hello world", "notes.txt", "text/plain")
    assert "hello world" in out


def test_extract_markdown():
    out = _extract_document_text(b"# Title\n\nSome **markdown** body.", "doc.md", "text/markdown")
    assert "Title" in out and "markdown" in out


def test_extract_unsupported_binary_failsoft():
    # An undecodable/unknown type must return a string, never raise.
    out = _extract_document_text(b"\xff\xfe\x00\x01", "blob.bin", "application/octet-stream")
    assert isinstance(out, str)


def test_extract_pdf_failsoft():
    # Whether or not pypdf is installed, a bad PDF returns a string (no exception).
    out = _extract_document_text(b"%PDF-1.4 not-a-real-pdf", "x.pdf", "application/pdf")
    assert isinstance(out, str)


def test_document_upload_feeds_extracted_text_to_brain(monkeypatch):
    import api.routes.chat as chatmod
    from api.routes.chat import chat_document_upload
    from starlette.datastructures import UploadFile, Headers

    monkeypatch.setattr(chatmod, "ensure_conversation", AsyncMock(return_value="conv1"))
    monkeypatch.setattr("memory.store.save_message", AsyncMock())

    captured = {}

    async def _fake_stream(messages, **kwargs):
        captured["messages"] = messages
        for t in ["The ", "answer."]:
            yield t

    monkeypatch.setattr(chatmod, "stream_tokens", _fake_stream)

    upload = UploadFile(
        filename="notes.txt",
        file=io.BytesIO(b"The capital of France is Paris."),
        headers=Headers({"content-type": "text/plain"}),
    )

    async def _run():
        resp = await chat_document_upload(
            message="What is the capital of France?", session_id="s1", file=upload, _user="owner",
        )
        async for _ in resp.body_iterator:
            pass

    asyncio.run(_run())
    blob = json.dumps(captured["messages"])
    assert "Paris" in blob          # the extracted document text reached the prompt
