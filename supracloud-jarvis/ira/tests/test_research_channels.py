"""Prompt 3B.1 — the sovereign web-research channel layer.

All backends are mocked: no SearXNG/Crawl4AI/network/yt-dlp/feedparser needed.
Covers doctor() structure, URL routing, dispatch, and per-channel fail-soft +
formatting.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
import importlib
from unittest.mock import AsyncMock

import channels
import channels.web as web_mod
import channels.github as github_mod
from channels.base import ChannelStatus

# `channels.search` the attribute is the dispatch function (it shadows the submodule),
# so grab the actual submodule via sys.modules to patch its internals.
search_mod = importlib.import_module("channels.search")


# ── fake httpx client ─────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, status=200, json_data=None, text=""):
        self.status_code = status
        self._json = json_data
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, resp):
        self._resp = resp

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **k):
        return self._resp

    async def post(self, *a, **k):
        return self._resp


# ── doctor + routing + dispatch ───────────────────────────────────────────────

def test_doctor_reports_all_channels(monkeypatch):
    for name in ("search", "web", "youtube", "github", "rss"):
        monkeypatch.setattr(channels.get_channel(name), "check",
                            AsyncMock(return_value=ChannelStatus(name, True, "ok")))
    rep = asyncio.run(channels.doctor())
    assert set(rep) == {"search", "web", "youtube", "github", "rss"}
    for info in rep.values():
        assert info["ok"] is True
        assert "search" in info and "read" in info


def test_channel_for_url_routing():
    assert channels.channel_for_url("https://www.youtube.com/watch?v=x").name == "youtube"
    assert channels.channel_for_url("https://youtu.be/x").name == "youtube"
    assert channels.channel_for_url("https://github.com/a/b").name == "github"
    assert channels.channel_for_url("https://example.com/page").name == "web"


def test_read_dispatch_autoroutes_to_youtube(monkeypatch):
    yt = channels.get_channel("youtube")
    monkeypatch.setattr(yt, "read", AsyncMock(return_value="YT-DATA"))
    out = asyncio.run(channels.read("https://youtu.be/abc"))
    assert out == "YT-DATA"


# ── per-channel fail-soft + formatting ─────────────────────────────────────────

def test_search_failsoft_when_searxng_unconfigured(monkeypatch):
    monkeypatch.setattr(search_mod, "get_settings", lambda: type("C", (), {"searxng_url": ""})())
    out = asyncio.run(search_mod.SearchChannel().search("x"))
    assert "unavailable" in out.lower()


def test_search_formats_results(monkeypatch):
    monkeypatch.setattr(search_mod, "get_settings",
                        lambda: type("C", (), {"searxng_url": "http://localhost:8888"})())
    resp = _FakeResp(200, {"results": [{"title": "Py", "url": "http://py", "content": "lang"}]})
    monkeypatch.setattr(search_mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))
    out = asyncio.run(search_mod.SearchChannel().search("python"))
    assert "Py" in out and "http://py" in out


def test_web_failsoft_when_crawl4ai_unconfigured(monkeypatch):
    monkeypatch.setattr(web_mod, "get_settings", lambda: type("C", (), {"crawl4ai_url": ""})())
    out = asyncio.run(web_mod.WebChannel().read("https://x.com"))
    assert "unavailable" in out.lower()


def test_github_read_rejects_non_repo_url():
    out = asyncio.run(github_mod.GitHubChannel().read("https://example.com/notarepo"))
    assert "recognizable" in out.lower()


def test_github_search_formats(monkeypatch):
    resp = _FakeResp(200, {"items": [
        {"full_name": "psf/requests", "stargazers_count": 50000,
         "html_url": "https://github.com/psf/requests", "description": "HTTP for humans"}]})
    monkeypatch.setattr(github_mod.httpx, "AsyncClient", lambda *a, **k: _FakeClient(resp))
    out = asyncio.run(github_mod.GitHubChannel().search("requests"))
    assert "psf/requests" in out
