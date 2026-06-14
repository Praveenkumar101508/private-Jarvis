"""P2.3 — Progressive account lockout backed by Redis.

Tracks failed login attempts per username and applies exponential backoff
culminating in a time-based lock after MAX_FAILURES attempts. Successful
login clears the counter. Timing is constant (bcrypt always runs in the
calling code) to prevent username enumeration.

Redis keys:
  ira:login_fails:{username}   — fail count, TTL = FAIL_WINDOW_SECONDS
  ira:login_lock:{username}    — lock marker, TTL = lock duration in seconds
"""

from __future__ import annotations

import logging
import math

logger = logging.getLogger(__name__)

# ── Defaults (overridable via config in future) ───────────────────────────────
MAX_FAILURES = 5           # lock after this many consecutive failures
FAIL_WINDOW_SECONDS = 900  # 15 min — sliding window for counting failures
BASE_LOCK_SECONDS = 900    # first lock = 15 min
MAX_LOCK_SECONDS = 86400   # cap at 24 h regardless of escalation

_FAIL_PREFIX = "ira:login_fails:"
_LOCK_PREFIX = "ira:login_lock:"


async def record_failure(username: str) -> tuple[int, bool]:
    """Increment the fail counter and lock the account if threshold reached.

    Returns (fail_count, is_now_locked).
    Fail-soft: if Redis is unavailable, returns (0, False) so login is never
    blocked solely due to Redis failure.
    """
    try:
        from utils.redis_client import get_redis
        r = get_redis()
        fail_key = f"{_FAIL_PREFIX}{username}"
        lock_key = f"{_LOCK_PREFIX}{username}"

        count = await r.incr(fail_key)
        # Reset the sliding window on each failure
        await r.expire(fail_key, FAIL_WINDOW_SECONDS)

        # P5.1: emit security event for every auth failure
        try:
            from utils.security_events import emit_event
            await emit_event(
                "login_failure",
                "medium",
                description=f"Login failure for '{username}': attempt {count}/{MAX_FAILURES}",
            )
        except Exception as se:
            logger.debug("emit_event failed (non-critical): %s", se)

        if count >= MAX_FAILURES:
            # Escalating lock: 15 min → 30 min → 60 min … capped at 24 h
            lock_ttl = min(
                int(BASE_LOCK_SECONDS * math.pow(2, (count - MAX_FAILURES))),
                MAX_LOCK_SECONDS,
            )
            await r.setex(lock_key, lock_ttl, "1")
            logger.warning(
                "Account locked for %s: %d failures → lock %ds", username, count, lock_ttl
            )
            # P5.1: emit HIGH event when account is actually locked
            try:
                from utils.security_events import emit_event
                await emit_event(
                    "account_locked",
                    "high",
                    description=(
                        f"Account '{username}' locked after {count} failures. "
                        f"Lock duration: {lock_ttl}s."
                    ),
                )
            except Exception as se:
                logger.debug("emit_event failed (non-critical): %s", se)
            return count, True

        return count, False

    except Exception as e:
        logger.warning("account_lockout.record_failure Redis error (fail-open): %s", e)
        return 0, False


async def is_locked(username: str) -> bool:
    """True if the account is currently locked out.

    Fail-soft: returns False on Redis error so a Redis outage doesn't
    permanently lock the owner out.
    """
    try:
        from utils.redis_client import get_redis
        return bool(await get_redis().exists(f"{_LOCK_PREFIX}{username}"))
    except Exception as e:
        logger.warning("account_lockout.is_locked Redis error (fail-open): %s", e)
        return False


async def clear_failures(username: str) -> None:
    """Clear fail counter and any lock on successful authentication."""
    try:
        from utils.redis_client import get_redis
        r = get_redis()
        await r.delete(f"{_FAIL_PREFIX}{username}", f"{_LOCK_PREFIX}{username}")
    except Exception as e:
        logger.warning("account_lockout.clear_failures Redis error: %s", e)


async def get_fail_count(username: str) -> int:
    """Current consecutive failure count (0 if not set or Redis unavailable)."""
    try:
        from utils.redis_client import get_redis
        v = await get_redis().get(f"{_FAIL_PREFIX}{username}")
        return int(v) if v else 0
    except Exception:
        return 0
