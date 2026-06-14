"""P2.3 — Tests for progressive account lockout.

All Redis calls are mocked. No live Redis or DB required.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

# ── Redis mock helpers ────────────────────────────────────────────────────────

def _redis_store() -> dict:
    """Simple in-memory store simulating Redis for lockout tests."""
    return {}


def _make_redis_mock(store: dict | None = None):
    """Return an AsyncMock that simulates aioredis for the lockout keys."""
    if store is None:
        store = {}

    async def _incr(key):
        store[key] = store.get(key, 0) + 1
        return store[key]

    async def _expire(key, ttl):
        return True

    async def _setex(key, ttl, value):
        store[key] = value
        return True

    async def _exists(*keys):
        return sum(1 for k in keys if k in store)

    async def _get(key):
        return str(store[key]) if key in store else None

    async def _delete(*keys):
        for k in keys:
            store.pop(k, None)
        return len(keys)

    r = AsyncMock()
    r.incr = AsyncMock(side_effect=_incr)
    r.expire = AsyncMock(side_effect=_expire)
    r.setex = AsyncMock(side_effect=_setex)
    r.exists = AsyncMock(side_effect=_exists)
    r.get = AsyncMock(side_effect=_get)
    r.delete = AsyncMock(side_effect=_delete)
    return r, store


# ── is_locked ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_locked_false_when_no_lock_key():
    r, store = _make_redis_mock()
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import is_locked
        assert not await is_locked("admin")


@pytest.mark.asyncio
async def test_is_locked_true_when_lock_key_exists():
    r, store = _make_redis_mock()
    store["ira:login_lock:admin"] = "1"
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import is_locked
        assert await is_locked("admin")


# ── record_failure / lockout threshold ────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_lock_before_threshold():
    r, store = _make_redis_mock()
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import record_failure, MAX_FAILURES
        for _ in range(MAX_FAILURES - 1):
            count, locked = await record_failure("admin")
            assert not locked, "Should not lock before MAX_FAILURES"


@pytest.mark.asyncio
async def test_lock_at_threshold():
    r, store = _make_redis_mock()
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import record_failure, MAX_FAILURES, _LOCK_PREFIX
        for i in range(MAX_FAILURES):
            count, locked = await record_failure("admin")
        # The MAX_FAILURES-th failure must lock
        assert locked
        assert f"{_LOCK_PREFIX}admin" in store


@pytest.mark.asyncio
async def test_lock_escalates_after_threshold():
    """Each failure beyond MAX_FAILURES doubles the lock duration."""
    r, store = _make_redis_mock()
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import record_failure, MAX_FAILURES, BASE_LOCK_SECONDS, _LOCK_PREFIX
        # Reach threshold — lock duration = BASE_LOCK_SECONDS
        for _ in range(MAX_FAILURES):
            await record_failure("escalate_user")
        # One more failure — lock duration should double
        await record_failure("escalate_user")
        # setex was called; the last call should have a larger TTL than BASE_LOCK_SECONDS
        calls = r.setex.call_args_list
        lock_calls = [c for c in calls if _LOCK_PREFIX in str(c)]
        assert len(lock_calls) >= 2
        first_ttl = lock_calls[0].args[1]
        second_ttl = lock_calls[1].args[1]
        assert second_ttl > first_ttl, "Lock TTL should escalate with each extra failure"


# ── clear_failures ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_clear_failures_removes_counter_and_lock():
    r, store = _make_redis_mock()
    store["ira:login_fails:admin"] = 3
    store["ira:login_lock:admin"] = "1"
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import clear_failures, is_locked, get_fail_count
        await clear_failures("admin")
        assert "ira:login_fails:admin" not in store
        assert "ira:login_lock:admin" not in store
        assert not await is_locked("admin")


@pytest.mark.asyncio
async def test_clear_on_success_after_failures():
    """Successful login after N < MAX failures clears the counter."""
    r, store = _make_redis_mock()
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import record_failure, clear_failures, get_fail_count, MAX_FAILURES
        # 2 failures
        await record_failure("admin")
        await record_failure("admin")
        assert await get_fail_count("admin") == 2
        # Successful login
        await clear_failures("admin")
        assert await get_fail_count("admin") == 0


# ── fail-soft on Redis unavailability ────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_locked_fail_soft_on_redis_error():
    """Redis failure must not block the owner out (fail-open)."""
    from utils.redis_client import get_redis
    with patch("utils.redis_client.get_redis", side_effect=RuntimeError("Redis down")):
        from utils.account_lockout import is_locked
        result = await is_locked("admin")
    assert result is False, "Must fail-open when Redis is unavailable"


@pytest.mark.asyncio
async def test_record_failure_fail_soft_on_redis_error():
    """Redis failure in record_failure must return (0, False)."""
    with patch("utils.redis_client.get_redis", side_effect=RuntimeError("Redis down")):
        from utils.account_lockout import record_failure
        count, locked = await record_failure("admin")
    assert count == 0
    assert locked is False


# ── timing: username enumeration guard ───────────────────────────────────────

@pytest.mark.asyncio
async def test_lockout_applies_per_username():
    """Lockout is per-username; one user locked does not affect another."""
    r, store = _make_redis_mock()
    with patch("utils.redis_client.get_redis", return_value=r):
        from utils.account_lockout import record_failure, is_locked, MAX_FAILURES
        for _ in range(MAX_FAILURES):
            await record_failure("user_a")
        assert await is_locked("user_a")
        assert not await is_locked("user_b"), "user_b must not be locked"
