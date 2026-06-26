"""Prompt 3B.3 — public-only guardrail + owner-gate + local-backend warning.

The value rule: read public sources only, never carry private/internal content
outward, and only the verified owner may trigger research.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

_st = sys.modules.get("sentence_transformers")
if _st is not None and not hasattr(_st, "SentenceTransformer"):
    _st.SentenceTransformer = object

from utils.net_safety import check_url, is_safe_query, guard_outbound
from config import research_backends_warning
import api.routes.research as rmod
from api.routes.research import research, ResearchRequest


class _Cfg:
    ira_admin_username = "owner"


# ── public-only guard ─────────────────────────────────────────────────────────

def test_public_url_allowed():
    assert check_url("https://example.com/page", resolve_fn=lambda h: ["93.184.216.34"])[0]


def test_private_and_internal_urls_blocked():
    for u in (
        "http://localhost/x", "http://127.0.0.1/x", "http://192.168.1.10/x",
        "http://10.0.0.5/", "http://169.254.1.1/", "file:///etc/passwd",
        "http://server.local/x", "ftp://example.com/x",
    ):
        ok, _reason = check_url(u, resolve_fn=lambda h: ["93.184.216.34"])
        assert not ok, f"{u} should be blocked"


def test_dns_rebinding_to_private_address_blocked():
    # A public-looking domain that resolves to an internal/metadata address
    # must be blocked even though the hostname string itself looks public.
    for private_ip in ("127.0.0.1", "10.0.0.5", "169.254.169.254", "192.168.1.1"):
        ok, reason = check_url(
            "http://rebind.example.com/", resolve_fn=lambda h, ip=private_ip: [ip]
        )
        assert not ok, f"resolution to {private_ip} should be blocked"
        assert "resolves to a private address" in reason


def test_alternate_ip_literal_encodings_blocked():
    for u in (
        "http://2130706433/",          # decimal encoding of 127.0.0.1
        "http://0x7f000001/",          # hex encoding of 127.0.0.1
        "http://017700000001/",        # octal encoding of 127.0.0.1
        "http://[::ffff:127.0.0.1]/",  # IPv4-mapped IPv6
    ):
        ok, _reason = check_url(u, resolve_fn=lambda h: ["93.184.216.34"])
        assert not ok, f"{u} should be blocked"


def test_query_blocks_secrets_and_local_paths():
    assert not is_safe_query("here is api_key=ABCDEF123456")[0]
    assert not is_safe_query("password=hunter2")[0]
    assert not is_safe_query("read /etc/passwd please")[0]
    assert not is_safe_query("-----BEGIN PRIVATE KEY-----")[0]
    assert is_safe_query("best python web framework 2026")[0]


def test_guard_outbound_combines():
    assert guard_outbound(url="http://localhost/x") is not None
    assert guard_outbound(query="password=hunter2") is not None
    assert guard_outbound(url="https://example.com") is None
    assert guard_outbound(query="weather in London today") is None


# ── local-backend sovereignty warning ─────────────────────────────────────────

def test_research_backends_warning():
    assert research_backends_warning("http://localhost:8888", "http://127.0.0.1:11235") is None
    assert research_backends_warning("http://10.0.0.5:8888", "") is None   # private LAN = self-hosted
    w = research_backends_warning("https://searx.be", "")
    assert w and "SEARXNG_URL" in w


# ── owner-gate + route enforcement ────────────────────────────────────────────

def test_research_is_owner_gated(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Cfg())
    with pytest.raises(HTTPException) as ei:
        asyncio.run(research(ResearchRequest(message="search the web for x"), _user="randomguy"))
    assert ei.value.status_code == 403


def test_research_route_blocks_private_url(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Cfg())
    monkeypatch.setattr(rmod, "ensure_conversation", AsyncMock(return_value="c1"))
    read_mock = AsyncMock(return_value="SHOULD NOT FETCH")
    monkeypatch.setattr("channels.read", read_mock)

    async def run():
        resp = await research(
            ResearchRequest(message="read http://localhost:8000/admin"), _user="owner")
        chunks = []
        async for ev in resp.body_iterator:
            chunks.append(ev.decode() if isinstance(ev, (bytes, bytearray)) else str(ev))
        return "".join(chunks)

    blob = asyncio.run(run())
    assert "Blocked" in blob
    read_mock.assert_not_awaited()    # the private target was never fetched
