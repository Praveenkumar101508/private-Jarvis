"""
IRA APScheduler — Proactive intelligence job registry.

All scheduled jobs are persisted in PostgreSQL (APScheduler SQLAlchemy job store)
so they survive container restarts without duplicating runs.

Job schedule:
  08:00 daily    — Morning briefing
  20:00 daily    — Evening summary
  Every 60s      — Security scan (nginx logs + system health)
  Every 5 min    — Business scan (new leads, bookings)
  Every 15 min   — Reminder check (due reminders)
  Every 30 min   — Cal.com calendar sync
  Every 6 hours  — Security report summary
  Every 12 hours — Architect Evolution Team cycle (silent, notifies when ready)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from config import get_settings
from worker.briefing import generate_briefing
from worker.security_monitor import run_security_scan
from worker.business_monitor import run_business_scan
from worker.reminders import check_due_reminders
from worker.self_healing import run_self_healing_check, run_self_reflection
from worker.backup import run_database_backup
from tasks.calendar import sync_calcom_bookings

logger = logging.getLogger("ira.scheduler")

_scheduler: AsyncIOScheduler | None = None


def _make_pg_url(cfg) -> str:
    """Build synchronous SQLAlchemy PostgreSQL URL for APScheduler job store."""
    return (
        f"postgresql+psycopg2://{cfg.postgres_user}:{cfg.postgres_password}"
        f"@{cfg.postgres_host}:{cfg.postgres_port}/{cfg.postgres_db}"
    )


def build_scheduler() -> AsyncIOScheduler:
    cfg = get_settings()

    jobstores = {
        "default": SQLAlchemyJobStore(url=_make_pg_url(cfg), tablename="apscheduler_jobs")
    }
    executors = {
        "default": AsyncIOExecutor()
    }
    job_defaults = {
        "coalesce": True,         # If a job missed multiple runs, run it once
        "max_instances": 1,       # Never run the same job twice simultaneously
        "misfire_grace_time": 120, # Allow up to 2min late execution
    }

    scheduler = AsyncIOScheduler(
        jobstores=jobstores,
        executors=executors,
        job_defaults=job_defaults,
        timezone="UTC",
    )

    # ── Register jobs ─────────────────────────────────────────────────────────

    # Morning briefing (08:00 UTC — adjust IRA_BRIEFING_TZ if needed)
    scheduler.add_job(
        _morning_briefing,
        trigger="cron",
        hour=int(cfg.briefing_hour_utc),
        minute=0,
        id="morning_briefing",
        name="IRA Morning Briefing",
        replace_existing=True,
    )

    # Evening summary (20:00 UTC)
    scheduler.add_job(
        _evening_summary,
        trigger="cron",
        hour=20,
        minute=0,
        id="evening_summary",
        name="IRA Evening Summary",
        replace_existing=True,
    )

    # Security scan — every 60 seconds
    scheduler.add_job(
        run_security_scan,
        trigger="interval",
        seconds=60,
        id="security_scan",
        name="Security Guardian Scan",
        replace_existing=True,
    )

    # Business scan — every 5 minutes
    scheduler.add_job(
        run_business_scan,
        trigger="interval",
        minutes=5,
        id="business_scan",
        name="Business Monitor Scan",
        replace_existing=True,
    )

    # Reminder check — every 15 minutes
    scheduler.add_job(
        check_due_reminders,
        trigger="interval",
        minutes=15,
        id="reminder_check",
        name="Reminder Delivery Check",
        replace_existing=True,
    )

    # 6-hourly security digest
    scheduler.add_job(
        _security_digest,
        trigger="interval",
        hours=6,
        id="security_digest",
        name="Security Digest",
        replace_existing=True,
    )

    # Calendar sync — every 30 minutes (pulls Cal.com bookings into calendar_events)
    scheduler.add_job(
        _sync_calendar,
        trigger="interval",
        minutes=30,
        id="calendar_sync",
        name="Cal.com Calendar Sync",
        replace_existing=True,
    )

    # Self-Healing Agent — every 60 seconds, detects and fixes system issues
    scheduler.add_job(
        _self_healing_check,
        trigger="interval",
        seconds=60,
        id="self_healing",
        name="IRA Self-Healing Agent",
        replace_existing=True,
    )

    # Self-Learning Reflection — hourly, improves IRA's own routing and prompts
    scheduler.add_job(
        _self_reflection,
        trigger="interval",
        hours=1,
        id="self_reflection",
        name="IRA Self-Learning Reflection",
        replace_existing=True,
    )

    # Daily database backup — 03:00 UTC (low-traffic window)
    scheduler.add_job(
        _database_backup,
        trigger="cron",
        hour=3,
        minute=0,
        id="database_backup",
        name="IRA Daily Database Backup",
        replace_existing=True,
    )

    # Architect Evolution Team — every 12 hours (06:00 and 18:00 UTC)
    # Silently analyses IRA vs Grok/Claude/Gemini, generates proposal, notifies owner.
    # Nothing is implemented until owner types "architect implement: [feature name]"
    scheduler.add_job(
        _architect_cycle,
        trigger="interval",
        hours=12,
        id="architect_evolution",
        name="IRA Architect Evolution Team",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(hours=12),
    )

    # Memory retention — weekly at 02:00 UTC on Sunday (Fix #75)
    # Deletes memory_embeddings rows older than 90 days to keep the table
    # from growing unbounded. Messages + conversations are NOT deleted.
    scheduler.add_job(
        _memory_retention,
        trigger="cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        id="memory_retention",
        name="IRA Memory Retention Purge",
        replace_existing=True,
    )

    return scheduler


async def _morning_briefing() -> None:
    try:
        await generate_briefing("morning")
    except Exception as e:
        logger.error(f"Morning briefing failed: {e}", exc_info=True)


async def _evening_summary() -> None:
    try:
        await generate_briefing("evening")
    except Exception as e:
        logger.error(f"Evening summary failed: {e}", exc_info=True)


async def _security_digest() -> None:
    """
    Fix #72: generate a 6-hour security digest from the DB instead of
    re-running the scan.  The old implementation called run_security_scan()
    which would re-process logs rather than summarise what happened.
    """
    try:
        from utils.db import acquire
        from worker.notifier import notify
        from config import get_settings

        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT severity, event_type, source_ip, description, created_at
                   FROM security_events
                   WHERE created_at > NOW() - INTERVAL '6 hours'
                   ORDER BY created_at DESC
                   LIMIT 20"""
            )

        if not rows:
            logger.debug("Security digest: no events in last 6 hours")
            return

        cfg = get_settings()
        total = len(rows)
        critical = sum(1 for r in rows if r["severity"] == "critical")
        high = sum(1 for r in rows if r["severity"] == "high")

        lines = "\n".join(
            f"• [{r['severity'].upper()}] {r['event_type']} — {r['description'][:80]}"
            for r in rows[:10]
        )
        summary = (
            f"🔐 *6-hour Security Digest* — {total} event(s), "
            f"{critical} critical, {high} high\n\n{lines}"
        )
        if total > 10:
            summary += f"\n…and {total - 10} more events"

        priority = "critical" if critical > 0 else ("warning" if high > 0 else "info")
        await notify(
            f"Security Digest — {total} event(s) in last 6h",
            summary,
            category="security",
            priority=priority,
        )
        logger.info(f"Security digest sent: {total} events ({critical} critical, {high} high)")
    except Exception as e:
        logger.error(f"Security digest failed: {e}", exc_info=True)


async def _sync_calendar() -> None:
    try:
        await sync_calcom_bookings()
    except Exception as e:
        logger.error(f"Calendar sync failed: {e}", exc_info=True)


async def _self_healing_check() -> None:
    try:
        await run_self_healing_check()
    except Exception as e:
        logger.error(f"Self-healing check failed: {e}", exc_info=True)


async def _self_reflection() -> None:
    try:
        await run_self_reflection()
    except Exception as e:
        logger.error(f"Self-reflection failed: {e}", exc_info=True)


async def _database_backup() -> None:
    try:
        path = await run_database_backup()
        if path:
            logger.info(f"Daily backup saved: {path.name}")
        else:
            logger.error("Daily backup FAILED — check pg_dump logs")
    except Exception as e:
        logger.error(f"Backup job failed: {e}", exc_info=True)


async def _architect_cycle() -> None:
    """
    24/7 Evolution Team background cycle.
    Runs silently every 12 hours — generates a proposal and notifies the owner.
    NEVER auto-implements anything — always waits for explicit 'architect implement: X' command.
    """
    try:
        from agents.architect_agent import run_background_architect_cycle
        await run_background_architect_cycle()
    except Exception as e:
        logger.error(f"Architect evolution cycle failed: {e}", exc_info=True)


async def _memory_retention() -> None:
    """Weekly purge of memory_embeddings older than 90 days. (Fix #75)"""
    try:
        from memory.store import purge_old_memories
        deleted = await purge_old_memories(retention_days=90)
        logger.info(f"Memory retention complete: {deleted} old embeddings purged")
    except Exception as e:
        logger.error(f"Memory retention job failed: {e}", exc_info=True)


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = build_scheduler()
    return _scheduler


async def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        logger.info("IRA Scheduler started. All jobs registered.")


async def stop_scheduler() -> None:
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("IRA Scheduler stopped.")
