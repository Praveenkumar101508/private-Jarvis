"""
ira/actions/calendar_dav.py — local-first calendar over CalDAV.

Talks to the owner's own CalDAV server (Radicale, Nextcloud, Baïkal, …) — no
third-party cloud calendar. Reading is non-destructive and runs directly; creating
and deleting events are gated behind the approval guardrail at the route layer
(owner + explicit confirmation).

Event text (summary/description) is treated as untrusted — a meeting invite can
carry an injection payload — so it is wrapped via ``utils.prompt_safety`` before it
can reach a model. Everything fails soft: an unconfigured or unreachable server
returns a status dict rather than raising.

The ``caldav`` library (https://github.com/python-caldav/caldav) is used here under
its Apache-2.0 option (it is dual-licensed GPL-3.0-or-later OR Apache-2.0); see
``third_party/caldav/NOTICE.md``. It is imported lazily so the lightweight test
environment can inject a fake calendar without the dependency installed.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Callable, Optional

from actions import is_configured, not_configured_message
from config import get_settings
from utils.prompt_safety import check_adversarial_content, wrap_external_content

logger = logging.getLogger("ira.actions.calendar_dav")

# A factory takes cfg and returns an object that quacks like a caldav Calendar
# (``.events()``, ``.save_event(ical)``). Injectable for testing.
CalendarFactory = Callable[[object], object]

_PROP_RE = re.compile(r"^(UID|SUMMARY|DTSTART|DTEND|DESCRIPTION|LOCATION)(?:;[^:]*)?:(.*)$")


def _ical_dt(iso: str) -> str:
    """Normalise an ISO-8601 timestamp to iCalendar UTC basic format."""
    s = (iso or "").strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _esc(text: str) -> str:
    """Escape a value for an iCalendar text property."""
    return (text or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _build_ical(*, uid: str, summary: str, start: str, end: Optional[str],
                description: str, location: str) -> str:
    dtstamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//IRA//CalDAV//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}", f"DTSTAMP:{dtstamp}", f"DTSTART:{_ical_dt(start)}",
    ]
    if end:
        lines.append(f"DTEND:{_ical_dt(end)}")
    lines.append(f"SUMMARY:{_esc(summary)}")
    if description:
        lines.append(f"DESCRIPTION:{_esc(description)}")
    if location:
        lines.append(f"LOCATION:{_esc(location)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(lines) + "\r\n"


def _unfold(ical: str) -> str:
    # iCalendar folds long lines with CRLF followed by a space/tab.
    return re.sub(r"\r?\n[ \t]", "", ical or "")


def _parse_ical(ical: str) -> dict:
    out = {"uid": "", "summary": "", "dtstart": "", "dtend": "", "description": "", "location": ""}
    for line in _unfold(ical).splitlines():
        m = _PROP_RE.match(line)
        if not m:
            continue
        key, val = m.group(1).lower(), m.group(2).strip()
        key = "dtstart" if key == "dtstart" else "dtend" if key == "dtend" else key
        if key in out and not out[key]:
            out[key] = val
    return out


def _summarise_event(ical: str) -> dict:
    """Parse + sanitise one event; ``content`` is the model-facing wrapped block."""
    p = _parse_ical(ical)
    combined = (f"Summary: {p['summary']}\nStart: {p['dtstart']}\nEnd: {p['dtend']}\n"
                f"Location: {p['location']}\n\n{p['description']}")
    flags = check_adversarial_content(combined)
    if flags:
        logger.warning("prompt-injection patterns in calendar event %r: %s", p["summary"][:60], flags)
    return {
        "uid": p["uid"],
        "summary": p["summary"][:300],
        "dtstart": p["dtstart"][:32],
        "dtend": p["dtend"][:32],
        "content": wrap_external_content(combined, source=f"calendar event {p['uid'][:60]}"),
        "injection_flags": flags,
    }


def _default_calendar(cfg) -> object:
    import caldav
    client = caldav.DAVClient(
        url=cfg.caldav_url, username=cfg.caldav_username, password=cfg.caldav_password,
    )
    principal = client.principal()
    name = getattr(cfg, "caldav_calendar", "") or ""
    if name:
        return principal.calendar(name=name)
    cals = principal.calendars()
    if not cals:
        raise RuntimeError("no CalDAV calendars found for this principal")
    return cals[0]


def _event_ical(ev) -> str:
    data = getattr(ev, "data", None)
    return data if isinstance(data, str) else (data.decode() if isinstance(data, (bytes, bytearray)) else "")


# ── read (non-destructive) ───────────────────────────────────────────────────

def _list_sync(limit: int, cfg, factory: CalendarFactory) -> list[str]:
    calendar = factory(cfg)
    events = calendar.events()
    return [_event_ical(e) for e in events[: max(1, limit)]]


async def list_events(limit: int = 20, *, is_owner: bool = False, cfg=None, factory: Optional[CalendarFactory] = None) -> dict:
    """List upcoming events (read-only, sanitised, fail-soft).

    Owner-only and FAIL-CLOSED (``is_owner`` defaults to False): calendar contents
    are private, so the tool re-checks identity itself rather than trusting the caller.
    """
    if not is_owner:
        return {"status": "forbidden",
                "message": "Calendar access is restricted to the verified owner."}
    cfg = cfg or get_settings()
    if not is_configured("calendar_dav", cfg):
        return {"status": "not_configured", "message": not_configured_message("calendar_dav")}
    fac = factory or _default_calendar
    try:
        loop = asyncio.get_running_loop()
        icals = await loop.run_in_executor(None, _list_sync, limit, cfg, fac)
    except Exception as exc:  # noqa: BLE001 — fail soft
        return {"status": "error", "message": f"CalDAV list failed: {str(exc)[:160]}"}
    events = [_summarise_event(i) for i in icals]
    flags = sorted({f for e in events for f in e["injection_flags"]})
    return {"status": "ok", "count": len(events), "events": events, "injection_flags": flags}


# ── create / delete (destructive → gated at the route) ───────────────────────

def _create_sync(ical: str, cfg, factory: CalendarFactory) -> None:
    factory(cfg).save_event(ical)


async def create_event(
    *, summary: str, start: str, end: Optional[str] = None,
    description: str = "", location: str = "", is_owner: bool = False,
    cfg=None, factory: Optional[CalendarFactory] = None,
) -> dict:
    """Create an event. DESTRUCTIVE/outbound — callers must gate behind approval.

    Owner-only and FAIL-CLOSED (``is_owner`` defaults to False) as defense-in-depth
    on top of the route's approval guardrail.
    """
    if not is_owner:
        return {"status": "forbidden",
                "message": "Calendar changes are restricted to the verified owner."}
    cfg = cfg or get_settings()
    if not is_configured("calendar_dav", cfg):
        return {"status": "not_configured", "message": not_configured_message("calendar_dav")}
    fac = factory or _default_calendar
    uid = f"{uuid.uuid4()}@ira"
    try:
        ical = _build_ical(uid=uid, summary=summary, start=start, end=end,
                           description=description, location=location)
    except Exception as exc:  # noqa: BLE001 — bad date etc.
        return {"status": "error", "message": f"Invalid event: {str(exc)[:160]}"}
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _create_sync, ical, cfg, fac)
    except Exception as exc:  # noqa: BLE001 — fail soft
        return {"status": "error", "message": f"CalDAV create failed: {str(exc)[:160]}"}
    return {"status": "created", "uid": uid, "summary": summary, "start": start}


def _delete_sync(uid: str, cfg, factory: CalendarFactory) -> bool:
    calendar = factory(cfg)
    for ev in calendar.events():
        if _parse_ical(_event_ical(ev)).get("uid") == uid:
            ev.delete()
            return True
    return False


async def delete_event(uid: str, *, is_owner: bool = False, cfg=None, factory: Optional[CalendarFactory] = None) -> dict:
    """Delete an event by UID. DESTRUCTIVE — callers must gate behind approval.

    Owner-only and FAIL-CLOSED (``is_owner`` defaults to False) as defense-in-depth
    on top of the route's approval guardrail.
    """
    if not is_owner:
        return {"status": "forbidden",
                "message": "Calendar changes are restricted to the verified owner."}
    cfg = cfg or get_settings()
    if not is_configured("calendar_dav", cfg):
        return {"status": "not_configured", "message": not_configured_message("calendar_dav")}
    fac = factory or _default_calendar
    try:
        loop = asyncio.get_running_loop()
        found = await loop.run_in_executor(None, _delete_sync, uid, cfg, fac)
    except Exception as exc:  # noqa: BLE001 — fail soft
        return {"status": "error", "message": f"CalDAV delete failed: {str(exc)[:160]}"}
    return {"status": "deleted", "uid": uid} if found else {"status": "not_found", "uid": uid}


__all__ = ["list_events", "create_event", "delete_event", "summarise_event"]
# Public alias for the summariser (used by tests / callers).
summarise_event = _summarise_event
