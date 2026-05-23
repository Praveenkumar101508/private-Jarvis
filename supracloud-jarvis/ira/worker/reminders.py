"""Reminder delivery — checks for due reminders and fires notifications."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from config import get_settings
from utils.db import acquire
from worker.notifier import notify

logger = logging.getLogger("ira.reminders")


def _next_cron_time(cron_expr: str, after: datetime) -> datetime | None:
    """
    Calculate the next fire time for a cron expression after a given datetime.
    Uses croniter if available; falls back to a 24-hour advance.
    """
    try:
        from croniter import croniter
        itr = croniter(cron_expr, after)
        return itr.get_next(datetime).replace(tzinfo=timezone.utc)
    except Exception:
        from datetime import timedelta
        return after + timedelta(hours=24)


async def check_due_reminders() -> None:
    """Find reminders due in the next 15 minutes and deliver them."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """SELECT r.id, r.title, r.body, r.channels, r.repeat_cron,
                      t.title AS task_title
               FROM reminders r
               LEFT JOIN tasks t ON r.task_id = t.id
               WHERE r.sent = FALSE AND r.remind_at <= NOW() + INTERVAL '15 minutes'
               ORDER BY r.remind_at ASC
               LIMIT 20"""
        )

    if not rows:
        return

    logger.info(f"Delivering {len(rows)} due reminder(s)...")

    for row in rows:
        body = row["body"] or ""
        if row["task_title"]:
            body = f"Task: **{row['task_title']}**\n{body}"

        await notify(
            f"Reminder: {row['title']}",
            f"{get_settings().owner_name}, a reminder is due.\n\n{body}",
            category="reminder",
            priority="warning",
            metadata={"reminder_id": str(row["id"])},
        )

        # One-shot reminders: mark sent so they never fire again.
        # Recurring reminders: advance remind_at to the next cron occurrence.
        if not row.get("repeat_cron"):
            async with acquire() as conn:
                await conn.execute(
                    "UPDATE reminders SET sent=TRUE WHERE id=$1",
                    row["id"],
                )
        else:
            now = datetime.now(timezone.utc)
            next_time = _next_cron_time(row["repeat_cron"], now)
            if next_time:
                async with acquire() as conn:
                    await conn.execute(
                        "UPDATE reminders SET remind_at=$1 WHERE id=$2",
                        next_time,
                        row["id"],
                    )
                logger.info(f"Recurring reminder '{row['title']}' rescheduled to {next_time.isoformat()}")


async def create_reminder(
    title: str,
    remind_at,
    *,
    body: str | None = None,
    task_id: str | None = None,
    channels: list[str] | None = None,
    repeat_cron: str | None = None,
) -> str:
    """Create a new reminder. Returns reminder UUID."""
    rem_id = str(uuid.uuid4())
    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO reminders (id, task_id, title, body, remind_at, channels, repeat_cron)
               VALUES ($1, $2, $3, $4, $5, $6::text[], $7)""",
            uuid.UUID(rem_id),
            uuid.UUID(task_id) if task_id else None,
            title, body, remind_at,
            channels or ["websocket"],
            repeat_cron,
        )
    return rem_id
