"""Tests for the execute-ASAP mobile task queue (worker/mobile_tasks.py).

Pure unit tests: owner-gating, background run + status lifecycle, approval-gating
for side-effecting types, completion push, and fail-soft. The completion push is
neutralized so tests never touch Redis/Expo.
"""
from __future__ import annotations

import pytest

from worker import mobile_tasks as mt


@pytest.fixture(autouse=True)
def _quiet_push(monkeypatch):
    async def _noop(*a, **k):
        return 0
    monkeypatch.setattr("worker.push_mobile.send_push", _noop)


async def test_non_side_effecting_task_runs_to_done():
    seen = {}

    async def runner(params):
        seen["params"] = params
        return {"echo": params.get("x")}

    mt.register_runner("t_echo", runner, side_effecting=False)
    out = await mt.submit_task("owner", "t_echo", {"x": 1}, is_owner=True)
    assert out["status"] == "queued"
    tid = out["task"]["id"]
    await mt.wait_for(tid)
    rec = mt.get_task(tid)
    assert rec["status"] == "done" and rec["result"] == {"echo": 1}
    assert seen["params"] == {"x": 1}


async def test_non_owner_is_forbidden():
    out = await mt.submit_task("intruder", "email", {}, is_owner=False)
    assert out["status"] == "forbidden"


async def test_unknown_task_type():
    out = await mt.submit_task("owner", "nope", {}, is_owner=True)
    assert out["status"] == "unknown_task"


async def test_side_effecting_requires_confirmation_then_runs():
    ran = {}

    async def runner(params):
        ran["ok"] = True
        return "done"

    mt.register_runner("t_send", runner, side_effecting=True, preview=lambda p: f"send to {p.get('to')}")

    draft = await mt.submit_task("owner", "t_send", {"to": "x@y.com"}, is_owner=True)
    assert draft["status"] == "confirmation_required"
    assert "send to x@y.com" in draft["preview"]
    assert draft["token"]
    assert ran == {}                       # nothing ran without confirmation

    out = await mt.submit_task("owner", "t_send", {}, confirm_token=draft["token"], is_owner=True)
    assert out["status"] == "queued"
    await mt.wait_for(out["task"]["id"])
    assert ran.get("ok") is True
    assert mt.get_task(out["task"]["id"])["status"] == "done"


async def test_failed_task_is_marked_failed():
    async def boom(params):
        raise RuntimeError("kaboom")

    mt.register_runner("t_boom", boom, side_effecting=False)
    out = await mt.submit_task("owner", "t_boom", {}, is_owner=True)
    await mt.wait_for(out["task"]["id"])
    rec = mt.get_task(out["task"]["id"])
    assert rec["status"] == "failed" and "kaboom" in rec["error"]


async def test_completion_push_fires(monkeypatch):
    sent = {}

    async def fake_send(title, body, *, priority="info", data=None):
        sent["data"] = data
        return 1

    monkeypatch.setattr("worker.push_mobile.send_push", fake_send)

    async def runner(params):
        return "ok"

    mt.register_runner("t_push", runner, side_effecting=False)
    out = await mt.submit_task("owner", "t_push", {}, is_owner=True)
    await mt.wait_for(out["task"]["id"])
    assert sent["data"]["task_id"] == out["task"]["id"]


async def test_builtin_email_task_is_gated():
    out = await mt.submit_task("owner", "email",
                               {"to": "a@b.com", "subject": "hi", "body": "yo"}, is_owner=True)
    assert out["status"] == "confirmation_required"
    assert "Send email to a@b.com" in out["preview"]


def test_get_unknown_task_is_none():
    assert mt.get_task("does-not-exist") is None
