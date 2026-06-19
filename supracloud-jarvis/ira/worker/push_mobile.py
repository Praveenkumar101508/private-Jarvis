"""worker/push_mobile.py — Expo push notifications for the IRA mobile app (#3).

The mobile-specific server capability: register a phone's Expo push token, and
deliver "task done" / alert notifications to it. This is an additional channel for
worker.notifier.notify(), mirroring the Telegram path. The app reaches IRA over a
private Tailscale mesh (no public exposure) and authenticates with the existing
JWT; this module only handles the device registry + the outbound push.

OFF by default (IRA_MOBILE_PUSH_ENABLED). Fully fail-soft: a push failure never
breaks a notification. Tokens are kept in Redis (re-registered on app launch).

Expo push API: https://docs.expo.dev/push-notifications/sending-notifications/
"""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from utils.redis_client import get_redis

logger = logging.getLogger("ira.push.mobile")

_DEVICES_KEY = "ira:mobile:devices"
_EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"
_BATCH = 100  # Expo accepts up to 100 messages per request

# ExponentPushToken[...] / ExpoPushToken[...]
_TOKEN_RE = re.compile(r"^Expo(?:nent)?PushToken\[[A-Za-z0-9_\-]+\]$")


def mobile_push_enabled() -> bool:
    return os.getenv("IRA_MOBILE_PUSH_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def is_valid_token(token: str) -> bool:
    return bool(token) and bool(_TOKEN_RE.match(token.strip()))


# ── Device registry (Redis set) ──────────────────────────────────────────────

async def register_device(token: str, platform: Optional[str] = None) -> None:
    await get_redis().sadd(_DEVICES_KEY, token.strip())
    logger.info("Registered mobile device (platform=%s)", platform or "?")


async def unregister_device(token: str) -> None:
    await get_redis().srem(_DEVICES_KEY, token.strip())


async def list_devices() -> list[str]:
    members = await get_redis().smembers(_DEVICES_KEY)
    return sorted(
        (m.decode() if isinstance(m, (bytes, bytearray)) else str(m)) for m in (members or [])
    )


# ── Push delivery ─────────────────────────────────────────────────────────────

def _expo_priority(priority: str) -> str:
    return "high" if priority in ("warning", "critical") else "default"


async def _post_expo(messages: list[dict]) -> None:
    """POST one batch of messages to the Expo push service (lazy httpx import)."""
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(_EXPO_PUSH_URL, json=messages)
        resp.raise_for_status()


async def send_push(title: str, body: str, *, priority: str = "info",
                    data: Optional[dict] = None) -> int:
    """Send a push to every registered device. Returns the number of messages
    dispatched. No-op (0) when disabled or no devices. Fail-soft per batch."""
    if not mobile_push_enabled():
        return 0
    tokens = await list_devices()
    if not tokens:
        return 0
    expo_priority = _expo_priority(priority)
    messages = [
        {"to": t, "title": title, "body": body, "priority": expo_priority, "data": data or {}}
        for t in tokens
    ]
    sent = 0
    for i in range(0, len(messages), _BATCH):
        batch = messages[i:i + _BATCH]
        try:
            await _post_expo(batch)
            sent += len(batch)
        except Exception as exc:  # noqa: BLE001 - a push failure must never break notify()
            logger.warning("Expo push batch failed (non-fatal): %s", exc)
    return sent


__all__ = [
    "mobile_push_enabled", "is_valid_token",
    "register_device", "unregister_device", "list_devices", "send_push",
]
