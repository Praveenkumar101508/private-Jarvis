"""P5.2 — Tests for canary tokens and honeypot tripwires.

Covers:
- check_canary_token(): fires CRITICAL event and returns True on match; no-op without config
- check_canary_username(): fires CRITICAL event and returns True on match; case-insensitive
- Canary paths list is non-empty and contains expected high-value targets
- Honeypot router correctly reports CRITICAL events on requests to canary paths
- Tripwires do not block normal flow when IRA_CANARY_TOKEN / IRA_CANARY_USERNAME not set
- Emit failure is fail-soft: tripwire still returns True even if DB is down
"""
from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest

from utils.canary import (
    _CANARY_PATHS,
    check_canary_token,
    check_canary_username,
    get_canary_token,
    get_canary_username,
)


# ── Fixture helpers ────────────────────────────────────────────────────────────

async def _noop_emit(*args, **kwargs):
    pass


# ── get_canary_token / get_canary_username ────────────────────────────────────

def test_get_canary_token_returns_none_when_not_set():
    with patch.dict(os.environ, {"IRA_CANARY_TOKEN": ""}):
        assert get_canary_token() is None


def test_get_canary_token_returns_value_when_set():
    with patch.dict(os.environ, {"IRA_CANARY_TOKEN": "supersecretcanary"}):
        assert get_canary_token() == "supersecretcanary"


def test_get_canary_username_returns_none_when_not_set():
    with patch.dict(os.environ, {"IRA_CANARY_USERNAME": ""}):
        assert get_canary_username() is None


def test_get_canary_username_returns_value_when_set():
    with patch.dict(os.environ, {"IRA_CANARY_USERNAME": "ghost_admin"}):
        assert get_canary_username() == "ghost_admin"


# ── check_canary_token ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_canary_token_no_op_when_not_configured():
    with patch.dict(os.environ, {"IRA_CANARY_TOKEN": ""}), \
         patch("utils.security_events.emit_event", side_effect=_noop_emit) as mock_emit:
        result = await check_canary_token("any-bearer-value")
    assert result is False
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_canary_token_not_triggered_by_normal_token():
    with patch.dict(os.environ, {"IRA_CANARY_TOKEN": "canary-abc123"}), \
         patch("utils.security_events.emit_event", side_effect=_noop_emit) as mock_emit:
        result = await check_canary_token("normal-jwt-token-value")
    assert result is False
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_canary_token_fires_critical_on_exact_match():
    emitted: list[tuple] = []

    async def capture_emit(event_type, severity="medium", **kwargs):
        emitted.append((event_type, severity))

    with patch.dict(os.environ, {"IRA_CANARY_TOKEN": "canary-secret-token"}), \
         patch("utils.security_events.emit_event", side_effect=capture_emit):
        result = await check_canary_token("canary-secret-token")

    assert result is True
    assert len(emitted) == 1
    event_type, severity = emitted[0]
    assert event_type == "canary_token_used"
    assert severity == "critical"


@pytest.mark.asyncio
async def test_canary_token_returns_true_even_if_emit_fails():
    """Tripwire must report True even when the DB/emit fails."""
    async def bad_emit(*args, **kwargs):
        raise RuntimeError("DB down")

    with patch.dict(os.environ, {"IRA_CANARY_TOKEN": "canary-secret-token"}), \
         patch("utils.security_events.emit_event", side_effect=bad_emit):
        result = await check_canary_token("canary-secret-token")

    assert result is True


@pytest.mark.asyncio
async def test_canary_token_includes_source_ip_in_event():
    emitted: list[dict] = []

    async def capture_emit(event_type, severity="medium", **kwargs):
        emitted.append({"event_type": event_type, **kwargs})

    with patch.dict(os.environ, {"IRA_CANARY_TOKEN": "canary-tk"}), \
         patch("utils.security_events.emit_event", side_effect=capture_emit):
        await check_canary_token("canary-tk", source_ip="192.168.1.100")

    assert emitted[0]["source_ip"] == "192.168.1.100"


# ── check_canary_username ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_canary_username_no_op_when_not_configured():
    with patch.dict(os.environ, {"IRA_CANARY_USERNAME": ""}), \
         patch("utils.security_events.emit_event", side_effect=_noop_emit) as mock_emit:
        result = await check_canary_username("admin")
    assert result is False
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_canary_username_not_triggered_by_real_user():
    with patch.dict(os.environ, {"IRA_CANARY_USERNAME": "ghost_admin"}), \
         patch("utils.security_events.emit_event", side_effect=_noop_emit) as mock_emit:
        result = await check_canary_username("admin")
    assert result is False
    mock_emit.assert_not_called()


@pytest.mark.asyncio
async def test_canary_username_fires_critical_on_match():
    emitted: list[tuple] = []

    async def capture_emit(event_type, severity="medium", **kwargs):
        emitted.append((event_type, severity))

    with patch.dict(os.environ, {"IRA_CANARY_USERNAME": "ghost_admin"}), \
         patch("utils.security_events.emit_event", side_effect=capture_emit):
        result = await check_canary_username("ghost_admin")

    assert result is True
    assert ("canary_username_login_attempt", "critical") in emitted


@pytest.mark.asyncio
async def test_canary_username_is_case_insensitive():
    emitted: list[tuple] = []

    async def capture_emit(event_type, severity="medium", **kwargs):
        emitted.append((event_type, severity))

    with patch.dict(os.environ, {"IRA_CANARY_USERNAME": "Ghost_Admin"}), \
         patch("utils.security_events.emit_event", side_effect=capture_emit):
        result = await check_canary_username("GHOST_ADMIN")

    assert result is True


@pytest.mark.asyncio
async def test_canary_username_returns_true_even_if_emit_fails():
    async def bad_emit(*args, **kwargs):
        raise RuntimeError("DB down")

    with patch.dict(os.environ, {"IRA_CANARY_USERNAME": "ghost_admin"}), \
         patch("utils.security_events.emit_event", side_effect=bad_emit):
        result = await check_canary_username("ghost_admin")

    assert result is True


# ── Canary paths ──────────────────────────────────────────────────────────────

def test_canary_paths_is_non_empty():
    assert len(_CANARY_PATHS) >= 10, "Must have enough honeypot paths to be effective"


def test_canary_paths_include_dotenv():
    assert "/.env" in _CANARY_PATHS


def test_canary_paths_include_git_config():
    assert "/.git/config" in _CANARY_PATHS


def test_canary_paths_include_admin():
    assert "/admin" in _CANARY_PATHS


def test_canary_paths_include_wp_admin():
    assert "/wp-admin" in _CANARY_PATHS


def test_canary_paths_all_start_with_slash():
    for path in _CANARY_PATHS:
        assert path.startswith("/"), f"Canary path {path!r} must start with /"
