"""Feature 3 addendum — recurring themes, calendar deadlines, open loops.

Each signal is tested for the real path and the degraded (no-source) branch, which
must return [] cleanly. DB + decision journal are mocked.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD",
           "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import worker.heartbeat_signals as sig

NOW = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)


class _FakeConn:
    def __init__(self, fetch_rows):
        self._rows = list(fetch_rows)

    async def fetch(self, sql, *args):
        return self._rows.pop(0) if self._rows else []


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


def _acq(*fetch_batches):
    return patch("worker.heartbeat_signals.acquire",
                 return_value=_FakeAcquire(_FakeConn(list(fetch_batches))))


# ── Signal A — recurring themes ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_recurring_theme_crosses_threshold(monkeypatch):
    monkeypatch.setenv("IRA_HEARTBEAT_RECURRENCE_MIN", "3")
    rows = [
        {"content": "thinking about the visa timeline again"},
        {"content": "the visa paperwork is stressing me"},
        {"content": "visa appointment maybe next month"},
        {"content": "had coffee with a friend"},
    ]
    with _acq(rows):
        items = await sig.gather_recurring_themes(NOW)
    keys = {i.key.split(":")[1] for i in items}
    assert "visa" in keys                          # appears in 3 distinct entries
    assert all(i.kind == "recurring_theme" for i in items)
    visa = next(i for i in items if i.key.split(":")[1] == "visa")
    assert "3 times" in visa.message


@pytest.mark.asyncio
async def test_recurring_theme_below_threshold_silent(monkeypatch):
    monkeypatch.setenv("IRA_HEARTBEAT_RECURRENCE_MIN", "3")
    rows = [{"content": "visa once"}, {"content": "visa twice"}]  # only 2
    with _acq(rows):
        items = await sig.gather_recurring_themes(NOW)
    assert all(i.key.split(":")[1] != "visa" for i in items)


@pytest.mark.asyncio
async def test_recurring_theme_no_memory_degrades_to_empty():
    with _acq([]):  # empty window
        assert await sig.gather_recurring_themes(NOW) == []


@pytest.mark.asyncio
async def test_recurring_theme_db_error_fails_closed():
    with patch("worker.heartbeat_signals.acquire", side_effect=RuntimeError("down")):
        assert await sig.gather_recurring_themes(NOW) == []


# ── Signal B — calendar deadlines ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_calendar_deadlines_real_source():
    rows = [{"id": "ev1", "title": "PhD submission",
             "start_at": NOW + timedelta(days=3)}]
    with _acq(rows):
        items = await sig.gather_calendar_deadlines(NOW)
    assert len(items) == 1
    assert items[0].key == "calendar_deadline:ev1"
    assert items[0].kind == "calendar_deadline"
    assert "PhD submission" in items[0].message and "3 day" in items[0].message


@pytest.mark.asyncio
async def test_calendar_deadlines_empty_degrades_cleanly():
    with _acq([]):  # no calendar rows
        assert await sig.gather_calendar_deadlines(NOW) == []


@pytest.mark.asyncio
async def test_calendar_deadlines_db_error_fails_closed():
    with patch("worker.heartbeat_signals.acquire", side_effect=RuntimeError("no table")):
        assert await sig.gather_calendar_deadlines(NOW) == []


# ── Signal C — open loops ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_open_loops_from_journal_and_memory():
    async def fake_overdue(cutoff):
        assert cutoff < NOW  # grace applied
        return [{"id": "d9", "summary": "Switch banks", "expected_outcome": "x"}]

    mem_rows = [{"source_id": "m5", "content": "I said I'd close on_speak last sprint"}]
    with patch("memory.decision_journal.list_pending_reviews", fake_overdue), \
         _acq(mem_rows):
        items = await sig.gather_open_loops(NOW)
    keys = {i.key for i in items}
    assert "open_loop:decision:d9" in keys
    assert "open_loop:mem:m5" in keys
    assert all(i.kind == "open_loop" for i in items)


@pytest.mark.asyncio
async def test_open_loops_degrade_when_no_sources():
    async def empty_overdue(cutoff):
        return []

    with patch("memory.decision_journal.list_pending_reviews", empty_overdue), \
         _acq([]):
        assert await sig.gather_open_loops(NOW) == []


@pytest.mark.asyncio
async def test_open_loops_memory_error_isolated_from_journal():
    async def fake_overdue(cutoff):
        return [{"id": "d1", "summary": "S", "expected_outcome": None}]

    # Journal yields one loop; memory scan raises — must still return the journal loop.
    with patch("memory.decision_journal.list_pending_reviews", fake_overdue), \
         patch("worker.heartbeat_signals.acquire", side_effect=RuntimeError("mem down")):
        items = await sig.gather_open_loops(NOW)
    assert [i.key for i in items] == ["open_loop:decision:d1"]


# ── registration into the base engine ─────────────────────────────────────────

def test_additional_signals_registered():
    names = {f.__name__ for f in sig.ADDITIONAL_SIGNALS}
    assert names == {"gather_recurring_themes", "gather_calendar_deadlines",
                     "gather_open_loops"}


def test_default_signals_includes_addendum(monkeypatch):
    monkeypatch.setenv("IRA_HEARTBEAT", "true")
    import worker.heartbeat as hb
    names = {f.__name__ for f in hb.default_signals()}
    assert {"gather_pending_decisions", "gather_stale_memory_commitments",
            "gather_recurring_themes", "gather_calendar_deadlines",
            "gather_open_loops"} <= names
