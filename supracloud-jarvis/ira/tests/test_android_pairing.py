"""Phase 5 — CVE-2026-10216 mitigation: pairing is loopback-only and the rate
limit is enforced against a non-spoofable key."""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import pytest

from actions.android_pairing import (
    LoopbackOnlyError, PairingGuard, RateLimiter, assert_loopback, is_loopback,
)


# ── loopback-only guard (removes the remote attack vector) ───────────────────

def test_loopback_detection():
    for ok in ("127.0.0.1", "::1", "localhost", ""):
        assert is_loopback(ok) is True
    for bad in ("192.168.1.10", "10.0.0.5", "0.0.0.0", "8.8.8.8", "tunnel.droidclaw.ai"):
        assert is_loopback(bad) is False


def test_assert_loopback_refuses_non_loopback():
    assert_loopback("127.0.0.1")  # no raise
    with pytest.raises(LoopbackOnlyError):
        assert_loopback("192.168.1.50")


# ── non-spoofable rate limit ─────────────────────────────────────────────────

def test_rate_limiter_caps_attempts():
    t = {"v": 0.0}
    rl = RateLimiter(max_attempts=3, window_s=60, now=lambda: t["v"])
    assert [rl.allow("k") for _ in range(3)] == [True, True, True]
    assert rl.allow("k") is False           # 4th attempt blocked
    t["v"] = 61                              # window elapses
    assert rl.allow("k") is True             # resets


# ── end-to-end claim path ────────────────────────────────────────────────────

def test_claim_refuses_non_loopback_host():
    g = PairingGuard()
    out = g.claim("123456", host="192.168.0.9", validate=lambda c: True)
    assert out["status"] == "refused"
    assert "loopback" in out["reason"].lower()


def test_claim_throttles_brute_force_then_validates():
    t = {"v": 0.0}
    g = PairingGuard()
    g._limiter = RateLimiter(max_attempts=5, window_s=60, now=lambda: t["v"])

    # Five wrong attempts from loopback are allowed through to validation…
    for _ in range(5):
        r = g.claim("000000", host="127.0.0.1", validate=lambda c: False)
        assert r["status"] == "invalid"
    # …the sixth is rate-limited regardless of the code (brute force throttled).
    assert g.claim("123456", host="127.0.0.1", validate=lambda c: True)["status"] == "rate_limited"


def test_claim_rejects_bad_code_format():
    g = PairingGuard()
    assert g.claim("12ab", host="127.0.0.1", validate=lambda c: True)["status"] == "invalid"


def test_claim_succeeds_for_valid_code():
    g = PairingGuard()
    assert g.claim("654321", host="127.0.0.1", validate=lambda c: True)["status"] == "paired"
