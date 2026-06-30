"""V2·Phase 3 — health-gate readiness logic (portable/health_check.py)."""
import sys
from pathlib import Path

_PORTABLE = Path(__file__).resolve().parents[3] / "portable"
sys.path.insert(0, str(_PORTABLE))

import health_check as hc  # noqa: E402


def test_evaluate_ok():
    ready, msg = hc.evaluate_health({"status": "ok", "services": {"postgres": {"status": "ok"}}})
    assert ready is True
    assert "ok" in msg


def test_evaluate_degraded_lists_broken_service():
    ready, msg = hc.evaluate_health({
        "status": "degraded",
        "services": {"postgres": {"status": "ok"}, "redis": {"status": "down"}},
    })
    assert ready is False
    assert "redis=down" in msg


def test_check_once_unreachable():
    def _boom(url, timeout):
        raise OSError("connection refused")

    ready, msg = hc.check_once("http://127.0.0.1:9", fetch=_boom)
    assert ready is False
    assert "unreachable" in msg


def test_wait_for_ready_polls_until_ok():
    calls = {"n": 0}

    def _fetch(url, timeout):
        calls["n"] += 1
        return {"status": "ok"} if calls["n"] >= 3 else {"status": "down", "services": {}}

    ready, msg = hc.wait_for_ready(
        total_timeout=100, interval=1, fetch=_fetch,
        sleep=lambda s: None, now=_fake_clock(),
    )
    assert ready is True
    assert calls["n"] == 3


def test_wait_for_ready_times_out():
    ready, msg = hc.wait_for_ready(
        total_timeout=5, interval=1,
        fetch=lambda u, t: {"status": "down", "services": {"redis": {"status": "down"}}},
        sleep=lambda s: None, now=_fake_clock(),
    )
    assert ready is False
    assert "redis=down" in msg


def _fake_clock():
    t = {"v": 0.0}

    def _now():
        t["v"] += 1.0
        return t["v"]

    return _now
