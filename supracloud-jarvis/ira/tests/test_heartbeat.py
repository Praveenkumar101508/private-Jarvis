"""Feature 3 — Heartbeat tests.

Covers: flag-OFF no-op + never-schedules, a tick with seeded pending items emits
exactly once each, a second tick emits nothing (de-dupe via the ledger), per-signal
fail-closed isolation, and the voice-unavailable fallback path. DB + voice are mocked.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD",
           "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import worker.heartbeat as hb
from worker.heartbeat import SurfacedItem

NOW = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)


def _enable(monkeypatch):
    monkeypatch.setenv("IRA_HEARTBEAT", "true")


# ── A fake ledger so de-dupe is exercised without Postgres ────────────────────

class _LedgerConn:
    """Stands in for the heartbeat_surfaced table; remembers claimed keys."""
    def __init__(self, claimed: set):
        self._claimed = claimed

    async def fetchrow(self, sql, *args):
        item_key = args[0]
        if item_key in self._claimed:
            return None                 # ON CONFLICT DO NOTHING → no row
        self._claimed.add(item_key)
        return {"id": "row-" + item_key}


class _LedgerAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


def _ledger_patch(claimed):
    return patch("worker.heartbeat.acquire",
                 return_value=_LedgerAcquire(_LedgerConn(claimed)))


# ── flag gate ─────────────────────────────────────────────────────────────────

def test_flag_defaults_off(monkeypatch):
    monkeypatch.delenv("IRA_HEARTBEAT", raising=False)
    assert hb.heartbeat_enabled() is False


@pytest.mark.asyncio
async def test_flag_off_tick_is_noop(monkeypatch):
    monkeypatch.delenv("IRA_HEARTBEAT", raising=False)
    spoken = []
    out = await hb.run_heartbeat_tick(NOW, speak=spoken.append)
    assert out == [] and spoken == []


def test_flag_off_never_schedules(monkeypatch):
    monkeypatch.delenv("IRA_HEARTBEAT", raising=False)

    class _Sched:
        def __init__(self):
            self.jobs = []

        def add_job(self, *a, **k):
            self.jobs.append(k.get("id"))

    sched = _Sched()
    assert hb.register_heartbeat(sched) is False
    assert sched.jobs == []


def test_flag_on_schedules_one_job(monkeypatch):
    _enable(monkeypatch)

    class _Sched:
        def __init__(self):
            self.jobs = []

        def add_job(self, *a, **k):
            self.jobs.append(k.get("id"))

    sched = _Sched()
    assert hb.register_heartbeat(sched) is True
    assert sched.jobs == ["heartbeat"]


# ── tick emits once + de-dupes ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_tick_emits_each_once_then_dedupes(monkeypatch):
    _enable(monkeypatch)
    items = [
        SurfacedItem("decision_review:1", "decision_review", "Review decision 1"),
        SurfacedItem("stale_commitment:2", "stale_commitment", "Still open?"),
    ]

    async def fake_signal(now):
        return list(items)

    spoken: list[str] = []
    claimed: set = set()  # shared ledger across both ticks

    with _ledger_patch(claimed):
        first = await hb.run_heartbeat_tick(NOW, speak=spoken.append, signals=[fake_signal])
        second = await hb.run_heartbeat_tick(NOW, speak=spoken.append, signals=[fake_signal])

    assert set(first) == {"decision_review:1", "stale_commitment:2"}
    assert second == []                       # de-duped on the second tick
    assert len(spoken) == 2                   # spoken exactly once each


@pytest.mark.asyncio
async def test_one_signal_failure_does_not_block_others(monkeypatch):
    _enable(monkeypatch)

    async def bad_signal(now):
        raise RuntimeError("source down")

    async def good_signal(now):
        return [SurfacedItem("ok:1", "k", "hello")]

    spoken: list[str] = []
    with _ledger_patch(set()):
        out = await hb.run_heartbeat_tick(NOW, speak=spoken.append,
                                          signals=[bad_signal, good_signal])
    assert out == ["ok:1"] and spoken == ["hello"]


@pytest.mark.asyncio
async def test_ledger_db_error_fails_closed_no_speak(monkeypatch):
    _enable(monkeypatch)

    async def sig(now):
        return [SurfacedItem("x:1", "k", "msg")]

    spoken: list[str] = []
    with patch("worker.heartbeat.acquire", side_effect=RuntimeError("DB down")):
        out = await hb.run_heartbeat_tick(NOW, speak=spoken.append, signals=[sig])
    # Cannot guarantee no-repeat → fail closed → do not surface.
    assert out == [] and spoken == []


# ── base signals ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_gather_pending_decisions_when_journal_on(monkeypatch):
    _enable(monkeypatch)

    async def fake_pending(now):
        return [{"id": "d1", "summary": "Take offer", "expected_outcome": "relocate"}]

    with patch("memory.decision_journal.journal_enabled", return_value=True), \
         patch("memory.decision_journal.list_pending_reviews", fake_pending):
        items = await hb.gather_pending_decisions(NOW)
    assert len(items) == 1
    assert items[0].key == "decision_review:d1"
    assert "Take offer" in items[0].message


@pytest.mark.asyncio
async def test_gather_pending_decisions_skipped_when_journal_off(monkeypatch):
    _enable(monkeypatch)
    with patch("memory.decision_journal.journal_enabled", return_value=False):
        assert await hb.gather_pending_decisions(NOW) == []


@pytest.mark.asyncio
async def test_gather_stale_commitments_reads_memory(monkeypatch):
    _enable(monkeypatch)

    async def fake_fetch(cutoff, limit=20):
        return [{"source_id": "m1", "content": "I will email the supervisor",
                 "created_at": NOW - timedelta(days=20)}]

    with patch("worker.heartbeat._fetch_stale_commitments", fake_fetch):
        items = await hb.gather_stale_memory_commitments(NOW)
    assert len(items) == 1
    assert items[0].key == "stale_commitment:m1"
    assert "still open" in items[0].message


# ── voice fallback ────────────────────────────────────────────────────────────

def test_default_speak_logs_when_voice_off(monkeypatch):
    # output_mode != "local" → fall back to a logged message, no exception.
    with patch("voice.voice_output.output_mode", return_value="none"):
        hb._default_speak("hello")  # must not raise
