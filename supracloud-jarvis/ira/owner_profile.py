"""
ira/owner_profile.py — the owner's "who I am" profile store.

A single, overwrite-in-place record (Postgres = business data) holding the owner's
name, goals, current projects, and preferences. A compact summary is injected into
the brain's context on every chat turn so IRA stays grounded in who it serves — this
is distinct from conversational recall, which Hermes owns (project rule 5).

Reads degrade gracefully: if the DB is unavailable the profile is treated as empty
so a chat turn is never broken by a missing/locked profile row.
"""
from __future__ import annotations

from typing_extensions import TypedDict  # pydantic <3.12 requires this variant

from utils.db import acquire

# Columns that make up the profile (also the accepted update fields).
FIELDS = ("name", "goals", "projects", "preferences")


class OwnerProfile(TypedDict):
    name: str
    goals: str
    projects: str
    preferences: str


_EMPTY: OwnerProfile = {"name": "", "goals": "", "projects": "", "preferences": ""}


async def get_profile() -> OwnerProfile:
    """Return the single owner-profile record, or an empty profile if unset/unavailable."""
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                "SELECT name, goals, projects, preferences FROM owner_profile WHERE id IS TRUE"
            )
    except Exception:
        return dict(_EMPTY)  # DB down / not migrated yet -> never break the turn
    if not row:
        return dict(_EMPTY)
    return {k: (row[k] or "") for k in FIELDS}  # type: ignore[return-value]


async def update_profile(**fields: str) -> OwnerProfile:
    """Overwrite-in-place the single owner-profile record; return the new state.

    Only known FIELDS are written; unknown keys are ignored. Ensures the singleton
    row exists first so a partial update always lands.
    """
    updates = {k: ("" if v is None else str(v)) for k, v in fields.items() if k in FIELDS}
    async with acquire() as conn:
        await conn.execute(
            "INSERT INTO owner_profile (id) VALUES (TRUE) ON CONFLICT (id) DO NOTHING"
        )
        if updates:
            set_clause = ", ".join(f"{col} = ${i}" for i, col in enumerate(updates, start=1))
            await conn.execute(
                f"UPDATE owner_profile SET {set_clause}, updated_at = NOW() WHERE id IS TRUE",
                *updates.values(),
            )
    return await get_profile()


def summarize(profile: OwnerProfile) -> str:
    """Compact one-block summary for prompt injection; '' when nothing is set."""
    labels = (
        ("name", "Name"),
        ("goals", "Goals"),
        ("projects", "Current projects"),
        ("preferences", "Preferences"),
    )
    parts = [f"{label}: {profile[key]}" for key, label in labels if profile.get(key)]
    if not parts:
        return ""
    return "Owner profile —\n" + "\n".join(parts)


async def get_profile_summary() -> str:
    """Convenience: fetch the profile and return its compact summary ('' if empty)."""
    return summarize(await get_profile())


__all__ = ["OwnerProfile", "FIELDS", "get_profile", "update_profile", "summarize", "get_profile_summary"]
