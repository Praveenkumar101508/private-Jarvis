"""P5.1 — Real-time security event emitter.

Provides emit_event() — a lightweight async writer that:
  1. Persists every event to the security_events table (fail-soft on DB error).
  2. For HIGH / CRITICAL events, immediately triggers a Telegram push via
     utils.security_alerts.send_alert() (dispatched to a thread so the
     calling coroutine is never blocked by network I/O).

Call from async routes / middleware with either:
  - await emit_event(...)           — waits for the DB write before continuing
  - asyncio.create_task(emit_event(...))  — fully fire-and-forget
"""
from __future__ import annotations

import asyncio
import logging
from typing import Literal

logger = logging.getLogger("ira.security_events")

Severity = Literal["critical", "high", "medium", "low", "info"]

_ALERT_SEVERITIES = frozenset(("critical", "high"))


async def emit_event(
    event_type: str,
    severity: Severity = "medium",
    *,
    source_ip: str | None = None,
    description: str = "",
    raw_log: str = "",
) -> None:
    """Emit one security event: persist to DB and alert via Telegram if high/critical.

    Fail-soft: DB or Telegram failures are logged as warnings, never raised.
    This function is safe to call from any async context including generators.
    """
    # 1. Persist to security_events
    try:
        from utils.db import acquire
        async with acquire() as conn:
            await conn.execute(
                """INSERT INTO security_events
                   (severity, event_type, source_ip, description, raw_log)
                   VALUES ($1, $2, $3::inet, $4, $5)""",
                severity,
                event_type,
                source_ip or None,
                description[:1000],
                raw_log[:500],
            )
    except Exception as exc:
        logger.warning("emit_event: DB write failed (fail-soft): %s", exc)

    # 2. Telegram push for high/critical
    if severity in _ALERT_SEVERITIES:
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _do_telegram_push, event_type, severity, description)
        except RuntimeError:
            # No running event loop (sync test context)
            _do_telegram_push(event_type, severity, description)


def _do_telegram_push(event_type: str, severity: str, description: str) -> None:
    """Sync Telegram push — intended to run in an executor thread."""
    try:
        from utils.security_alerts import send_alert
        priority: Literal["info", "warning", "critical"] = (
            "critical" if severity == "critical" else "warning"
        )
        send_alert(
            f"[{event_type.upper().replace('_', ' ')}]\n{description}",
            priority=priority,
        )
    except Exception as exc:
        logger.warning("emit_event: Telegram push failed: %s", exc)


def classify_guard_refusal(refusal: str, *, has_url: bool = False) -> tuple[str, Severity]:
    """Map a guard_outbound() refusal reason to (event_type, severity).

    SSRF (private host)          → HIGH
    Credential/secret smuggling  → CRITICAL
    Local file path in query     → HIGH
    Anything else                → MEDIUM
    """
    reason = refusal.lower()
    if "private" in reason or "internal" in reason or "loopback" in reason or has_url:
        if "private" in reason or "internal" in reason or "loopback" in reason:
            return "ssrf_block", "high"
    if "secret" in reason or "credential" in reason or "key" in reason:
        return "credential_exfiltration_attempt", "critical"
    if "local file" in reason or "file path" in reason or "file://" in reason:
        return "local_path_exfiltration_attempt", "high"
    # Fallback for the has_url=True SSRF path
    if has_url:
        return "ssrf_block", "high"
    return "outbound_request_blocked", "medium"


__all__ = ["emit_event", "classify_guard_refusal", "Severity"]
