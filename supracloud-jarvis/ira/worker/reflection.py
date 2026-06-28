"""
worker/reflection.py — IRA's weekly Self-Reflection (Feature 4).

A retrospective analytics pass over data the owner ALREADY produces — git commit
history in the IRA repo, completed-task records, and decision-journal outcomes. It
summarizes patterns in plain language and speaks the reflection through the SAME
surface the Heartbeat uses. It adds no new tracking or telemetry, reads only, and
reuses the Heartbeat scheduler.

Deliberately NOT here: cameras, biometrics, mood/body inference, or any prediction —
only retrospective summary over self-reported, already-logged signals.

Gating:
  * IRA_REFLECTION (default ON, read via the IRA_USE_CORTEX mechanism).
  * IRA_REFLECTION_REPO — repo path for git history (defaults to the IRA repo root).
  * IRA_REFLECTION_DAYS — look-back window (default 7).

Summarization is routed through the existing model layer at the FAST tier (light task,
"route low") — Cortex/utils.llm picks the actual backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Awaitable, Callable, Optional

from utils.db import acquire

logger = logging.getLogger("ira.worker.reflection")

_TRUTHY = ("1", "true", "yes", "on")


def reflection_enabled() -> bool:
    """Whether weekly Self-Reflection is active. Defaults ON; set IRA_REFLECTION=false
    to disable."""
    return os.getenv("IRA_REFLECTION", "true").strip().lower() in _TRUTHY


def _window_days() -> int:
    try:
        return int(os.getenv("IRA_REFLECTION_DAYS", "7"))
    except ValueError:
        return 7


def _repo_root() -> str:
    """The IRA git repo root. Mirrors the repo-root discovery in utils/migrations.py."""
    env = os.getenv("IRA_REFLECTION_REPO", "").strip()
    if env:
        return env
    # worker/reflection.py -> ira -> supracloud-jarvis -> <repo root>
    return str(Path(__file__).resolve().parents[3])


# ── Signal gatherers (each fail-closed, read-only) ────────────────────────────

async def gather_git_activity(now: datetime) -> str:
    """One-line-per-commit git history for the window. Empty string on any error."""
    days = _window_days()

    def _run() -> str:
        try:
            out = subprocess.run(
                ["git", "-C", _repo_root(), "log",
                 f"--since={days} days ago", "--pretty=format:%h %s", "--no-color"],
                capture_output=True, text=True, timeout=15,
            )
            return out.stdout.strip() if out.returncode == 0 else ""
        except Exception as e:  # git missing / not a repo / timeout
            logger.debug(f"reflection: git history unavailable: {e}")
            return ""

    try:
        return await asyncio.to_thread(_run)
    except Exception as e:
        logger.warning(f"reflection: git gather failed (fail-closed): {e}")
        return ""


async def gather_completed_tasks(now: datetime) -> list[str]:
    """Titles of tasks completed within the window. [] on any error."""
    cutoff = now - timedelta(days=_window_days())
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT title, completed_at FROM tasks
                   WHERE status = 'done' AND completed_at >= $1
                   ORDER BY completed_at DESC
                   LIMIT 100""",
                cutoff,
            )
        return [r["title"] for r in rows if r["title"]]
    except Exception as e:
        logger.warning(f"reflection: completed-task gather failed (fail-closed): {e}")
        return []


async def gather_decision_outcomes(now: datetime) -> list[str]:
    """Decision outcomes recorded within the window — only when the journal flag is ON."""
    try:
        from memory import decision_journal
        if not decision_journal.journal_enabled():
            return []
    except Exception:
        return []

    cutoff = now - timedelta(days=_window_days())
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT summary, actual_outcome, calibration_note
                   FROM decisions
                   WHERE reviewed_at IS NOT NULL AND reviewed_at >= $1
                   ORDER BY reviewed_at DESC
                   LIMIT 50""",
                cutoff,
            )
        out: list[str] = []
        for r in rows:
            line = f"{r['summary']} -> {r['actual_outcome'] or 'n/a'}"
            if r["calibration_note"]:
                line += f" ({r['calibration_note']})"
            out.append(line)
        return out
    except Exception as e:
        logger.warning(f"reflection: decision-outcome gather failed (fail-closed): {e}")
        return []


# ── The weekly pass ───────────────────────────────────────────────────────────

Summarizer = Callable[[list[dict]], Awaitable[str]]
Speaker = Callable[[str], object]


async def run_weekly_reflection(
    now: Optional[datetime] = None,
    *,
    summarize: Optional[Summarizer] = None,
    speak: Optional[Speaker] = None,
) -> Optional[str]:
    """Gather already-logged activity, summarize it, and speak the reflection.

    Returns the reflection text, or None when the flag is OFF or there is nothing to
    reflect on. Fully read-only; never raises out of the scheduler.
    """
    if not reflection_enabled():
        return None
    now = now or datetime.now(timezone.utc)
    summarize = summarize or _default_summarize
    speak = speak or _default_speak

    commits = await gather_git_activity(now)
    tasks = await gather_completed_tasks(now)
    decisions = await gather_decision_outcomes(now)

    if not commits and not tasks and not decisions:
        logger.info("reflection: no activity in window — nothing to summarize")
        return None

    days = _window_days()
    blocks = []
    if commits:
        blocks.append(f"Git commits (last {days} days):\n{commits}")
    if tasks:
        blocks.append("Completed tasks:\n- " + "\n- ".join(tasks))
    if decisions:
        blocks.append("Decision outcomes:\n- " + "\n- ".join(decisions))
    context = "\n\n".join(blocks)

    messages = [
        {"role": "system", "content": (
            "You are IRA, reflecting privately with the owner. Given a week of their own "
            "logged activity, write a short (3-5 sentence) plain-language reflection on "
            "patterns and progress. Be concrete and grounded in the data; do not invent "
            "facts, predict the future, or give medical/biometric commentary.")},
        {"role": "user", "content": context},
    ]

    try:
        summary = (await summarize(messages) or "").strip()
    except Exception as e:
        logger.warning(f"reflection: summarization failed (fail-closed): {e}")
        return None
    if not summary:
        return None

    await _safe_speak(speak, summary)
    return summary


async def _default_summarize(messages: list[dict]) -> str:
    """Route through the existing model layer at the FAST tier (light task)."""
    from utils.llm import chat_complete
    return await chat_complete(messages)


def _default_speak(text: str) -> None:
    """Speak via the SAME surface the Heartbeat uses (voice path, log fallback)."""
    from worker.heartbeat import _default_speak as hb_speak
    hb_speak(text)


async def _safe_speak(speak: Speaker, text: str) -> None:
    import inspect
    try:
        result = speak(text)
        if inspect.isawaitable(result):
            await result
    except Exception as e:
        logger.info("reflection: speak failed (non-fatal): %s", e)


# ── Scheduler registration (reuses the Heartbeat scheduler) ────────────────────

def register_reflection(scheduler) -> bool:
    """Register the weekly reflection job, only when IRA_REFLECTION is ON."""
    if not reflection_enabled():
        logger.info("Self-Reflection disabled (set IRA_REFLECTION=true to enable)")
        return False
    scheduler.add_job(
        _reflection_job,
        trigger="cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        id="weekly_reflection",
        name="IRA Weekly Self-Reflection",
        replace_existing=True,
    )
    logger.info("Self-Reflection scheduled weekly (Sun 04:00 UTC)")
    return True


async def _reflection_job() -> None:
    try:
        await run_weekly_reflection()
    except Exception as e:
        logger.error(f"Weekly reflection failed: {e}", exc_info=True)
