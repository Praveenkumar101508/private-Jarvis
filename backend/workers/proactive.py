"""
Phase 4: Proactive Worker — IRA reaches out before you ask
Runs as a standalone process: python -m workers.proactive
"""
import asyncio
import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings
from agents.graph import IRAGraph
from persona.ira import MORNING_BRIEFING_PROMPT

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ira.proactive")

tz = pytz.timezone(settings.timezone)


async def morning_briefing():
    """Send daily morning briefing via configured notification channels."""
    log.info("Generating morning briefing")
    graph = IRAGraph()
    result = await graph.invoke(
        message=MORNING_BRIEFING_PROMPT,
        session_id="proactive:morning",
        language="en",
    )
    briefing = result.get("output", "Good morning! IRA is ready to help you today.")
    await _send_notification(title="☀️ Good Morning from IRA", body=briefing)


async def check_reminders():
    """Check and fire any due reminders from PostgreSQL reminders table."""
    from db.connection import get_pool

    now = datetime.now(tz)
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            # Fetch all pending reminders whose due_at has passed
            rows = await conn.fetch(
                """
                SELECT id, message, due_at
                FROM reminders
                WHERE NOT notified AND due_at <= $1
                ORDER BY due_at ASC
                """,
                now,
            )
            for row in rows:
                await _send_notification(
                    title="IRA Reminder",
                    body=row["message"],
                )
                # Mark as notified so it won't fire again
                await conn.execute(
                    "UPDATE reminders SET notified = TRUE WHERE id = $1",
                    row["id"],
                )
                log.info(
                    "reminder_fired",
                    id=str(row["id"]),
                    message=row["message"],
                    due_at=row["due_at"].isoformat(),
                )
    except Exception as exc:
        log.error("check_reminders_failed", error=str(exc))


async def periodic_health_check():
    """Log system health status."""
    log.info("IRA proactive worker heartbeat", time=datetime.now(tz).isoformat())


async def _send_notification(title: str, body: str):
    """Send notification via all configured channels."""
    log.info("notification", title=title, body=body[:100])

    tasks = []
    if settings.telegram_bot_token and settings.telegram_chat_id:
        tasks.append(_send_telegram(title, body))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    else:
        log.info("No notification channels configured. Add TELEGRAM_BOT_TOKEN to .env")


async def _send_telegram(title: str, body: str):
    from telegram import Bot
    bot = Bot(token=settings.telegram_bot_token)
    message = f"*{title}*\n\n{body}"
    await bot.send_message(
        chat_id=settings.telegram_chat_id,
        text=message,
        parse_mode="Markdown",
    )


async def main():
    scheduler = AsyncIOScheduler(timezone=tz)

    # Morning briefing at configured time
    hour, minute = settings.morning_briefing_time.split(":")
    scheduler.add_job(
        morning_briefing,
        CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
        id="morning_briefing",
    )

    # Check reminders every minute
    scheduler.add_job(
        check_reminders,
        "interval",
        minutes=1,
        id="check_reminders",
    )

    # Health check every 5 minutes
    scheduler.add_job(
        periodic_health_check,
        "interval",
        minutes=5,
        id="health_check",
    )

    scheduler.start()
    log.info(
        "IRA proactive worker started",
        timezone=settings.timezone,
        morning_briefing=settings.morning_briefing_time,
    )

    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
