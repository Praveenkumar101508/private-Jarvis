"""
ira/actions/ — the v1 action set and per-action configuration status.

Defines the actions IRA can take (tasks, reminders, briefings, file ops, calendar,
email-with-approval) and whether each one's external dependency is configured. A
handler uses this to return a clear "not configured" message instead of throwing
when an API key / service is missing — so a missing dependency degrades gracefully
and the conversation continues.

Local actions (tasks, reminders, briefings, file ops) have no external API key and
are always "configured"; calendar needs Cal.com and email needs SMTP.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from config import get_settings


@dataclass(frozen=True)
class ActionSpec:
    name: str
    requires: str                       # human label of the external dep, "" if local
    check: Callable[[object], bool]     # given cfg -> is it configured?


def _always(_cfg) -> bool:
    return True


_ACTIONS: dict[str, ActionSpec] = {
    "tasks":     ActionSpec("tasks", "", _always),       # Postgres (core, local)
    "reminders": ActionSpec("reminders", "", _always),   # Postgres (core, local)
    "briefings": ActionSpec("briefings", "", _always),   # local LLM
    "files":     ActionSpec("files", "", _always),       # local disk
    "notes":     ActionSpec("notes", "", _always),       # local disk (markdown)
    "calendar":  ActionSpec("calendar", "CALCOM_API_KEY (Cal.com)",
                            lambda c: bool(getattr(c, "calcom_api_key", ""))),
    "email":     ActionSpec("email", "SMTP_HOST (SMTP)",
                            lambda c: bool(getattr(c, "smtp_host", ""))),
    "email_triage": ActionSpec("email_triage", "IMAP_HOST (IMAP, read-only)",
                               lambda c: bool(getattr(c, "imap_host", ""))),
}

# The canonical v1 action set.
V1_ACTIONS: tuple[str, ...] = tuple(_ACTIONS)


def is_configured(action: str, cfg=None) -> bool:
    """True if `action` exists and its external dependency is configured."""
    spec = _ACTIONS.get(action)
    if spec is None:
        return False
    return spec.check(cfg or get_settings())


def not_configured_message(action: str) -> str:
    """A clear, user-facing 'not configured' message for a gracefully-skipped action."""
    spec = _ACTIONS.get(action)
    req = spec.requires if (spec and spec.requires) else "its dependency"
    return f"The '{action}' action is not configured ({req} missing); nothing was done."


def action_status(cfg=None) -> dict[str, dict]:
    """Per-action configuration status — never raises; safe for health/fail-soft use."""
    cfg = cfg or get_settings()
    status: dict[str, dict] = {}
    for name, spec in _ACTIONS.items():
        ok = spec.check(cfg)
        status[name] = {
            "configured": ok,
            "requires": spec.requires or None,
            "message": None if ok else not_configured_message(name),
        }
    return status


__all__ = [
    "ActionSpec", "V1_ACTIONS", "is_configured", "not_configured_message", "action_status",
]
