"""P6.2 — Bounded automated security playbooks.

Exactly three automated security-response actions, invokable only through
run_playbook() which validates against a fixed ALLOWED_ACTIONS allowlist.

Actions:
  rotate_tokens(username)               Bump the per-user token version in Redis,
                                        immediately invalidating every outstanding
                                        access token for that account.

  block_ip(ip_address, ttl_seconds)     Add the IP to the Redis blocklist
                                        (ira:blocked_ip:{ip}) for ttl_seconds.
                                        The auth middleware checks this key on
                                        every request and returns 403 if set.

  snapshot_logs(label)                  Read recent security_events from the DB
                                        and write them to a timestamped JSON file
                                        in IRA_LOG_SNAPSHOT_DIR for forensics.

Safety invariants:
  - Only actions in ALLOWED_ACTIONS are executable — anything else is refused
    with a logged warning and no side-effect.
  - Every action call is written to security_events as 'playbook_action' (MEDIUM)
    before the action executes, creating an immutable audit trail.
  - All actions are fail-soft: infrastructure errors are logged as warnings and
    return False; no action ever raises to its caller.
  - No destructive operations: no `rm`, no `git`, no service kill, no DROP TABLE.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("ira.playbooks")

# ── Allowlist ─────────────────────────────────────────────────────────────────

ALLOWED_ACTIONS: frozenset[str] = frozenset({"rotate_tokens", "block_ip", "snapshot_logs"})

_BLOCKED_IP_PREFIX = "ira:blocked_ip:"
_DEFAULT_BLOCK_TTL = 3600          # 1 hour
_MAX_BLOCK_TTL = 86400 * 7         # 7 days cap
_DEFAULT_SNAPSHOT_DIR = "/tmp/ira-logs"


# ── Gatekeeper ────────────────────────────────────────────────────────────────

async def run_playbook(action: str, **kwargs: Any) -> bool:
    """Execute a bounded playbook action by name.

    Returns True on success, False on failure or unknown action.
    Unknown actions are logged as a WARNING and immediately refused.
    Every execution (successful or not) is written to security_events.
    """
    if action not in ALLOWED_ACTIONS:
        logger.warning(
            "run_playbook: refused unknown action %r (allowed: %s)",
            action, ", ".join(sorted(ALLOWED_ACTIONS)),
        )
        return False

    # Audit log BEFORE executing the action
    await _audit(action, kwargs, outcome="initiated")

    try:
        result = await _dispatch(action, **kwargs)
        await _audit(action, kwargs, outcome="success" if result else "failed")
        return result
    except Exception as exc:
        logger.warning("run_playbook: %r raised unexpectedly: %s", action, exc)
        await _audit(action, kwargs, outcome=f"error: {exc!s:.80}")
        return False


async def _dispatch(action: str, **kwargs: Any) -> bool:
    if action == "rotate_tokens":
        return await rotate_tokens(**kwargs)
    if action == "block_ip":
        return await block_ip(**kwargs)
    if action == "snapshot_logs":
        return await snapshot_logs(**kwargs)
    return False  # unreachable but satisfies type checker


async def _audit(action: str, params: dict, outcome: str) -> None:
    """Write one row to security_events as the playbook audit trail."""
    description = (
        f"Playbook '{action}' {outcome}. "
        f"Params: {json.dumps({k: str(v)[:60] for k, v in params.items()})}"
    )
    try:
        from utils.security_events import emit_event
        await emit_event("playbook_action", "medium", description=description[:1000])
    except Exception as exc:
        logger.warning("playbook audit write failed: %s", exc)


# ── Action: rotate_tokens ─────────────────────────────────────────────────────

async def rotate_tokens(username: str) -> bool:
    """Bump the per-user token version, invalidating all outstanding access tokens.

    Uses the same Redis key as require_auth's version check so tokens already
    issued with an older `ver` claim are rejected immediately on next use.
    """
    if not username:
        logger.warning("rotate_tokens: empty username — skipping")
        return False
    try:
        from utils.redis_client import get_redis
        key = f"ira:token_ver:{username}"
        new_ver = await get_redis().incr(key)
        logger.info("rotate_tokens: invalidated all tokens for %r (ver now %d)", username, new_ver)
        return True
    except Exception as exc:
        logger.warning("rotate_tokens: Redis error for %r: %s", username, exc)
        return False


# ── Action: block_ip ──────────────────────────────────────────────────────────

async def block_ip(ip_address: str, ttl_seconds: int = _DEFAULT_BLOCK_TTL) -> bool:
    """Add ip_address to the Redis blocklist for ttl_seconds.

    The key ira:blocked_ip:{ip} is checked by the auth middleware on every
    request; any request from a blocked IP receives 403 immediately.
    TTL is capped at 7 days to prevent indefinite blocks from automated logic.
    """
    if not ip_address:
        logger.warning("block_ip: empty ip_address — skipping")
        return False
    ttl = min(int(ttl_seconds), _MAX_BLOCK_TTL)
    try:
        from utils.redis_client import get_redis
        key = f"{_BLOCKED_IP_PREFIX}{ip_address}"
        await get_redis().setex(key, ttl, "1")
        logger.info("block_ip: %s blocked for %ds (key: %s)", ip_address, ttl, key)
        return True
    except Exception as exc:
        logger.warning("block_ip: Redis error for %s: %s", ip_address, exc)
        return False


async def is_ip_blocked(ip_address: str) -> bool:
    """Check whether ip_address is on the Redis blocklist. Fail-open on error."""
    if not ip_address:
        return False
    try:
        from utils.redis_client import get_redis
        return bool(await get_redis().exists(f"{_BLOCKED_IP_PREFIX}{ip_address}"))
    except Exception as exc:
        logger.warning("is_ip_blocked: Redis error (fail-open): %s", exc)
        return False


# ── Action: snapshot_logs ─────────────────────────────────────────────────────

async def snapshot_logs(label: str = "manual") -> bool:
    """Dump recent security_events to a timestamped JSON file for forensics.

    Writes to IRA_LOG_SNAPSHOT_DIR (default /tmp/ira-logs). The file is
    named ira-security-snapshot-{label}-{timestamp}.json and contains the
    last 500 security events ordered newest-first.
    """
    snapshot_dir = Path(os.environ.get("IRA_LOG_SNAPSHOT_DIR", _DEFAULT_SNAPSHOT_DIR))
    try:
        snapshot_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("snapshot_logs: cannot create dir %s: %s", snapshot_dir, exc)
        return False

    try:
        from utils.db import acquire
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT severity, event_type, source_ip::text,
                          description, raw_log, resolved, created_at
                   FROM security_events
                   ORDER BY created_at DESC
                   LIMIT 500"""
            )
    except Exception as exc:
        logger.warning("snapshot_logs: DB read failed: %s", exc)
        return False

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:40]
    filename = snapshot_dir / f"ira-security-snapshot-{safe_label}-{ts}.json"

    payload = {
        "snapshot_label": label,
        "created_at": ts,
        "event_count": len(rows),
        "events": [
            {
                "severity": r["severity"],
                "event_type": r["event_type"],
                "source_ip": r["source_ip"],
                "description": r["description"],
                "raw_log": r["raw_log"],
                "resolved": r["resolved"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in rows
        ],
    }

    try:
        filename.write_text(json.dumps(payload, indent=2, default=str))
        logger.info("snapshot_logs: %d events written to %s", len(rows), filename)
        return True
    except OSError as exc:
        logger.warning("snapshot_logs: write failed: %s", exc)
        return False


__all__ = [
    "ALLOWED_ACTIONS",
    "run_playbook",
    "rotate_tokens",
    "block_ip",
    "snapshot_logs",
    "is_ip_blocked",
]
