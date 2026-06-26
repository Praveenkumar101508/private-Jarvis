"""Phase 4 — sensitive tools enforce owner authorization at the tool boundary.

Access control used to live only in a keyword/regex check on the request text
(is_restricted_domain / enforce_owner_gate). A paraphrase could evade that, and the
sensitive tools did not independently re-check identity. These tests call each tool
DIRECTLY with the classifier bypassed and assert it fails CLOSED for a non-owner.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio

import pytest

from actions.email_triage import fetch_recent
from actions import calendar_dav
from utils.security_tools import (
    scan_threats, initiate_lockdown, lift_lockdown, dispatch_secure_message,
)


def _run(coro):
    return asyncio.run(coro)


# ── Each tool refuses a non-owner (default is_owner=False ⇒ fail closed) ───────

def test_email_triage_refuses_non_owner():
    out = _run(fetch_recent())                       # no is_owner ⇒ False
    assert out["status"] == "forbidden"
    out2 = _run(fetch_recent(is_owner=False))
    assert out2["status"] == "forbidden"


def test_calendar_list_refuses_non_owner():
    out = _run(calendar_dav.list_events(is_owner=False))
    assert out["status"] == "forbidden"


def test_calendar_create_refuses_non_owner():
    out = _run(calendar_dav.create_event(summary="x", start="2026-06-17T09:00:00Z", is_owner=False))
    assert out["status"] == "forbidden"


def test_calendar_delete_refuses_non_owner():
    out = _run(calendar_dav.delete_event("any@ira", is_owner=False))
    assert out["status"] == "forbidden"


@pytest.mark.parametrize("call", [
    lambda: scan_threats(is_owner=False),
    lambda: initiate_lockdown(reason="t", is_owner=False),
    lambda: lift_lockdown(is_owner=False),
    lambda: dispatch_secure_message("hi", is_owner=False),
])
def test_security_tools_refuse_non_owner(call):
    out = _run(call())
    assert out["status"] == "forbidden"
    assert "owner" in out["message"].lower()


def test_defaults_fail_closed_without_is_owner_kwarg():
    """Omitting is_owner entirely must refuse — the default is False, not True."""
    assert _run(scan_threats())["status"] == "forbidden"
    assert _run(lift_lockdown())["status"] == "forbidden"
    assert _run(calendar_dav.list_events())["status"] == "forbidden"
