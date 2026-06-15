"""
Reminder tools — read/write the PostgreSQL `reminders` table.

Tools exposed:
  set_reminder(message, due_iso)   — create a new reminder
  list_reminders()                  — list all pending reminders for the default user
  delete_reminder(reminder_id)      — delete a reminder by UUID

The `due_iso` parameter accepts:
  • An ISO-8601 datetime string  (e.g. "2026-05-17T15:00:00+05:30")
  • A natural-language expression (e.g. "tomorrow at 3pm", "in 2 hours")
    resolved via dateparser relative to the server timezone.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger()

# ── lazy imports (avoid hard-crashing if optional dep absent at import time) ──

def _parse_due(due_iso: str) -> datetime:
    """
    Parse a datetime from either an ISO string or natural-language expression.
    Falls back to dateparser for fuzzy expressions.
    Always returns a timezone-aware UTC datetime.
    """
    # Try strict ISO parse first
    try:
        dt = datetime.fromisoformat(due_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        pass

    # Fallback: natural-language via dateparser
    try:
        import dateparser
        dt = dateparser.parse(
            due_iso,
            settings={
                "RETURN_AS_TIMEZONE_AWARE": True,
                "TO_TIMEZONE": "UTC",
                "PREFER_DATES_FROM": "future",
            },
        )
        if dt is not None:
            return dt.astimezone(timezone.utc)
    except Exception as exc:
        log.warning("dateparser_failed", error=str(exc))

    raise ValueError(
        f"Cannot parse '{due_iso}' as a datetime. "
        "Use ISO-8601 or natural language like 'tomorrow at 3pm'."
    )


# ── default session user placeholder ────────────────────────────────────────
# In a multi-user deployment this would come from the session/JWT.
# For the single-user sovereign setup we use a stable sentinel UUID.
_DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def set_reminder(message: str, due_iso: str) -> dict[str, Any]:
    """
    Create a reminder in the PostgreSQL reminders table.

    Args:
        message:  Human-readable reminder text.
        due_iso:  When to fire — ISO-8601 string or natural-language expression.

    Returns:
        dict with 'id', 'message', 'due_at' on success, or 'error' on failure.
    """
    try:
        due_at = _parse_due(due_iso)
    except ValueError as exc:
        return {"error": str(exc)}

    try:
        from db.connection import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO reminders (user_id, message, due_at)
                VALUES ($1, $2, $3)
                RETURNING id, message, due_at
                """,
                _DEFAULT_USER_ID,
                message,
                due_at,
            )
        result = {
            "id": str(row["id"]),
            "message": row["message"],
            "due_at": row["due_at"].isoformat(),
        }
        log.info("reminder_created", id=result["id"], due_at=result["due_at"])
        return result
    except Exception as exc:
        log.error("set_reminder_failed", error=str(exc))
        return {"error": f"Database error: {exc}"}


async def list_reminders() -> list[dict[str, Any]]:
    """
    List all pending (not yet notified) reminders ordered by due_at ascending.

    Returns:
        List of dicts with 'id', 'message', 'due_at'; empty list on error.
    """
    try:
        from db.connection import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, message, due_at
                FROM reminders
                WHERE user_id = $1 AND NOT notified
                ORDER BY due_at ASC
                """,
                _DEFAULT_USER_ID,
            )
        return [
            {
                "id": str(r["id"]),
                "message": r["message"],
                "due_at": r["due_at"].isoformat(),
            }
            for r in rows
        ]
    except Exception as exc:
        log.error("list_reminders_failed", error=str(exc))
        return []


async def delete_reminder(reminder_id: str) -> dict[str, Any]:
    """
    Delete a reminder by its UUID.

    Args:
        reminder_id: UUID string of the reminder to delete.

    Returns:
        dict with 'deleted': True on success, or 'error' on failure.
    """
    try:
        rid = uuid.UUID(reminder_id)
    except ValueError:
        return {"error": f"'{reminder_id}' is not a valid UUID."}

    try:
        from db.connection import get_pool
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM reminders WHERE id = $1 AND user_id = $2",
                rid,
                _DEFAULT_USER_ID,
            )
        # result is a string like "DELETE 1"
        deleted_count = int(result.split()[-1])
        if deleted_count == 0:
            return {"error": f"No reminder found with id {reminder_id}"}
        log.info("reminder_deleted", id=reminder_id)
        return {"deleted": True, "id": reminder_id}
    except Exception as exc:
        log.error("delete_reminder_failed", error=str(exc))
        return {"error": f"Database error: {exc}"}
