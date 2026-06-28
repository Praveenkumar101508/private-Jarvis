"""
worker/heartbeat_signals.py — Heartbeat addendum signals (Feature 3 addendum).

Three additional read-only surfacing signals, each appended to the base Heartbeat's
ADDITIONAL_SIGNALS and gated under the SAME IRA_HEARTBEAT flag (no new top-level flag):

  A. Recurring themes  — "you've mentioned the visa timeline 4 times this week."
       Phase 0 item 8 found recurrence IS computable from existing data
       (memory_embeddings carries created_at + searchable content), so this is the
       REAL version: it groups recent memory entries by extracted theme and surfaces
       any theme that crosses a threshold. No schema change is required; a normalized
       `topic` column would sharpen grouping (a documented future seam), not a blocker.

  B. Calendar deadlines — "PhD deadline in 3 days."
       Phase 0 item 7 found a calendar source EXISTS (the `calendar_events` table,
       read by tasks/calendar.py). So this reads upcoming events directly from it —
       no new external connector is built here. A Google-Calendar connector that
       feeds the same table would be its own separately-scoped prompt.

  C. Open loops — "you said you'd close on_speak, still open."
       Commitments past an expected-by time and not resolved, drawn from BOTH the
       decision journal (overdue, unreviewed decisions) and memory (unfulfilled-
       promise phrasing older than a grace window).

Every signal is fail-closed: any source error yields [] and logs, never crashes the
tick. All routing/de-dupe/voice is handled by the base engine (worker/heartbeat.py).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta

from utils.db import acquire
from worker.heartbeat import SurfacedItem

logger = logging.getLogger("ira.worker.heartbeat_signals")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ── Signal A — recurring themes ───────────────────────────────────────────────

# Minimal stopword list — enough to keep "theme" tokens meaningful without pulling in
# an NLP dependency. Grouping is by salient keyword; a normalized `topic` column would
# improve this (future seam) but Phase 0 confirmed it is not required.
_STOPWORDS = {
    "the", "and", "for", "that", "with", "this", "have", "from", "your", "you",
    "about", "would", "could", "should", "there", "their", "what", "when", "will",
    "been", "they", "them", "then", "than", "into", "just", "like", "want", "need",
    "really", "going", "still", "also", "some", "much", "very", "make", "made",
    "today", "tomorrow", "yesterday", "week", "day", "time",
}
_WORD = re.compile(r"[a-z][a-z'-]{3,}")  # tokens of length >= 4


def _themes_of(text: str) -> set[str]:
    """Salient keyword themes in one memory entry (lowercased, stopwords removed)."""
    return {
        w for w in _WORD.findall((text or "").lower())
        if w not in _STOPWORDS
    }


async def gather_recurring_themes(now: datetime) -> list[SurfacedItem]:
    """Themes mentioned across >= threshold distinct memory entries in the window."""
    days = _int_env("IRA_HEARTBEAT_RECURRENCE_DAYS", 7)
    threshold = _int_env("IRA_HEARTBEAT_RECURRENCE_MIN", 3)
    window_start = now - timedelta(days=days)

    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT content FROM memory_embeddings
                   WHERE created_at >= $1
                   ORDER BY created_at DESC
                   LIMIT 1000""",
                window_start,
            )
    except Exception as e:
        logger.warning(f"heartbeat: recurrence fetch failed (fail-closed): {e}")
        return []

    if not rows:
        logger.debug("recurrence: no memory in window")
        return []

    counts: dict[str, int] = {}
    for r in rows:
        for theme in _themes_of(r["content"]):
            counts[theme] = counts.get(theme, 0) + 1  # at most once per entry (set)

    window_tag = window_start.date().isoformat()
    items: list[SurfacedItem] = []
    for theme, count in sorted(counts.items(), key=lambda kv: kv[1], reverse=True):
        if count < threshold:
            continue
        items.append(SurfacedItem(
            key=f"recurring_theme:{theme}:{window_tag}",
            kind="recurring_theme",
            message=(f"You've brought up '{theme}' {count} times in the last "
                     f"{days} days — worth a focused look?"),
        ))
    return items


# ── Signal B — calendar deadlines ─────────────────────────────────────────────

async def gather_calendar_deadlines(now: datetime) -> list[SurfacedItem]:
    """Confirmed calendar events within the horizon, read from calendar_events.

    Uses the existing calendar source identified in Phase 0; no new connector. When
    the table is empty or unreadable this degrades to [] cleanly.
    """
    horizon_days = _int_env("IRA_HEARTBEAT_CALENDAR_DAYS", 7)
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, title, start_at FROM calendar_events
                   WHERE start_at BETWEEN NOW() AND NOW() + make_interval(days => $1)
                     AND status = 'confirmed'
                   ORDER BY start_at ASC
                   LIMIT 50""",
                horizon_days,
            )
    except Exception as e:
        logger.warning(f"heartbeat: calendar fetch failed (fail-closed): {e}")
        return []

    items: list[SurfacedItem] = []
    for r in rows:
        start = r["start_at"]
        days_until = max(0, (start - now).days) if start else None
        when = (f"in {days_until} day(s)" if days_until is not None else "soon")
        items.append(SurfacedItem(
            key=f"calendar_deadline:{r['id']}",
            kind="calendar_deadline",
            message=f"Upcoming: {r['title']} — {when}.",
        ))
    return items

# NOTE (future seam): a Google Calendar connector would sync into this same
# calendar_events table (source='google'); the Heartbeat needs no change to pick it
# up. That connector is intentionally a separate, explicitly-scoped prompt — not here.


# ── Signal C — open loops / stale commitments ─────────────────────────────────

# Promise phrasing distinct from the base age-based stale-commitment markers.
_OPEN_LOOP_PATTERNS = ["%said i'd %", "%said i would %", "%meant to %",
                       "%promised to %", "%was going to %", "%never got to %"]


async def gather_open_loops(now: datetime) -> list[SurfacedItem]:
    """Commitments past an expected-by time and not resolved, from the decision
    journal (overdue, unreviewed) and memory (unfulfilled-promise phrasing)."""
    grace_days = _int_env("IRA_HEARTBEAT_OPEN_LOOP_GRACE_DAYS", 7)
    cutoff = now - timedelta(days=grace_days)
    items: list[SurfacedItem] = []

    # Source 1 — decision journal: decisions whose review was due > grace ago and that
    # were never reviewed are genuine open loops. Reuses the journal's read surface and
    # its own flag gating (returns [] when the journal flag is OFF).
    try:
        from memory import decision_journal
        overdue = await decision_journal.list_pending_reviews(cutoff)
        for d in overdue:
            items.append(SurfacedItem(
                key=f"open_loop:decision:{d['id']}",
                kind="open_loop",
                message=(f"Open loop: you decided '{d['summary']}' and meant to revisit "
                         f"it by now — still unresolved?"),
            ))
    except Exception as e:
        logger.warning(f"heartbeat: open-loop journal scan failed (fail-closed): {e}")

    # Source 2 — memory: unfulfilled-promise phrasing older than the grace window.
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT source_id, content FROM memory_embeddings
                   WHERE created_at < $1
                     AND content ILIKE ANY($2::text[])
                   ORDER BY created_at ASC
                   LIMIT 20""",
                cutoff, _OPEN_LOOP_PATTERNS,
            )
        for r in rows:
            content = (r["content"] or "").strip()
            if not content:
                continue
            snippet = content[:140] + ("…" if len(content) > 140 else "")
            items.append(SurfacedItem(
                key=f"open_loop:mem:{r['source_id']}",
                kind="open_loop",
                message=f'Open loop: "{snippet}" — did that ever get closed?',
            ))
    except Exception as e:
        logger.warning(f"heartbeat: open-loop memory scan failed (fail-closed): {e}")

    return items


# Registered with the base engine via worker.heartbeat.default_signals().
ADDITIONAL_SIGNALS = [
    gather_recurring_themes,
    gather_calendar_deadlines,
    gather_open_loops,
]
