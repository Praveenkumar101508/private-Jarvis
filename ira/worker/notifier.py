"""
IRA Multi-Channel Notifier.

Delivers proactive alerts through all configured channels simultaneously:
  WebSocket  — real-time push to any connected browser/app client (always on)
  Telegram   — mobile push via bot (if TELEGRAM_BOT_TOKEN set)
  Email      — SMTP (if SMTP_HOST set)
  Redis      — internal pub/sub (always; other services can subscribe)

Usage:
    await notify("Security Alert", "3 failed SSH attempts from 1.2.3.4",
                 category="security", priority="high")
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Literal

import httpx

from config import get_settings
from utils.db import acquire
from utils.redis_client import get_redis

logger = logging.getLogger("ira.notifier")

Priority = Literal["info", "warning", "critical"]
Category = Literal["briefing", "security", "business", "reminder", "task", "system"]

# Redis channel name — WebSocket handler subscribes to this
REDIS_NOTIFY_CHANNEL = "ira:notifications"


# ── Core notify function ───────────────────────────────────────────────────────

async def notify(
    title: str,
    body: str,
    *,
    category: Category = "system",
    priority: Priority = "info",
    metadata: dict | None = None,
) -> str:
    """
    Send a notification via all configured channels.
    Returns the notification UUID for reference.
    """
    notif_id = str(uuid.uuid4())
    channels_sent: list[str] = []
    cfg = get_settings()

    payload = {
        "id": notif_id,
        "category": category,
        "title": title,
        "body": body,
        "priority": priority,
        "metadata": metadata or {},
    }

    # Always publish to Redis (WebSocket clients and internal subscribers)
    await _publish_redis(payload)
    channels_sent.append("websocket")

    # Telegram (if configured)
    if cfg.telegram_bot_token and cfg.telegram_chat_id:
        try:
            await _send_telegram(title, body, priority, cfg)
            channels_sent.append("telegram")
        except Exception as e:
            logger.warning(f"Telegram delivery failed: {e}")

    # Email (if configured) — only for warning/critical or briefings
    if cfg.smtp_host and cfg.smtp_user and (priority in ("warning", "critical") or category == "briefing"):
        try:
            await _send_email(title, body, category, cfg)
            channels_sent.append("email")
        except Exception as e:
            logger.warning(f"Email delivery failed: {e}")

    # Persist to notifications table
    await _persist(notif_id, category, title, body, priority, channels_sent, metadata or {})

    logger.info(f"Notification [{priority}] '{title}' → {channels_sent}")
    return notif_id


# ── Redis pub/sub ─────────────────────────────────────────────────────────────

async def _publish_redis(payload: dict) -> None:
    await get_redis().publish(REDIS_NOTIFY_CHANNEL, json.dumps(payload))


# ── Telegram ──────────────────────────────────────────────────────────────────

_PRIORITY_EMOJI = {"info": "ℹ️", "warning": "⚠️", "critical": "🚨"}

async def _send_telegram(title: str, body: str, priority: Priority, cfg) -> None:
    emoji = _PRIORITY_EMOJI.get(priority, "ℹ️")
    text = f"{emoji} *{title}*\n\n{body}"
    url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json={
            "chat_id": cfg.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        })
        resp.raise_for_status()


# ── Email (SMTP) ──────────────────────────────────────────────────────────────

async def _send_email(title: str, body: str, category: str, cfg) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _send_email_sync, title, body, category, cfg)


def _send_email_sync(title: str, body: str, category: str, cfg) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"[IRA] {title}"
    msg["From"] = cfg.smtp_user
    msg["To"] = cfg.smtp_to or cfg.smtp_user

    # Plain text
    msg.attach(MIMEText(body, "plain"))

    # Simple HTML version
    html = f"""<html><body>
    <h2 style="color:#1a1a2e;">IRA — {title}</h2>
    <div style="font-family:sans-serif;white-space:pre-wrap;">{body}</div>
    <hr><p style="color:#888;font-size:12px;">SupraCloud IRA — Private AI Assistant</p>
    </body></html>"""
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
        server.starttls()
        server.login(cfg.smtp_user, cfg.smtp_password)
        server.send_message(msg)


# ── Database persistence ──────────────────────────────────────────────────────

async def _persist(
    notif_id: str,
    category: str,
    title: str,
    body: str,
    priority: str,
    channels: list[str],
    metadata: dict,
) -> None:
    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO notifications
               (id, category, title, body, priority, channels_sent, metadata)
               VALUES ($1, $2, $3, $4, $5, $6::text[], $7)""",
            uuid.UUID(notif_id), category, title, body, priority, channels,
            json.dumps(metadata),
        )
