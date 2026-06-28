"""Feature 2 — Decision Journal tests.

Covers: flag-OFF no-op, log_decision insert, list_pending_reviews filtering,
record_outcome clearing a pending review, the optional Life-Graph link (on when
both flags are set, silently skipped when the graph flag is OFF), and fail-closed.
DB + graph are mocked; no Postgres required.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

import pytest

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD",
           "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import memory.decision_journal as dj


class _FakeConn:
    def __init__(self, *, fetchrow_rows=None, fetch_rows=None, execute_results=None):
        self._fetchrow = list(fetchrow_rows or [])
        self._fetch = list(fetch_rows or [])
        self._execute = list(execute_results or [])
        self.calls: list[tuple] = []

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow.pop(0) if self._fetchrow else None

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch.pop(0) if self._fetch else []

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self._execute.pop(0) if self._execute else "UPDATE 0"


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


def _enable(monkeypatch):
    monkeypatch.setenv("IRA_DECISION_JOURNAL", "true")


NOW = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)


# ── flag gate ─────────────────────────────────────────────────────────────────

def test_flag_defaults_on(monkeypatch):
    monkeypatch.delenv("IRA_DECISION_JOURNAL", raising=False)
    assert dj.journal_enabled() is True


def test_flag_explicitly_disabled(monkeypatch):
    monkeypatch.setenv("IRA_DECISION_JOURNAL", "false")
    assert dj.journal_enabled() is False


@pytest.mark.asyncio
async def test_flag_off_is_noop(monkeypatch):
    monkeypatch.setenv("IRA_DECISION_JOURNAL", "false")
    with patch("memory.decision_journal.acquire", side_effect=AssertionError("DB touched")):
        assert await dj.log_decision("x", review_at=NOW) is None
        assert await dj.list_pending_reviews(NOW) == []
        assert await dj.record_outcome("id", "happened") is False


# ── log_decision ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_decision_inserts_and_returns_id(monkeypatch):
    _enable(monkeypatch)
    did = "11111111-1111-1111-1111-111111111111"
    conn = _FakeConn(fetchrow_rows=[{"id": did}])
    with patch("memory.decision_journal.acquire", return_value=_FakeAcquire(conn)):
        out = await dj.log_decision(
            "Take the Luxembourg offer",
            reasoning="Better funding",
            expected_outcome="Relocate by autumn",
            review_at=NOW + timedelta(days=30),
        )
    assert out == did
    _, sql, args = conn.calls[0]
    assert "INSERT INTO decisions" in sql
    assert args[0] == "Take the Luxembourg offer"


@pytest.mark.asyncio
async def test_log_decision_requires_summary(monkeypatch):
    _enable(monkeypatch)
    with patch("memory.decision_journal.acquire", side_effect=AssertionError("DB touched")):
        assert await dj.log_decision("   ", review_at=NOW) is None


# ── list_pending_reviews ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_pending_reviews(monkeypatch):
    _enable(monkeypatch)
    rows = [{
        "id": "22222222-2222-2222-2222-222222222222",
        "summary": "Apply to PhD", "reasoning": "career", "expected_outcome": "accepted",
        "decided_at": NOW - timedelta(days=40), "review_at": NOW - timedelta(days=1),
    }]
    conn = _FakeConn(fetch_rows=[rows])
    with patch("memory.decision_journal.acquire", return_value=_FakeAcquire(conn)):
        out = await dj.list_pending_reviews(NOW)
    assert len(out) == 1 and out[0]["summary"] == "Apply to PhD"
    _, sql, args = conn.calls[0]
    assert "review_at <= $1" in sql and "reviewed_at IS NULL" in sql
    assert args[0] == NOW


# ── record_outcome ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_record_outcome_clears_pending(monkeypatch):
    _enable(monkeypatch)
    conn = _FakeConn(execute_results=["UPDATE 1"])
    with patch("memory.decision_journal.acquire", return_value=_FakeAcquire(conn)):
        ok = await dj.record_outcome(
            "22222222-2222-2222-2222-222222222222",
            "Was accepted", calibration_note="Expectation matched",
        )
    assert ok is True
    _, sql, _ = conn.calls[0]
    assert "UPDATE decisions" in sql and "reviewed_at = NOW()" in sql


@pytest.mark.asyncio
async def test_record_outcome_idempotent_second_call_noops(monkeypatch):
    _enable(monkeypatch)
    conn = _FakeConn(execute_results=["UPDATE 0"])  # already reviewed
    with patch("memory.decision_journal.acquire", return_value=_FakeAcquire(conn)):
        assert await dj.record_outcome("id", "x") is False


# ── optional Life-Graph link ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_log_decision_links_graph_when_both_flags_on(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("IRA_LIFE_GRAPH", "true")
    did = "33333333-3333-3333-3333-333333333333"
    entity = "44444444-4444-4444-4444-444444444444"
    conn = _FakeConn(fetchrow_rows=[{"id": did}])

    calls = {}

    async def fake_upsert(type, name, description=None, **kw):
        calls["upsert"] = (type, name, description)
        return "decision-entity-id"

    async def fake_add_edge(src, dst, relation, **kw):
        calls["edge"] = (src, dst, relation)
        return "edge-id"

    with patch("memory.decision_journal.acquire", return_value=_FakeAcquire(conn)), \
         patch("memory.life_graph.graph_enabled", return_value=True), \
         patch("memory.life_graph.upsert_entity", fake_upsert), \
         patch("memory.life_graph.add_edge", fake_add_edge):
        out = await dj.log_decision("decide", review_at=NOW, about_entity_id=entity)

    assert out == did
    assert calls["upsert"][0] == "decision"
    assert calls["edge"] == ("decision-entity-id", entity, "decision_about")


@pytest.mark.asyncio
async def test_log_decision_skips_graph_when_graph_flag_off(monkeypatch):
    _enable(monkeypatch)
    monkeypatch.setenv("IRA_LIFE_GRAPH", "false")
    conn = _FakeConn(fetchrow_rows=[{"id": "55555555-5555-5555-5555-555555555555"}])

    def _boom(*a, **k):
        raise AssertionError("graph touched while flag OFF")

    with patch("memory.decision_journal.acquire", return_value=_FakeAcquire(conn)), \
         patch("memory.life_graph.upsert_entity", _boom):
        out = await dj.log_decision("decide", review_at=NOW,
                                    about_entity_id="44444444-4444-4444-4444-444444444444")
    assert out is not None  # decision still logged, graph silently skipped


# ── fail-closed ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_db_error_fails_closed(monkeypatch):
    _enable(monkeypatch)
    with patch("memory.decision_journal.acquire", side_effect=RuntimeError("DB down")):
        assert await dj.log_decision("d", review_at=NOW) is None
        assert await dj.list_pending_reviews(NOW) == []
        assert await dj.record_outcome("id", "x") is False
