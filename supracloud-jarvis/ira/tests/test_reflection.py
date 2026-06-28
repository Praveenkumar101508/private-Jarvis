"""Feature 4 — Weekly Self-Reflection tests.

Covers: flag-OFF no-op + never-schedules, a pass over seeded fixtures produces a
non-empty summary routed through the model layer and spoken, the no-activity case
returns None cleanly, per-source fail-closed gathering, and weekly scheduling.
git + DB + model are mocked.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD",
           "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import worker.reflection as rf

NOW = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)


def _enable(monkeypatch):
    monkeypatch.setenv("IRA_REFLECTION", "true")


class _FakeConn:
    def __init__(self, rows):
        self._rows = list(rows)

    async def fetch(self, sql, *args):
        return self._rows.pop(0) if self._rows else []


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


# ── flag gate ─────────────────────────────────────────────────────────────────

def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("IRA_REFLECTION", raising=False)
    assert rf.reflection_enabled() is False


@pytest.mark.asyncio
async def test_flag_off_is_noop(monkeypatch):
    monkeypatch.delenv("IRA_REFLECTION", raising=False)
    spoken = []

    async def boom(_m):
        raise AssertionError("summarizer called while flag OFF")

    out = await rf.run_weekly_reflection(NOW, summarize=boom, speak=spoken.append)
    assert out is None and spoken == []


def test_flag_off_never_schedules(monkeypatch):
    monkeypatch.delenv("IRA_REFLECTION", raising=False)

    class _Sched:
        def __init__(self):
            self.jobs = []

        def add_job(self, *a, **k):
            self.jobs.append(k.get("id"))

    sched = _Sched()
    assert rf.register_reflection(sched) is False and sched.jobs == []


def test_flag_on_schedules_weekly(monkeypatch):
    _enable(monkeypatch)

    class _Sched:
        def __init__(self):
            self.jobs = []
            self.kw = []

        def add_job(self, *a, **k):
            self.jobs.append(k.get("id"))
            self.kw.append(k)

    sched = _Sched()
    assert rf.register_reflection(sched) is True
    assert sched.jobs == ["weekly_reflection"]
    assert sched.kw[0]["trigger"] == "cron" and sched.kw[0]["day_of_week"] == "sun"


# ── the pass ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reflection_summarizes_and_speaks(monkeypatch):
    _enable(monkeypatch)
    captured = {}

    async def fake_summarize(messages):
        captured["messages"] = messages
        return "You shipped three commits and closed two tasks. Steady week."

    spoken = []

    async def fake_git(now):
        return "abc123 feat: add life graph\ndef456 fix: edge index"

    async def fake_tasks(now):
        return ["Email supervisor", "Submit form"]

    async def fake_decisions(now):
        return ["Take offer -> accepted (matched)"]

    with patch.object(rf, "gather_git_activity", fake_git), \
         patch.object(rf, "gather_completed_tasks", fake_tasks), \
         patch.object(rf, "gather_decision_outcomes", fake_decisions):
        out = await rf.run_weekly_reflection(NOW, summarize=fake_summarize,
                                             speak=spoken.append)

    assert out and "Steady week" in out
    assert spoken == [out]                                   # spoken through the surface
    # the model got all three already-logged sources in its context
    ctx = captured["messages"][-1]["content"]
    assert "Git commits" in ctx and "Completed tasks" in ctx and "Decision outcomes" in ctx


@pytest.mark.asyncio
async def test_reflection_no_activity_returns_none(monkeypatch):
    _enable(monkeypatch)

    async def empty_git(now):
        return ""

    async def empty_list(now):
        return []

    called = {"summarize": False}

    async def summarize(_m):
        called["summarize"] = True
        return "should not happen"

    with patch.object(rf, "gather_git_activity", empty_git), \
         patch.object(rf, "gather_completed_tasks", empty_list), \
         patch.object(rf, "gather_decision_outcomes", empty_list):
        out = await rf.run_weekly_reflection(NOW, summarize=summarize, speak=lambda _t: None)

    assert out is None and called["summarize"] is False


# ── gatherers fail-closed ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_completed_tasks_db_error_fails_closed(monkeypatch):
    _enable(monkeypatch)
    with patch("worker.reflection.acquire", side_effect=RuntimeError("db down")):
        assert await rf.gather_completed_tasks(NOW) == []


@pytest.mark.asyncio
async def test_completed_tasks_reads_done_within_window(monkeypatch):
    _enable(monkeypatch)
    rows = [{"title": "Submit form", "completed_at": NOW - timedelta(days=2)}]
    conn = _FakeConn([rows])
    with patch("worker.reflection.acquire", return_value=_FakeAcquire(conn)):
        out = await rf.gather_completed_tasks(NOW)
    assert out == ["Submit form"]


@pytest.mark.asyncio
async def test_decision_outcomes_skipped_when_journal_off(monkeypatch):
    _enable(monkeypatch)
    with patch("memory.decision_journal.journal_enabled", return_value=False):
        assert await rf.gather_decision_outcomes(NOW) == []


@pytest.mark.asyncio
async def test_git_activity_handles_missing_repo(monkeypatch):
    _enable(monkeypatch)
    # Point at a non-repo dir; git returns non-zero → empty string, no raise.
    monkeypatch.setenv("IRA_REFLECTION_REPO", "/nonexistent-path-xyz")
    out = await rf.gather_git_activity(NOW)
    assert out == ""
