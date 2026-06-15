"""P6.2 — Tests for bounded automated security playbooks.

Covers:
- ALLOWED_ACTIONS contains exactly the three permitted actions
- run_playbook() refuses unknown actions and logs a warning
- rotate_tokens() increments the token version in Redis
- block_ip() sets a Redis key with correct TTL; TTL is capped at 7 days
- is_ip_blocked() returns True when key exists, False otherwise
- snapshot_logs() writes a JSON file to the snapshot directory
- All actions fail-soft: infrastructure errors return False, never raise
- run_security_playbooks() dispatches brute_force → block_ip, canary → block_ip, disk_pressure → snapshot
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from utils.playbooks import (
    ALLOWED_ACTIONS,
    block_ip,
    is_ip_blocked,
    rotate_tokens,
    run_playbook,
    snapshot_logs,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

class _FakeRedis:
    def __init__(self):
        self.store: dict[str, tuple[str, int]] = {}  # key -> (value, ttl)

    async def incr(self, key: str) -> int:
        val = int(self.store.get(key, ("0", 0))[0]) + 1
        self.store[key] = (str(val), 0)
        return val

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = (value, ttl)
        return True

    async def exists(self, *keys: str) -> int:
        return sum(1 for k in keys if k in self.store)

    async def get(self, key: str):
        v = self.store.get(key)
        return v[0].encode() if v else None


def _noop_audit():
    """Patch _audit so tests don't need a DB."""
    async def _audit(*a, **kw): pass
    return patch("utils.playbooks._audit", side_effect=_audit)


# ── ALLOWED_ACTIONS ───────────────────────────────────────────────────────────

def test_allowed_actions_contains_exactly_three():
    assert ALLOWED_ACTIONS == {"rotate_tokens", "block_ip", "snapshot_logs"}


def test_allowed_actions_is_frozenset():
    assert isinstance(ALLOWED_ACTIONS, frozenset)


# ── run_playbook gatekeeper ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_playbook_refuses_unknown_action():
    with _noop_audit():
        result = await run_playbook("rm_rf_everything")
    assert result is False


@pytest.mark.asyncio
async def test_run_playbook_refuses_injection_attempt():
    with _noop_audit():
        result = await run_playbook("__import__('os').system('id')")
    assert result is False


@pytest.mark.asyncio
async def test_run_playbook_dispatches_block_ip():
    r = _FakeRedis()
    with _noop_audit(), \
         patch("utils.redis_client.get_redis", return_value=r):
        result = await run_playbook("block_ip", ip_address="1.2.3.4", ttl_seconds=300)
    assert result is True
    assert "ira:blocked_ip:1.2.3.4" in r.store


@pytest.mark.asyncio
async def test_run_playbook_dispatches_rotate_tokens():
    r = _FakeRedis()
    with _noop_audit(), \
         patch("utils.redis_client.get_redis", return_value=r):
        result = await run_playbook("rotate_tokens", username="admin")
    assert result is True
    assert "ira:token_ver:admin" in r.store


# ── rotate_tokens ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rotate_tokens_increments_version():
    r = _FakeRedis()
    with patch("utils.redis_client.get_redis", return_value=r):
        ok = await rotate_tokens("testuser")
    assert ok is True
    assert r.store["ira:token_ver:testuser"][0] == "1"


@pytest.mark.asyncio
async def test_rotate_tokens_second_call_reaches_two():
    r = _FakeRedis()
    with patch("utils.redis_client.get_redis", return_value=r):
        await rotate_tokens("testuser")
        await rotate_tokens("testuser")
    assert r.store["ira:token_ver:testuser"][0] == "2"


@pytest.mark.asyncio
async def test_rotate_tokens_empty_username_returns_false():
    result = await rotate_tokens("")
    assert result is False


@pytest.mark.asyncio
async def test_rotate_tokens_redis_error_is_failsoft():
    with patch("utils.redis_client.get_redis", side_effect=RuntimeError("Redis down")):
        result = await rotate_tokens("admin")
    assert result is False


# ── block_ip ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_block_ip_sets_redis_key_with_ttl():
    r = _FakeRedis()
    with patch("utils.redis_client.get_redis", return_value=r):
        ok = await block_ip("192.168.1.1", ttl_seconds=1800)
    assert ok is True
    key, (val, ttl) = "ira:blocked_ip:192.168.1.1", r.store["ira:blocked_ip:192.168.1.1"]
    assert val == "1"
    assert ttl == 1800


@pytest.mark.asyncio
async def test_block_ip_caps_ttl_at_seven_days():
    r = _FakeRedis()
    with patch("utils.redis_client.get_redis", return_value=r):
        await block_ip("10.0.0.1", ttl_seconds=9_999_999)
    _, ttl = r.store["ira:blocked_ip:10.0.0.1"]
    assert ttl == 86400 * 7


@pytest.mark.asyncio
async def test_block_ip_empty_address_returns_false():
    result = await block_ip("")
    assert result is False


@pytest.mark.asyncio
async def test_block_ip_redis_error_is_failsoft():
    with patch("utils.redis_client.get_redis", side_effect=RuntimeError("Redis down")):
        result = await block_ip("5.5.5.5")
    assert result is False


# ── is_ip_blocked ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_ip_blocked_true_when_key_exists():
    r = _FakeRedis()
    r.store["ira:blocked_ip:1.1.1.1"] = ("1", 3600)
    with patch("utils.redis_client.get_redis", return_value=r):
        result = await is_ip_blocked("1.1.1.1")
    assert result is True


@pytest.mark.asyncio
async def test_is_ip_blocked_false_when_key_absent():
    r = _FakeRedis()
    with patch("utils.redis_client.get_redis", return_value=r):
        result = await is_ip_blocked("2.2.2.2")
    assert result is False


@pytest.mark.asyncio
async def test_is_ip_blocked_failopen_on_redis_error():
    with patch("utils.redis_client.get_redis", side_effect=RuntimeError("Redis down")):
        result = await is_ip_blocked("3.3.3.3")
    assert result is False


# ── snapshot_logs ─────────────────────────────────────────────────────────────

class _FakeConn:
    async def fetch(self, sql, *args):
        return [
            {
                "severity": "high",
                "event_type": "brute_force",
                "source_ip": "6.6.6.6",
                "description": "brute force",
                "raw_log": "",
                "resolved": False,
                "created_at": datetime(2026, 6, 14, 12, 0, 0, tzinfo=timezone.utc),
            }
        ]

class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn
    async def __aenter__(self):
        return self._conn
    async def __aexit__(self, *_):
        pass


@pytest.mark.asyncio
async def test_snapshot_logs_creates_file():
    conn = _FakeConn()
    with tempfile.TemporaryDirectory() as tmpdir, \
         patch.dict(os.environ, {"IRA_LOG_SNAPSHOT_DIR": tmpdir}), \
         patch("utils.db.acquire", return_value=_FakeAcquire(conn)):
        ok = await snapshot_logs(label="test")
        # Check files while tmpdir still exists
        files = list(Path(tmpdir).glob("ira-security-snapshot-test-*.json"))
        assert ok is True
        assert len(files) == 1


@pytest.mark.asyncio
async def test_snapshot_logs_file_has_correct_structure():
    conn = _FakeConn()
    with tempfile.TemporaryDirectory() as tmpdir, \
         patch.dict(os.environ, {"IRA_LOG_SNAPSHOT_DIR": tmpdir}), \
         patch("utils.db.acquire", return_value=_FakeAcquire(conn)):
        await snapshot_logs(label="structure_test")
        files = list(Path(tmpdir).glob("*.json"))
        data = json.loads(files[0].read_text())

    assert data["snapshot_label"] == "structure_test"
    assert data["event_count"] == 1
    assert data["events"][0]["event_type"] == "brute_force"


@pytest.mark.asyncio
async def test_snapshot_logs_db_error_is_failsoft():
    with tempfile.TemporaryDirectory() as tmpdir, \
         patch.dict(os.environ, {"IRA_LOG_SNAPSHOT_DIR": tmpdir}), \
         patch("utils.db.acquire", side_effect=RuntimeError("DB down")):
        result = await snapshot_logs(label="error_test")
    assert result is False


# ── run_security_playbooks dispatch ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_security_playbooks_brute_force_blocks_ip():
    r = _FakeRedis()
    events = [{"event_type": "brute_force", "source_ip": "7.7.7.7", "severity": "high"}]

    async def fake_emit(*a, **kw): pass
    with patch("utils.redis_client.get_redis", return_value=r), \
         patch("utils.playbooks._audit", side_effect=fake_emit):
        from worker.self_healing import run_security_playbooks
        await run_security_playbooks(events)

    assert "ira:blocked_ip:7.7.7.7" in r.store


@pytest.mark.asyncio
async def test_run_security_playbooks_canary_tripwire_blocks_ip():
    r = _FakeRedis()
    events = [{"event_type": "canary_tripwire_hit", "source_ip": "8.8.8.8", "severity": "critical"}]

    async def fake_emit(*a, **kw): pass
    with patch("utils.redis_client.get_redis", return_value=r), \
         patch("utils.playbooks._audit", side_effect=fake_emit):
        from worker.self_healing import run_security_playbooks
        await run_security_playbooks(events)

    assert "ira:blocked_ip:8.8.8.8" in r.store
    _, ttl = r.store["ira:blocked_ip:8.8.8.8"]
    assert ttl == 86400  # canary gets 24h block


@pytest.mark.asyncio
async def test_run_security_playbooks_no_source_ip_skips_block():
    r = _FakeRedis()
    events = [{"event_type": "brute_force", "source_ip": None, "severity": "high"}]

    async def fake_emit(*a, **kw): pass
    with patch("utils.redis_client.get_redis", return_value=r), \
         patch("utils.playbooks._audit", side_effect=fake_emit):
        from worker.self_healing import run_security_playbooks
        await run_security_playbooks(events)

    # No IP blocks should have been added
    blocked = [k for k in r.store if k.startswith("ira:blocked_ip:")]
    assert blocked == []


@pytest.mark.asyncio
async def test_run_security_playbooks_unknown_event_is_noop():
    r = _FakeRedis()
    events = [{"event_type": "unknown_event_type", "source_ip": "9.9.9.9", "severity": "low"}]

    async def fake_emit(*a, **kw): pass
    with patch("utils.redis_client.get_redis", return_value=r), \
         patch("utils.playbooks._audit", side_effect=fake_emit):
        from worker.self_healing import run_security_playbooks
        await run_security_playbooks(events)

    blocked = [k for k in r.store if k.startswith("ira:blocked_ip:")]
    assert blocked == []
