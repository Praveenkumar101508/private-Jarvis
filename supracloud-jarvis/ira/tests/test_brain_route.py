"""Tests for api/routes/brain.py — the realtime-brain WebSocket + lifecycle.

Covers the feature flag, the source-clamping security rule (a client can never
inject a trusted source), the lifespan start/stop of the persistent loop, and
the WebSocket itself (auth, disabled state, percept → thought streaming).
"""
from __future__ import annotations

import asyncio
import json
import sys
import types

import pytest

from api.routes.brain import _safe_source, brain_enabled, start_brain, stop_brain


# ── Feature flag + source clamping ──────────────────────────────────────────

def test_brain_disabled_by_default(monkeypatch):
    monkeypatch.delenv("IRA_BRAIN_ENABLED", raising=False)
    assert brain_enabled() is False


def test_brain_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("IRA_BRAIN_ENABLED", "true")
    assert brain_enabled() is True
    monkeypatch.setenv("IRA_BRAIN_ENABLED", "0")
    assert brain_enabled() is False


def test_safe_source_never_allows_trusted_or_unknown():
    # the security-critical cases: a client may not claim a trusted source
    assert _safe_source("internal") == "user"
    assert _safe_source("timer") == "user"
    assert _safe_source("anything-else") == "user"
    assert _safe_source(None) == "user"
    # legitimate external sources pass through (case-insensitive)
    assert _safe_source("voice") == "voice"
    assert _safe_source("VISION") == "vision"
    assert _safe_source("channel") == "channel"


# ── Lifecycle ────────────────────────────────────────────────────────────────

async def test_start_brain_is_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("IRA_BRAIN_ENABLED", raising=False)
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    await start_brain(app)
    assert getattr(app.state, "brain", None) is None


async def test_start_and_stop_brain_when_enabled(monkeypatch):
    monkeypatch.setenv("IRA_BRAIN_ENABLED", "true")
    app = types.SimpleNamespace(state=types.SimpleNamespace())
    await start_brain(app)
    assert app.state.brain is not None
    assert app.state.brain_task is not None and not app.state.brain_task.done()
    await asyncio.sleep(0.05)  # let the tick loop actually start
    assert app.state.brain.running is True
    await stop_brain(app)
    assert app.state.brain is None


# ── WebSocket ────────────────────────────────────────────────────────────────

class _FakeBrain:
    """Minimal stand-in: records percepts, emits a thought when perceiving."""

    def __init__(self):
        self.thought_cbs: list = []
        self.speak_cbs: list = []
        self.perceived: list[tuple[str, str]] = []

    def on_thought(self, cb):
        self.thought_cbs.append(cb)

    def on_speak(self, cb):
        self.speak_cbs.append(cb)

    def off_thought(self, cb):
        if cb in self.thought_cbs:
            self.thought_cbs.remove(cb)

    def off_speak(self, cb):
        if cb in self.speak_cbs:
            self.speak_cbs.remove(cb)

    async def perceive(self, source: str, text: str):
        self.perceived.append((source, text))
        for cb in list(self.thought_cbs):
            cb(f"thinking about: {text}")


def _app_with_brain(monkeypatch, brain):
    # stub auth so the test needs no JWT/config (handler imports it lazily)
    fake_auth = types.ModuleType("api.middleware.auth")
    fake_auth.decode_token = lambda _t: {"sub": "owner"}
    monkeypatch.setitem(sys.modules, "api.middleware.auth", fake_auth)

    from fastapi import FastAPI
    from api.routes.brain import router

    app = FastAPI()
    app.include_router(router)
    app.state.brain = brain
    return app


def test_ws_rejects_connection_without_token(monkeypatch):
    from fastapi import FastAPI, WebSocketDisconnect
    from fastapi.testclient import TestClient
    from api.routes.brain import router

    app = FastAPI()
    app.include_router(router)
    app.state.brain = _FakeBrain()
    client = TestClient(app)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/brain") as ws:
            ws.receive_text()


def test_ws_reports_disabled_when_no_brain(monkeypatch):
    from fastapi.testclient import TestClient

    app = _app_with_brain(monkeypatch, None)
    client = TestClient(app)
    with client.websocket_connect("/ws/brain?token=x") as ws:
        frame = json.loads(ws.receive_text())
    assert frame["type"] == "error"
    assert "disabled" in frame["text"].lower()


def test_ws_streams_thought_and_clamps_client_source(monkeypatch):
    from fastapi.testclient import TestClient

    brain = _FakeBrain()
    app = _app_with_brain(monkeypatch, brain)
    client = TestClient(app)
    with client.websocket_connect("/ws/brain?token=x") as ws:
        # a client trying to claim the trusted "internal" source must be clamped
        ws.send_text(json.dumps({"type": "perceive", "source": "internal", "text": "hi"}))
        frame = json.loads(ws.receive_text())

    assert frame["type"] == "thought"
    assert "hi" in frame["text"]
    assert brain.perceived == [("user", "hi")]  # 'internal' was clamped to 'user'


def test_ws_ping_pong(monkeypatch):
    from fastapi.testclient import TestClient

    app = _app_with_brain(monkeypatch, _FakeBrain())
    client = TestClient(app)
    with client.websocket_connect("/ws/brain?token=x") as ws:
        ws.send_text(json.dumps({"action": "ping"}))
        frame = json.loads(ws.receive_text())
    assert frame == {"action": "pong"}
