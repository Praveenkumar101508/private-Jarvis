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
  Every 6 hours  — Security report summary
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor

from config import get_settings
from worker.briefing import generate_briefing
from worker.security_monitor import run_security_scan
from worker.business_monitor import run_business_scan
from worker.reminders import check_due_reminders

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
    try:
        from worker.security_monitor import run_security_scan
        await run_security_scan()
    except Exception as e:
        logger.error(f"Security digest failed: {e}", exc_info=True)


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
