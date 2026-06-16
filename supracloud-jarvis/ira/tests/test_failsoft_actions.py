"""Prompt 2.3 — the v1 action set degrades gracefully when a dependency is absent.

Covers each action via the config-status registry (no key -> clear "not configured",
never throws), plus concrete fail-soft for the two external-dependency actions:
calendar (Cal.com) and email-with-approval (SMTP).
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
from unittest.mock import AsyncMock

from actions import action_status, is_configured, not_configured_message, V1_ACTIONS
import api.routes.calendar as calmod
from api.routes.calendar import create_event, CreateEventRequest
from api.routes.actions import send_email_action, EmailRequest


class _NoKeys:
    ira_admin_username = "owner"
    calcom_api_key = ""
    smtp_host = ""
    smtp_port = 587
    smtp_user = ""
    smtp_password = ""
    imap_host = ""
    caldav_url = ""


class _WithKeys:
    ira_admin_username = "owner"
    calcom_api_key = "cal-key"
    smtp_host = "smtp.example.com"
    smtp_port = 587
    smtp_user = "u@example.com"
    smtp_password = "pw"
    imap_host = "imap.example.com"
    caldav_url = "https://dav.example.com"


# ── registry: a status per action, never throwing ────────────────────────────

def test_v1_action_set_is_defined():
    assert set(V1_ACTIONS) == {
        "tasks", "reminders", "briefings", "files", "notes",
        "calendar", "calendar_dav", "email", "email_triage",
    }


def test_status_failsoft_when_no_keys():
    st = action_status(_NoKeys())
    # Local actions need no external key -> always configured.
    for local in ("tasks", "reminders", "briefings", "files", "notes"):
        assert st[local]["configured"] is True
    # External-dep actions report a clear "not configured" message.
    for ext in ("calendar", "calendar_dav", "email", "email_triage"):
        assert st[ext]["configured"] is False
        assert "not configured" in st[ext]["message"]


def test_status_configured_with_keys():
    st = action_status(_WithKeys())
    assert st["calendar"]["configured"] is True
    assert st["email"]["configured"] is True


# ── calendar fail-soft (Cal.com absent) ──────────────────────────────────────

def test_calendar_create_failsoft_when_unconfigured(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _NoKeys())
    monkeypatch.setattr("actions.get_settings", lambda: _NoKeys())
    create = AsyncMock(return_value=None)
    monkeypatch.setattr(calmod, "create_calcom_event", create)

    body = dict(event_type_id=1, start="2026-06-01T10:00:00Z", name="N", email="e@x.com")
    draft = asyncio.run(create_event(CreateEventRequest(**body), _user="owner"))
    res = asyncio.run(create_event(CreateEventRequest(confirm_token=draft["token"], **body), _user="owner"))

    assert res["status"] == "not_configured"      # clear message, no exception


# ── email-with-approval fail-soft + send ─────────────────────────────────────

def test_email_failsoft_when_smtp_absent(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _NoKeys())
    monkeypatch.setattr("utils.email_send.get_settings", lambda: _NoKeys())
    sent = []
    monkeypatch.setattr("utils.email_send._send_sync", lambda *a: sent.append(1))

    draft = asyncio.run(send_email_action(EmailRequest(to="a@b.com", subject="s", body="b"), _user="owner"))
    res = asyncio.run(send_email_action(
        EmailRequest(to="a@b.com", subject="s", body="b", confirm_token=draft["token"]), _user="owner"))

    assert res["status"] == "not_configured"
    assert sent == []                              # nothing was sent


def test_email_sends_after_confirm_when_configured(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _WithKeys())
    monkeypatch.setattr("utils.email_send.get_settings", lambda: _WithKeys())
    sent = []
    monkeypatch.setattr("utils.email_send._send_sync",
                        lambda to, subject, body, cfg: sent.append((to, subject)))

    draft = asyncio.run(send_email_action(EmailRequest(to="a@b.com", subject="hi", body="x"), _user="owner"))
    assert draft["status"] == "confirmation_required"
    assert sent == []                              # unconfirmed sends nothing

    res = asyncio.run(send_email_action(
        EmailRequest(to="a@b.com", subject="hi", body="x", confirm_token=draft["token"]), _user="owner"))
    assert res["status"] == "sent"
    assert sent == [("a@b.com", "hi")]
