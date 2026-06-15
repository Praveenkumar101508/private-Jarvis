"""
Calendar integration — Cal.com (primary) + Google Calendar (optional).

Cal.com (self-hosted or cloud):
  Set CALCOM_API_KEY and CALCOM_API_URL in .env.
  IRA reads upcoming bookings, creates events, and syncs to calendar_events table.

Google Calendar:
  Set GOOGLE_CALENDAR_ID and GOOGLE_SERVICE_ACCOUNT_JSON in .env.
  Uses service account auth — no OAuth prompt needed for self-hosted.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

import httpx

from config import get_settings
from utils.db import acquire

logger = logging.getLogger("ira.calendar")


# ── Cal.com Integration ────────────────────────────────────────────────────────

async def sync_calcom_bookings() -> int:
    """
    Fetch upcoming bookings from Cal.com and sync to calendar_events table.
    Returns the number of new events synced.
    """
    cfg = get_settings()
    if not cfg.calcom_api_key:
        logger.debug("Cal.com not configured — skipping sync")
        return 0

    try:
        async with httpx.AsyncClient(
            base_url=cfg.calcom_api_url,
            headers={"Authorization": f"Bearer {cfg.calcom_api_key}"},
            timeout=15,
        ) as client:
            resp = await client.get("/v1/bookings", params={"status": "upcoming"})
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        logger.warning(f"Cal.com sync failed: {e}")
        return 0

    bookings = data.get("bookings", [])
    synced = 0

    for booking in bookings:
        event_id = str(booking.get("id", ""))
        title = booking.get("title", "Meeting")
        start = booking.get("startTime")
        end = booking.get("endTime")
        attendees = booking.get("attendees", [])
        location = booking.get("location", "")

        if not start or not end:
            continue

        try:
            async with acquire() as conn:
                await conn.execute(
                    """INSERT INTO calendar_events
                       (external_id, source, title, attendees, start_at, end_at, location, status)
                       VALUES ($1, 'calcom', $2, $3, $4, $5, $6, 'confirmed')
                       ON CONFLICT (external_id) DO UPDATE
                       SET title=EXCLUDED.title,
                           start_at=EXCLUDED.start_at,
                           end_at=EXCLUDED.end_at""",
                    event_id, title, json.dumps(attendees),
                    datetime.fromisoformat(start.replace("Z", "+00:00")),
                    datetime.fromisoformat(end.replace("Z", "+00:00")),
                    location,
                )
            synced += 1
        except Exception as e:
            logger.warning(f"Failed to sync booking {event_id}: {e}")

    if synced:
        logger.info(f"Cal.com: synced {synced} event(s)")
    return synced


async def create_calcom_booking(
    event_type_id: int,
    start: str,
    name: str,
    email: str,
    notes: str = "",
) -> dict | None:
    """
    Create a booking in Cal.com via the API.
    Requires CALCOM_API_KEY and a valid event_type_id.
    """
    cfg = get_settings()
    if not cfg.calcom_api_key:
        return None

    try:
        async with httpx.AsyncClient(
            base_url=cfg.calcom_api_url,
            headers={"Authorization": f"Bearer {cfg.calcom_api_key}"},
            timeout=15,
        ) as client:
            resp = await client.post("/v1/bookings", json={
                "eventTypeId": event_type_id,
                "start": start,
                "responses": {"name": name, "email": email, "notes": notes},
                "timeZone": "UTC",
                "language": "en",
            })
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Cal.com booking creation failed: {e}")
        return None


async def get_upcoming_events(hours: int = 24) -> list[dict]:
    """Return calendar events starting within the next N hours."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """SELECT title, start_at, end_at, location, attendees
               FROM calendar_events
               WHERE start_at BETWEEN NOW() AND NOW() + ($1 * INTERVAL '1 hour')
               AND status = 'confirmed'
               ORDER BY start_at ASC""",
            hours,
        )
    return [
        {
            "title": r["title"],
            "start": r["start_at"].isoformat(),
            "end": r["end_at"].isoformat(),
            "location": r["location"],
            "attendees": r["attendees"],
        }
        for r in rows
    ]
