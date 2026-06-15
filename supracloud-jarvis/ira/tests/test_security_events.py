"""P5.1 — Tests for real-time security event emission.

Covers:
- emit_event() writes to security_events table
- HIGH/CRITICAL events trigger Telegram push; lower severities do not
- DB failure is fail-soft (no exception propagated)
- Telegram failure is fail-soft
- account_lockout.record_failure emits events to security_events
- classify_guard_refusal maps guard reasons to correct (event_type, severity)
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from utils.security_events import classify_guard_refusal, emit_event


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeConn:
    def __init__(self):
        self.executed: list[tuple] = []

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        pass


# ── emit_event: DB write ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_event_writes_to_db():
    conn = _FakeConn()
    with patch("utils.security_events.emit_event.__module__"):
        pass
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)):
        await emit_event("test_event", "medium", description="hello")

    assert len(conn.executed) == 1
    sql, args = conn.executed[0]
    assert "INSERT INTO security_events" in sql
    assert "test_event" in args
    assert "medium" in args
    assert "hello" in args


@pytest.mark.asyncio
async def test_emit_event_includes_source_ip():
    conn = _FakeConn()
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)):
        await emit_event("ssrf_block", "high", source_ip="10.0.0.1", description="SSRF attempt")

    _, args = conn.executed[0]
    assert "10.0.0.1" in args


@pytest.mark.asyncio
async def test_emit_event_truncates_long_description():
    conn = _FakeConn()
    long_desc = "x" * 2000
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)):
        await emit_event("test", "info", description=long_desc)

    _, args = conn.executed[0]
    # Description is the 4th positional arg ($4)
    actual_desc = args[3]
    assert len(actual_desc) <= 1000


@pytest.mark.asyncio
async def test_emit_event_db_failure_is_failsoft():
    """DB error must not raise — emit_event must return cleanly."""
    with patch("utils.db.acquire", side_effect=RuntimeError("DB down")):
        # Should not raise
        await emit_event("test", "critical", description="test")


# ── emit_event: Telegram push ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_emit_event_high_severity_pushes_telegram():
    conn = _FakeConn()
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)), \
         patch("utils.security_events._do_telegram_push") as mock_push:
        await emit_event("account_locked", "high", description="user locked")

    mock_push.assert_called_once()
    _, sev, desc = mock_push.call_args.args
    assert sev == "high"
    assert "user locked" in desc


@pytest.mark.asyncio
async def test_emit_event_critical_severity_pushes_telegram():
    conn = _FakeConn()
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)), \
         patch("utils.security_events._do_telegram_push") as mock_push:
        await emit_event("credential_exfiltration_attempt", "critical", description="secret found")

    mock_push.assert_called_once()
    event_type, sev, _ = mock_push.call_args.args
    assert sev == "critical"


@pytest.mark.asyncio
async def test_emit_event_medium_does_not_push_telegram():
    conn = _FakeConn()
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)), \
         patch("utils.security_events._do_telegram_push") as mock_push:
        await emit_event("login_failure", "medium", description="one failure")

    mock_push.assert_not_called()


@pytest.mark.asyncio
async def test_emit_event_info_does_not_push_telegram():
    conn = _FakeConn()
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)), \
         patch("utils.security_events._do_telegram_push") as mock_push:
        await emit_event("health_check", "info")

    mock_push.assert_not_called()


@pytest.mark.asyncio
async def test_emit_event_telegram_failure_is_failsoft():
    """Telegram push failure must not raise."""
    conn = _FakeConn()
    with patch("utils.db.acquire", return_value=_FakeAcquire(conn)), \
         patch("utils.security_events._do_telegram_push",
               side_effect=RuntimeError("Telegram down")):
        # Should not raise even though Telegram fails
        await emit_event("account_locked", "high", description="test")


# ── classify_guard_refusal ────────────────────────────────────────────────────

def test_classify_private_host_ssrf():
    event_type, severity = classify_guard_refusal(
        "Blocked: refusing to fetch a private/internal host (127.0.0.1).", has_url=True
    )
    assert event_type == "ssrf_block"
    assert severity == "high"


def test_classify_localhost_ssrf():
    event_type, severity = classify_guard_refusal(
        "Blocked: refusing to fetch a private/internal host (localhost)."
    )
    assert event_type == "ssrf_block"
    assert severity == "high"


def test_classify_credential_smuggling():
    event_type, severity = classify_guard_refusal(
        "Blocked: query appears to contain a secret/credential — not sent outbound"
    )
    assert event_type == "credential_exfiltration_attempt"
    assert severity == "critical"


def test_classify_local_file_path():
    event_type, severity = classify_guard_refusal(
        "Blocked: query appears to contain a local file path — not sent outbound"
    )
    assert event_type == "local_path_exfiltration_attempt"
    assert severity == "high"


def test_classify_unknown_reason_with_url():
    event_type, severity = classify_guard_refusal("Blocked: only http(s) URLs allowed.", has_url=True)
    assert event_type == "ssrf_block"
    assert severity == "high"


def test_classify_unknown_reason_no_url():
    event_type, severity = classify_guard_refusal("Blocked: unknown reason.")
    assert event_type == "outbound_request_blocked"
    assert severity == "medium"


# ── account_lockout: emit on failure ─────────────────────────────────────────

def _make_redis_mock(store=None):
    if store is None:
        store = {}

    async def _incr(key):
        store[key] = store.get(key, 0) + 1
        return store[key]

    async def _expire(key, ttl): return True
    async def _setex(key, ttl, value):
        store[key] = value
        return True
    async def _exists(*keys): return sum(1 for k in keys if k in store)
    async def _get(key): return str(store[key]) if key in store else None
    async def _delete(*keys):
        for k in keys: store.pop(k, None)
        return len(keys)

    r = AsyncMock()
    r.incr = AsyncMock(side_effect=_incr)
    r.expire = AsyncMock(side_effect=_expire)
    r.setex = AsyncMock(side_effect=_setex)
    r.exists = AsyncMock(side_effect=_exists)
    r.get = AsyncMock(side_effect=_get)
    r.delete = AsyncMock(side_effect=_delete)
    return r, store


@pytest.mark.asyncio
async def test_record_failure_emits_login_failure_event():
    r, store = _make_redis_mock()
    emitted: list[tuple] = []

    async def fake_emit(event_type, severity="medium", **kwargs):
        emitted.append((event_type, severity))

    with patch("utils.redis_client.get_redis", return_value=r), \
         patch("utils.security_events.emit_event", side_effect=fake_emit):
        from utils.account_lockout import record_failure
        await record_failure("testuser")

    assert any(et == "login_failure" for et, _ in emitted)


@pytest.mark.asyncio
async def test_record_failure_emits_account_locked_on_threshold():
    r, store = _make_redis_mock()
    emitted: list[tuple] = []

    async def fake_emit(event_type, severity="medium", **kwargs):
        emitted.append((event_type, severity))

    with patch("utils.redis_client.get_redis", return_value=r), \
         patch("utils.security_events.emit_event", side_effect=fake_emit):
        from utils.account_lockout import record_failure, MAX_FAILURES
        for _ in range(MAX_FAILURES):
            await record_failure("lockuser")

    event_types = [et for et, _ in emitted]
    assert "account_locked" in event_types
    # The account_locked event must be HIGH severity
    locked_events = [(et, sv) for et, sv in emitted if et == "account_locked"]
    assert all(sv == "high" for _, sv in locked_events)


@pytest.mark.asyncio
async def test_record_failure_emit_error_does_not_break_lockout():
    """If emit_event fails, record_failure must still return correctly."""
    r, store = _make_redis_mock()

    async def bad_emit(*args, **kwargs):
        raise RuntimeError("DB unavailable")

    with patch("utils.redis_client.get_redis", return_value=r), \
         patch("utils.security_events.emit_event", side_effect=bad_emit):
        from utils.account_lockout import record_failure
        count, locked = await record_failure("adminuser")

    # Lockout logic must not be affected by emit failure
    assert count == 1
    assert locked is False
