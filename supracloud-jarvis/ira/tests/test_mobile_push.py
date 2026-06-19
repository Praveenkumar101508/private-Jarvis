"""Tests for mobile push + device registry (worker/push_mobile.py, api/routes/mobile.py).

Cover the parts that run in CI without Redis/network/Expo: token validation, the
flag, the device registry against a fake Redis, send_push batching + fail-soft, and
the owner-gated registration routes (TestClient + stubbed auth + mocked registry).
"""
from __future__ import annotations

import sys
import types

import pytest

from worker import push_mobile as pm


# ── Token validation + flag ──────────────────────────────────────────────────

def test_is_valid_token():
    assert pm.is_valid_token("ExponentPushToken[abc123_-]")
    assert pm.is_valid_token("ExpoPushToken[XYZ789]")
    assert not pm.is_valid_token("garbage")
    assert not pm.is_valid_token("")
    assert not pm.is_valid_token("ExponentPushToken[bad token]")  # space


def test_mobile_push_disabled_by_default(monkeypatch):
    monkeypatch.delenv("IRA_MOBILE_PUSH_ENABLED", raising=False)
    assert pm.mobile_push_enabled() is False


def test_mobile_push_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("IRA_MOBILE_PUSH_ENABLED", "true")
    assert pm.mobile_push_enabled() is True


# ── Device registry against a fake Redis ─────────────────────────────────────

class _FakeRedis:
    def __init__(self):
        self.store: set[str] = set()

    async def sadd(self, key, value):
        self.store.add(value)

    async def srem(self, key, value):
        self.store.discard(value)

    async def smembers(self, key):
        return {t.encode() for t in self.store}


async def test_register_list_unregister(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(pm, "get_redis", lambda: fake)
    await pm.register_device("ExponentPushToken[aaa]", platform="ios")
    await pm.register_device("ExponentPushToken[bbb]", platform="android")
    assert await pm.list_devices() == ["ExponentPushToken[aaa]", "ExponentPushToken[bbb]"]
    await pm.unregister_device("ExponentPushToken[aaa]")
    assert await pm.list_devices() == ["ExponentPushToken[bbb]"]


# ── send_push: gating, batching, fail-soft ───────────────────────────────────

async def test_send_push_noop_when_disabled(monkeypatch):
    monkeypatch.delenv("IRA_MOBILE_PUSH_ENABLED", raising=False)
    assert await pm.send_push("t", "b") == 0


async def test_send_push_noop_without_devices(monkeypatch):
    monkeypatch.setenv("IRA_MOBILE_PUSH_ENABLED", "true")
    monkeypatch.setattr(pm, "get_redis", lambda: _FakeRedis())  # empty
    assert await pm.send_push("t", "b") == 0


async def test_send_push_delivers_to_devices(monkeypatch):
    monkeypatch.setenv("IRA_MOBILE_PUSH_ENABLED", "true")
    fake = _FakeRedis()
    fake.store = {"ExponentPushToken[aaa]", "ExponentPushToken[bbb]"}
    monkeypatch.setattr(pm, "get_redis", lambda: fake)
    posted = []

    async def fake_post(messages):
        posted.extend(messages)

    monkeypatch.setattr(pm, "_post_expo", fake_post)
    sent = await pm.send_push("Task done", "Your report is ready", priority="warning",
                              data={"id": "x"})
    assert sent == 2
    assert {m["to"] for m in posted} == {"ExponentPushToken[aaa]", "ExponentPushToken[bbb]"}
    assert all(m["priority"] == "high" for m in posted)        # warning → high
    assert all(m["title"] == "Task done" for m in posted)


async def test_send_push_failsoft_on_post_error(monkeypatch):
    monkeypatch.setenv("IRA_MOBILE_PUSH_ENABLED", "true")
    fake = _FakeRedis()
    fake.store = {"ExponentPushToken[aaa]"}
    monkeypatch.setattr(pm, "get_redis", lambda: fake)

    async def boom(messages):
        raise RuntimeError("expo down")

    monkeypatch.setattr(pm, "_post_expo", boom)
    assert await pm.send_push("t", "b") == 0                   # swallowed, no crash


# ── Routes (owner-gated; TestClient + stubbed auth) ──────────────────────────

def _app(monkeypatch):
    fake_auth = types.ModuleType("api.middleware.auth")
    fake_auth.require_auth = lambda: "owner"
    monkeypatch.setitem(sys.modules, "api.middleware.auth", fake_auth)

    from fastapi import FastAPI
    from api.routes.mobile import router

    app = FastAPI()
    app.include_router(router)
    return app


def test_route_register_valid_token(monkeypatch):
    from fastapi.testclient import TestClient

    app = _app(monkeypatch)
    recorded = {}

    async def fake_register(token, platform=None):
        recorded["token"] = token
        recorded["platform"] = platform

    monkeypatch.setattr(pm, "register_device", fake_register)
    client = TestClient(app)
    r = client.post("/mobile/devices",
                    json={"token": "ExponentPushToken[abc123]", "platform": "ios"})
    assert r.status_code == 200 and r.json()["status"] == "registered"
    assert recorded == {"token": "ExponentPushToken[abc123]", "platform": "ios"}


def test_route_register_rejects_bad_token(monkeypatch):
    from fastapi.testclient import TestClient

    app = _app(monkeypatch)
    client = TestClient(app)
    r = client.post("/mobile/devices", json={"token": "not-a-token"})
    assert r.status_code == 422


def test_route_list_devices_returns_count_only(monkeypatch):
    from fastapi.testclient import TestClient

    app = _app(monkeypatch)

    async def fake_list():
        return ["ExponentPushToken[aaa]", "ExponentPushToken[bbb]"]

    monkeypatch.setattr(pm, "list_devices", fake_list)
    client = TestClient(app)
    r = client.get("/mobile/devices")
    assert r.status_code == 200
    assert r.json() == {"count": 2}          # count only — no token leakage
