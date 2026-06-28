"""
worker/heartbeat.py — IRA's Heartbeat (Feature 3).

IRA is normally reactive. The Heartbeat makes it proactive: a scheduled, READ-ONLY
pass that reviews pending decision reviews and stale commitments in memory, de-dupes
against what it has already surfaced, and speaks anything new through the REAL voice
output path (the same local-TTS sink the brain's on_speak uses). If voice output is
unavailable it falls back to a logged message and exits cleanly — it never crashes the
loop, and it never modifies user data.

Gating:
  * IRA_HEARTBEAT (default ON, read via the IRA_USE_CORTEX mechanism). When OFF the
    job is never scheduled and run_heartbeat_tick() is a no-op.
  * IRA_HEARTBEAT_INTERVAL_HOURS (default 6) — tick cadence.
  * IRA_HEARTBEAT_STALE_DAYS (default 14) — how old a memory commitment must be to
    count as "stale".

The signal set is a list of async gatherers (each fail-closed). Feature 3's addendum
adds more gatherers to ADDITIONAL_SIGNALS without touching this engine.
"""

from __future__ import annotations

import inspect
import logging
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Awaitable, Callable, Optional

from utils.db import acquire

logger = logging.getLogger("ira.worker.heartbeat")

_TRUTHY = ("1", "true", "yes", "on")


def heartbeat_enabled() -> bool:
    """Whether the Heartbeat is active. Defaults ON; set IRA_HEARTBEAT=false to disable.
    Note: surfaced items are spoken aloud only when IRA_VOICE_OUTPUT=local; otherwise
    they are logged."""
    return os.getenv("IRA_HEARTBEAT", "true").strip().lower() in _TRUTHY


def heartbeat_interval_hours() -> float:
    try:
        return float(os.getenv("IRA_HEARTBEAT_INTERVAL_HOURS", "6"))
    except ValueError:
        return 6.0


def _stale_days() -> int:
    try:
        return int(os.getenv("IRA_HEARTBEAT_STALE_DAYS", "14"))
    except ValueError:
        return 14


@dataclass(frozen=True)
class SurfacedItem:
    """One thing the Heartbeat may say. ``key`` is the stable de-dupe identity."""
    key: str
    kind: str
    message: str


# Gatherers take the current time and return items. Each is independently fail-closed.
Gatherer = Callable[[datetime], Awaitable[list[SurfacedItem]]]


# ── Base signals ──────────────────────────────────────────────────────────────

async def gather_pending_decisions(now: datetime) -> list[SurfacedItem]:
    """Pending decision reviews — only when IRA_DECISION_JOURNAL is ON."""
    from memory import decision_journal
    if not decision_journal.journal_enabled():
        return []
    rows = await decision_journal.list_pending_reviews(now)
    items: list[SurfacedItem] = []
    for r in rows:
        expected = r.get("expected_outcome") or "no expectation recorded"
        items.append(SurfacedItem(
            key=f"decision_review:{r['id']}",
            kind="decision_review",
            message=(f"Time to review a decision: {r['summary']}. "
                     f"You expected: {expected}. How did it actually turn out?"),
        ))
    return items


# Commitment markers — content matching any of these (case-insensitive) is treated as
# a commitment that may have gone stale. Read-only heuristic over memory_embeddings.
_COMMITMENT_PATTERNS = ["%i'll %", "%i will %", "%i need to %", "%i should %",
                        "%i'm going to %", "%remind me to %", "%i promised %"]


async def gather_stale_memory_commitments(now: datetime) -> list[SurfacedItem]:
    """Commitment-like memories older than the staleness threshold.

    Read-only scan of memory_embeddings for commitment phrasing that was recorded a
    while ago and may still be open. De-dupe (so each is said once) is handled by the
    shared ledger, not here.
    """
    cutoff = now - timedelta(days=_stale_days())
    rows = await _fetch_stale_commitments(cutoff)
    items: list[SurfacedItem] = []
    for r in rows:
        content = (r["content"] or "").strip()
        if not content:
            continue
        snippet = content[:140] + ("…" if len(content) > 140 else "")
        items.append(SurfacedItem(
            key=f"stale_commitment:{r['source_id']}",
            kind="stale_commitment",
            message=f'A while back you noted: "{snippet}" — is that still open?',
        ))
    return items


async def _fetch_stale_commitments(cutoff: datetime, limit: int = 20) -> list[dict]:
    """Parameterized read of stale commitment-like memories. Fail-closed → []."""
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT source_id, content, created_at
                   FROM memory_embeddings
                   WHERE created_at < $1
                     AND content ILIKE ANY($2::text[])
                   ORDER BY created_at ASC
                   LIMIT $3""",
                cutoff, _COMMITMENT_PATTERNS, limit,
            )
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"heartbeat: stale-commitment fetch failed (fail-closed): {e}")
        return []


# Base gatherers; the addendum appends to ADDITIONAL_SIGNALS (imported lazily in
# default_signals so this engine has no hard dependency on the addendum module).
BASE_SIGNALS: list[Gatherer] = [
    gather_pending_decisions,
    gather_stale_memory_commitments,
]


def default_signals() -> list[Gatherer]:
    """Base signals plus any registered by the Feature 3 addendum (if present)."""
    signals = list(BASE_SIGNALS)
    try:
        from worker import heartbeat_signals  # addendum module (optional)
        signals.extend(heartbeat_signals.ADDITIONAL_SIGNALS)
    except Exception:
        pass
    return signals


# ── The tick ──────────────────────────────────────────────────────────────────

async def run_heartbeat_tick(
    now: Optional[datetime] = None,
    *,
    speak: Optional[Callable[[str], object]] = None,
    signals: Optional[list[Gatherer]] = None,
) -> list[str]:
    """Run one read-only pass. Returns the keys of items surfaced this tick.

    No-op (returns []) when IRA_HEARTBEAT is OFF. Every signal and every surface is
    individually guarded so one failure cannot stop the others or crash the loop.
    """
    if not heartbeat_enabled():
        return []
    now = now or datetime.now(timezone.utc)
    speak = speak or _default_speak
    signals = signals if signals is not None else default_signals()

    candidates: list[SurfacedItem] = []
    for gather in signals:
        try:
            candidates.extend(await gather(now))
        except Exception as e:
            logger.warning("heartbeat signal %s failed (fail-closed): %s",
                           getattr(gather, "__name__", gather), e)

    surfaced: list[str] = []
    for item in candidates:
        try:
            if await _claim_item(item):       # atomic de-dupe; only newly-claimed pass
                await _safe_speak(speak, item.message)
                surfaced.append(item.key)
        except Exception as e:
            logger.warning("heartbeat: surfacing %s failed (non-fatal): %s", item.key, e)
    if surfaced:
        logger.info("heartbeat surfaced %d new item(s)", len(surfaced))
    return surfaced


async def _claim_item(item: SurfacedItem) -> bool:
    """Atomically record an item in the ledger. Returns True only if it was NOT
    already surfaced. Fail-closed: a DB error returns False (do not risk repeating)."""
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO heartbeat_surfaced (item_key, kind, message)
                   VALUES ($1, $2, $3)
                   ON CONFLICT (item_key) DO NOTHING
                   RETURNING id""",
                item.key, item.kind, item.message,
            )
        return row is not None
    except Exception as e:
        logger.warning(f"heartbeat: ledger claim failed (fail-closed): {e}")
        return False


async def _safe_speak(speak: Callable[[str], object], text: str) -> None:
    """Invoke the speak seam, tolerating sync or async callables; never raises."""
    try:
        result = speak(text)
        if inspect.isawaitable(result):
            await result
    except Exception as e:
        logger.info("heartbeat: speak failed (non-fatal): %s", e)


def _default_speak(text: str) -> None:
    """Hand the utterance to the REAL voice path — the same local-TTS sink the brain's
    on_speak uses (voice/voice_output.py). If voice output is unavailable (mode off,
    no audio device, TTS error) fall back to a logged message. Never raises."""
    try:
        from voice.voice_output import output_mode, LocalAudioSink, _default_synth
    except Exception as e:
        logger.info("heartbeat (voice path unavailable, %s): %s", e, text)
        return
    if output_mode() != "local":
        logger.info("heartbeat (voice off): %s", text)
        return
    try:
        wav = _default_synth(text)
        if wav:
            LocalAudioSink().play(wav)
    except Exception as e:
        logger.info("heartbeat (voice unavailable, %s): %s", e, text)


# ── Scheduler registration ────────────────────────────────────────────────────

def register_heartbeat(scheduler) -> bool:
    """Register the Heartbeat job on the given APScheduler, only when IRA_HEARTBEAT is
    ON. Returns True if the job was scheduled. When OFF, nothing is scheduled."""
    if not heartbeat_enabled():
        logger.info("Heartbeat disabled (set IRA_HEARTBEAT=true to enable)")
        return False
    scheduler.add_job(
        _heartbeat_job,
        trigger="interval",
        hours=heartbeat_interval_hours(),
        id="heartbeat",
        name="IRA Heartbeat",
        replace_existing=True,
    )
    logger.info("Heartbeat scheduled every %.2gh", heartbeat_interval_hours())
    return True


async def _heartbeat_job() -> None:
    """APScheduler entry point — fully guarded so a tick error never kills the job."""
    try:
        await run_heartbeat_tick()
    except Exception as e:
        logger.error(f"Heartbeat tick failed: {e}", exc_info=True)
