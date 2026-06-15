"""
IRA Bodyguard — Active Security Tools.

  scan_threats()            — inspect active network connections for external IPs
  initiate_lockdown()       — persist lockdown + Telegram confirmation
  lift_lockdown()           — remove lockdown state + notify
  dispatch_secure_message() — route a voice message directly to Telegram

Lockdown state is persisted in the monitor_state table so it survives container
restarts (unlike a module-level variable).
"""

from __future__ import annotations

import asyncio
import logging
import socket
from datetime import datetime, timezone

import psutil

from utils.db import acquire
from worker.notifier import notify

logger = logging.getLogger("ira.security_tools")

# ── Private IP helpers ────────────────────────────────────────────────────────

_PRIVATE_PREFIXES = (
    "10.", "172.16.", "172.17.", "172.18.", "172.19.", "172.20.",
    "172.21.", "172.22.", "172.23.", "172.24.", "172.25.", "172.26.",
    "172.27.", "172.28.", "172.29.", "172.30.", "172.31.",
    "192.168.", "127.", "::1", "fe80:",
)


def _is_external(ip: str) -> bool:
    return bool(ip) and not any(ip.startswith(p) for p in _PRIVATE_PREFIXES)


# ── Lockdown state (Redis-cached, DB-persisted) ───────────────────────────────
#
# Fix #33: the original implementation used a module-level `_lockdown_cache`
# variable that was process-local. With multi-worker deployments (uvicorn
# --workers N), worker A could set lockdown=True while worker B retained
# the old False in its own memory. Now Redis is the shared source of truth,
# with the DB as the durable persistence layer.

_REDIS_LOCKDOWN_KEY = "ira:lockdown_active"


async def get_lockdown_state() -> bool:
    """
    Read lockdown state.

    Order of preference:
      1. Redis cache (fast, shared across all workers in a pod)
      2. DB fallback (for cold-start before Redis write, or Redis outage)
    """
    # 1. Try Redis first
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        val = await redis.get(_REDIS_LOCKDOWN_KEY)
        if val is not None:
            # Fix P16: Redis client has decode_responses=True so val is always str;
            # the dead b"1" bytes branch has been removed.
            return val == "1"
    except Exception as e:
        logger.debug(f"Redis lockdown read failed (falling back to DB): {e}")

    # 2. Fall back to DB and backfill Redis
    try:
        async with acquire() as db:
            row = await db.fetchrow(
                "SELECT value FROM monitor_state WHERE key='lockdown_active'"
            )
            state = row is not None and row["value"] == "1"
        # Backfill Redis so subsequent calls are fast
        try:
            from utils.redis_client import get_redis
            redis = get_redis()
            await redis.set(_REDIS_LOCKDOWN_KEY, "1" if state else "0")
        except Exception:
            pass
        return state
    except Exception:
        return False


async def _set_lockdown_db(active: bool) -> None:
    """Write lockdown state to Redis (immediate, shared) and DB (durable)."""
    value = "1" if active else "0"

    # 1. Update Redis first — all workers see the change instantly
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        await redis.set(_REDIS_LOCKDOWN_KEY, value)
    except Exception as e:
        logger.warning(f"Failed to update lockdown state in Redis: {e}")

    # 2. Persist to DB for durability across container restarts
    try:
        async with acquire() as db:
            await db.execute(
                """INSERT INTO monitor_state (key, value)
                   VALUES ('lockdown_active', $1)
                   ON CONFLICT (key) DO UPDATE SET value=$1, updated_at=NOW()""",
                value,
            )
    except Exception as e:
        logger.warning(f"Failed to persist lockdown state to DB: {e}")


# ── Tool 1: Scan Threats ──────────────────────────────────────────────────────

async def scan_threats() -> dict:
    """Scan all active TCP/UDP connections for unusual external IPs."""
    loop = asyncio.get_running_loop()  # Fix L3: get_event_loop() deprecated in Python 3.10+
    raw_connections = await loop.run_in_executor(None, psutil.net_connections, "inet")

    external: list[dict] = []
    for conn in raw_connections:
        if not (conn.raddr and _is_external(conn.raddr.ip)):
            continue
        try:
            hostname = await loop.run_in_executor(None, socket.getfqdn, conn.raddr.ip)
        except Exception:
            hostname = conn.raddr.ip

        external.append({
            "remote_ip": conn.raddr.ip,
            "remote_port": conn.raddr.port,
            "hostname": hostname,
            "local_port": conn.laddr.port if conn.laddr else None,
            "status": conn.status,
            "pid": conn.pid,
        })

    unique_ips = list({c["remote_ip"] for c in external})

    threat_level = "CLEAR"
    if len(unique_ips) > 20:
        threat_level = "HIGH"
    elif len(unique_ips) > 5:
        threat_level = "MEDIUM"
    elif unique_ips:
        threat_level = "LOW"

    result = {
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "external_connections": external,
        "unique_external_ips": unique_ips,
        "total_external": len(external),
        "threat_level": threat_level,
    }

    if threat_level in ("HIGH", "MEDIUM"):
        ip_summary = ", ".join(unique_ips[:10])
        severity = "high" if threat_level == "HIGH" else "medium"
        try:
            async with acquire() as db:
                await db.execute(
                    """INSERT INTO security_events (severity, event_type, description)
                       VALUES ($1, 'network_scan_alert', $2)""",
                    severity,
                    f"Network scan: {len(external)} external connections from {len(unique_ips)} IPs — {ip_summary}",
                )
        except Exception as e:
            logger.warning(f"DB write failed for scan_threats: {e}")

    logger.info(f"scan_threats complete — {len(external)} external connections, level={threat_level}")
    return result


# ── Tool 2: Initiate Lockdown ─────────────────────────────────────────────────

async def initiate_lockdown(reason: str = "voice command") -> dict:
    """
    Engage lockdown mode:
      1. Persists LOCKDOWN=1 to monitor_state (survives restarts)
      2. Writes a CRITICAL event to security_events
      3. Sends Telegram alert to owner
    """
    await _set_lockdown_db(True)
    timestamp = datetime.now(timezone.utc).isoformat()

    try:
        async with acquire() as db:
            await db.execute(
                """INSERT INTO security_events (severity, event_type, description)
                   VALUES ('critical', 'lockdown_initiated', $1)""",
                f"LOCKDOWN initiated at {timestamp}. Reason: {reason}",
            )
    except Exception as e:
        logger.warning(f"DB write failed for lockdown: {e}")

    from config import get_settings
    owner_name = get_settings().owner_name
    await notify(
        "🔒 LOCKDOWN INITIATED",
        f"{owner_name}, IRA has engaged lockdown mode.\n\n"
        f"*Reason:* {reason}\n"
        f"*Time:* {timestamp}\n\n"
        f"Say _\"IRA, lift lockdown\"_ to restore normal operations.",
        category="security",
        priority="critical",
    )

    logger.critical(f"LOCKDOWN INITIATED — reason: {reason}")
    return {
        "status": "lockdown_active",
        "reason": reason,
        "timestamp": timestamp,
        "message": "Lockdown engaged. Telegram alert sent to your phone.",
    }


async def lift_lockdown() -> dict:
    """Deactivate lockdown mode and notify owner."""
    await _set_lockdown_db(False)
    timestamp = datetime.now(timezone.utc).isoformat()

    from config import get_settings
    owner_name = get_settings().owner_name
    await notify(
        "🔓 Lockdown Lifted",
        f"{owner_name}, IRA lockdown has been lifted at {timestamp}.\nReturning to normal monitoring.",
        category="security",
        priority="warning",
    )
    logger.info("Lockdown lifted")
    return {"status": "normal", "timestamp": timestamp}


# ── Tool 3: Dispatch Secure Message ──────────────────────────────────────────

async def dispatch_secure_message(message: str) -> dict:
    """Send a voice-dictated message directly to the owner's Telegram."""
    from config import get_settings
    cfg = get_settings()

    if not cfg.telegram_bot_token or not cfg.telegram_chat_id:
        return {"status": "error", "message": "Telegram is not configured in .env"}

    timestamp = datetime.now(timezone.utc).strftime("%H:%M UTC")

    try:
        import html
        import httpx
        text = (
            f"📨 <b>Secure Message via IRA</b> [{html.escape(timestamp)}]\n\n"
            f"{html.escape(message)}"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": cfg.telegram_chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
            resp.raise_for_status()

        logger.info(f"Secure message dispatched to Telegram at {timestamp}")
        return {"status": "sent", "timestamp": timestamp}
    except Exception as e:
        logger.error(f"dispatch_secure_message failed: {e}")
        return {"status": "error", "message": str(e)}
