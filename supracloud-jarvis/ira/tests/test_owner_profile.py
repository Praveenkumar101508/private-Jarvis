"""Prompt 1.4 — owner profile store + routes.

`summarize()` is pure (no DB) so it's tested directly; the route handlers are
exercised with the store mocked (DB stubbed in conftest). Confirms the brain gets
a compact summary and that partial PUTs only send provided fields.
"""
import asyncio
from unittest.mock import AsyncMock

import owner_profile


def test_summarize_empty_profile_is_blank():
    assert owner_profile.summarize(
        {"name": "", "goals": "", "projects": "", "preferences": ""}
    ) == ""


def test_summarize_includes_all_set_fields():
    s = owner_profile.summarize(
        {"name": "Praveen", "goals": "Ship v1", "projects": "IRA", "preferences": "Be concise"}
    )
    assert s.startswith("Owner profile")
    for token in ("Praveen", "Ship v1", "IRA", "Be concise"):
        assert token in s


def test_summarize_partial_omits_blank_fields():
    s = owner_profile.summarize(
        {"name": "", "goals": "Learn Rust", "projects": "", "preferences": ""}
    )
    assert "Learn Rust" in s
    assert "Name:" not in s
    assert "Current projects:" not in s


def test_route_get_returns_profile(monkeypatch):
    from api.routes.profile import get_owner_profile

    fake = {"name": "P", "goals": "g", "projects": "p", "preferences": "x"}
    monkeypatch.setattr(owner_profile, "get_profile", AsyncMock(return_value=fake))
    out = asyncio.run(get_owner_profile(_user="owner"))
    assert out == fake


def test_route_put_sends_only_provided_fields(monkeypatch):
    from api.routes.profile import put_owner_profile, ProfileBody

    captured: dict = {}

    async def fake_update(**kwargs):
        captured.update(kwargs)
        return {"name": "P", "goals": "", "projects": "", "preferences": ""}

    monkeypatch.setattr(owner_profile, "update_profile", fake_update)
    out = asyncio.run(put_owner_profile(ProfileBody(name="P"), _user="owner"))

    assert captured == {"name": "P"}          # goals/projects/preferences omitted (None)
    assert out["name"] == "P"
