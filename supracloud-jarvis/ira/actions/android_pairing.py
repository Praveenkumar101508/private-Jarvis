"""
ira/actions/android_pairing.py — hardened device pairing (CVE-2026-10216 fix).

droidclaw's pairing `claim` endpoint (server/src/routes/pairing.ts) is the subject
of CVE-2026-10216 (CWE-307, improper restriction of excessive authentication
attempts): it is PUBLIC, network-exposed via a tunnel, and rate-limits only by the
*spoofable* `x-forwarded-for` / `x-real-ip` header — so an attacker can brute-force
the 6-digit pairing code by rotating that header.

We do NOT run their server. If IRA ever exposes a pairing/companion endpoint, this
module is the only sanctioned path, and it closes the vulnerability:

  1. LOOPBACK ONLY — `assert_loopback()` refuses any non-loopback host, so the
     endpoint can never be bound to the LAN or a public tunnel. This removes the
     remote attack vector entirely.
  2. NON-SPOOFABLE RATE LIMIT — because it is loopback-only, attempts are counted
     against a fixed local key (not a client-supplied IP header), so the cap
     actually holds. A strict per-window attempt limit throttles brute force.

Pure, dependency-free, and fully unit-testable.
"""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field
from typing import Callable

_LOOPBACK_NAMES = {"localhost"}


class LoopbackOnlyError(ValueError):
    """Raised when a pairing service is asked to bind/serve a non-loopback host."""


def is_loopback(host: str) -> bool:
    h = (host or "").strip().lower()
    if h in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def assert_loopback(host: str) -> None:
    """Guard: refuse anything that isn't a loopback host (LAN/public/0.0.0.0)."""
    if not is_loopback(host):
        raise LoopbackOnlyError(
            f"pairing must bind to loopback only (got {host!r}); "
            "exposing it on the LAN/tunnel re-opens CVE-2026-10216"
        )


@dataclass
class RateLimiter:
    """Fixed-window attempt limiter keyed by a non-spoofable local key."""
    max_attempts: int = 5
    window_s: float = 60.0
    now: Callable[[], float] = None  # injectable clock; defaults to time.monotonic
    _state: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.now is None:
            import time
            self.now = time.monotonic

    def allow(self, key: str = "local") -> bool:
        """Record an attempt; return False once the window cap is exceeded."""
        t = self.now()
        entry = self._state.get(key)
        if entry is None or t > entry["reset_at"]:
            self._state[key] = {"count": 1, "reset_at": t + self.window_s}
            return True
        entry["count"] += 1
        return entry["count"] <= self.max_attempts


@dataclass
class PairingGuard:
    """Loopback-only, rate-limited pairing claim — the CVE-2026-10216-safe path."""
    max_attempts: int = 5
    window_s: float = 60.0
    _limiter: RateLimiter = None

    def __post_init__(self):
        if self._limiter is None:
            self._limiter = RateLimiter(max_attempts=self.max_attempts, window_s=self.window_s)

    def claim(self, code: str, *, host: str, validate: Callable[[str], bool]) -> dict:
        """Attempt to claim a pairing code from `host`.

        Order matters: refuse non-loopback callers first, then rate-limit, then
        validate. `validate(code)` is supplied by the caller (e.g. a DB lookup).
        """
        try:
            assert_loopback(host)
        except LoopbackOnlyError as exc:
            return {"status": "refused", "reason": str(exc)}

        if not self._limiter.allow("pairing"):
            return {"status": "rate_limited", "reason": "too many attempts; try again later"}

        if not (isinstance(code, str) and code.isdigit() and len(code) == 6):
            return {"status": "invalid", "reason": "code must be 6 digits"}

        if not validate(code):
            return {"status": "invalid", "reason": "invalid or expired code"}

        return {"status": "paired"}


__all__ = ["is_loopback", "assert_loopback", "LoopbackOnlyError", "RateLimiter", "PairingGuard"]
