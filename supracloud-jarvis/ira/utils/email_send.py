"""
ira/utils/email_send.py — fail-soft outbound email for the email-with-approval action.

send_email() NEVER raises: if SMTP isn't configured it returns a clear
"not configured" result, and any SMTP error is returned as a soft "error" result —
so a chat turn is never broken by the mail server. Actually sending is gated by the
approval guardrail at the route layer (owner + explicit confirmation).
"""
from __future__ import annotations

import asyncio
import html
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from actions import is_configured, not_configured_message
from config import get_settings


def _send_sync(to: str, subject: str, body: str, cfg) -> None:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = cfg.smtp_user
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))
    html_body = (
        f'<html><body><div style="font-family:sans-serif;white-space:pre-wrap;">'
        f"{html.escape(body)}</div></body></html>"
    )
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port) as server:
        server.starttls()
        if cfg.smtp_user:
            server.login(cfg.smtp_user, cfg.smtp_password)
        server.send_message(msg)


async def send_email(*, to: str, subject: str, body: str, cfg=None) -> dict:
    """Send an email, failing soft. Returns a status dict; never raises."""
    cfg = cfg or get_settings()
    if not is_configured("email", cfg):
        return {"status": "not_configured", "message": not_configured_message("email")}
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _send_sync, to, subject, body, cfg)
    except Exception as exc:  # noqa: BLE001 — fail soft, never break the chat
        return {"status": "error", "message": f"Email send failed: {exc}"}
    return {"status": "sent", "to": to, "subject": subject}


__all__ = ["send_email"]
