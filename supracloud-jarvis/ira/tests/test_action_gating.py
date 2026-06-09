"""Prompt 2.2 — high-stakes actions require the verified owner AND confirmation.

Acceptance: a non-owner is blocked, and an unconfirmed action does nothing. Verified
against the calendar create endpoint (representative) plus a file-delete owner check.
"""
import os

for _k in ("IRA_SECRET_KEY", "IRA_ADMIN_PASSWORD", "POSTGRES_PASSWORD", "REDIS_PASSWORD", "VLLM_API_KEY"):
    os.environ.setdefault(_k, "test-placeholder")

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

import api.routes.calendar as calmod
from api.routes.calendar import create_event, CreateEventRequest
from api.routes.files import delete_file


class _Cfg:
    ira_admin_username = "owner"


def _body(**kw):
    base = dict(event_type_id=1, start="2026-06-01T10:00:00Z", name="X", email="x@y.com")
    base.update(kw)
    return CreateEventRequest(**base)


def test_non_owner_is_blocked(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Cfg())
    create = AsyncMock(return_value={"id": "evt1"})
    monkeypatch.setattr(calmod, "create_calcom_event", create)

    with pytest.raises(HTTPException) as ei:
        asyncio.run(create_event(_body(), _user="randomguy"))
    assert ei.value.status_code == 403
    assert not create.called          # the side effect never ran for a non-owner


def test_owner_unconfirmed_does_nothing(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Cfg())
    create = AsyncMock(return_value={"id": "evt1"})
    monkeypatch.setattr(calmod, "create_calcom_event", create)

    out = asyncio.run(create_event(_body(), _user="owner"))
    assert out["status"] == "confirmation_required"
    assert out["token"]
    assert not create.called          # a draft, not a send


def test_owner_confirmed_executes(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Cfg())
    create = AsyncMock(return_value={"id": "evt1", "ok": True})
    monkeypatch.setattr(calmod, "create_calcom_event", create)

    draft = asyncio.run(create_event(_body(), _user="owner"))
    result = asyncio.run(create_event(_body(confirm_token=draft["token"]), _user="owner"))

    assert create.called
    assert result == {"id": "evt1", "ok": True}


def test_file_delete_blocks_non_owner(monkeypatch):
    monkeypatch.setattr("api.middleware.auth.get_settings", lambda: _Cfg())
    with pytest.raises(HTTPException) as ei:
        asyncio.run(delete_file(file_id="f1", confirm_token=None, _user="randomguy"))
    assert ei.value.status_code == 403
