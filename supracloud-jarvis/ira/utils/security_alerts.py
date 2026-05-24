"""
IRA Security Alerts — synchronous Telegram push utility.

Designed to be called from threads, signal handlers, and blocking watchdog
scripts where async is unavailable. Uses `requests` (not httpx) so it works
in any context without an event loop.

Usage:
    from utils.security_alerts import send_alert
    send_alert("🚨 Unauthorized login attempt on port 22")
"""

from __future__ import annotations

import html as _html
import logging
import os
from typing import Literal

import requests

logger = logging.getLogger("ira.security_alerts")

Priority = Literal["info", "warning", "critical"]

_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}


def send_alert(
    message: str,
    *,
    priority: Priority = "warning",
) -> bool:
    """
    Send a Telegram message to the owner's chat.

    Returns True on success, False on failure (never raises).
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.debug("Telegram not configured — alert not sent")
        return False

    emoji = _EMOJI.get(priority, "⚠️")
    text = f"{emoji} <b>IRA Security Alert</b>\n\n{_html.escape(message)}"

    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if not resp.ok:
            logger.warning(f"Telegram API error {resp.status_code}: {resp.text[:200]}")
        return resp.ok
    except Exception as e:
        logger.warning(f"Telegram delivery failed: {e}")
        return False
