"""
Inbound webhook endpoints — public intake for external events.

POST /webhooks/lead      → receive a new lead from the SupraCloud website
POST /webhooks/booking   → receive a new booking confirmation
POST /webhooks/livekit   → LiveKit room event notifications

Security model:
  All webhook routes validate the 'X-Webhook-Secret' header against
  WEBHOOK_SECRET in the environment. Requests with an incorrect or missing
  secret are rejected with 401. The secret must be set in .env before
  the webhook URL is published anywhere.

Usage (set in your website's form submission handler):
  POST https://ira.yourdomain.com/webhooks/lead
  Headers: X-Webhook-Secret: <WEBHOOK_SECRET from .env>
  Body: {"name": "...", "email": "...", "message": "...", "source": "website"}
"""

from __future__ import annotations

import hmac
import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field

from config import get_settings
from utils.db import acquire

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger("ira.webhooks")


# ── Shared security ───────────────────────────────────────────────────────────

def _validate_webhook_secret(x_webhook_secret: str | None) -> None:
    """Raise 401 if the request secret doesn't match the configured secret."""
    cfg = get_settings()
    if not cfg.webhook_secret:
        # No secret configured → reject all webhooks (safer than accepting anything)
        raise HTTPException(
            status_code=503,
            detail="Webhook secret not configured. Set WEBHOOK_SECRET in .env",
        )
    if not hmac.compare_digest(x_webhook_secret or "", cfg.webhook_secret):
        raise HTTPException(
            status_code=401,
            detail="Invalid webhook secret. Request rejected.",
        )


# ── Lead intake ───────────────────────────────────────────────────────────────

class LeadPayload(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: EmailStr     # validated RFC email
    company: str | None = Field(None, max_length=200)
    phone: str | None = Field(None, max_length=50)
    message: str | None = Field(None, max_length=5000)
    source: str = "website"
    budget: str | None = None          # e.g. "10k-50k", "enterprise"
    service_interest: str | None = None
    metadata: dict = {}


@router.post("/lead", status_code=201)
async def receive_lead(
    payload: LeadPayload,
    x_webhook_secret: str | None = Header(None),
):
    """
    Receive an inbound lead from the SupraCloud website or CRM.

    Inserts the lead into `business_events` so the Business Monitor and
    Website Manager agent can immediately see and qualify it.
    The business_monitor worker scans every 5 minutes and will fire a
    notification to the owner via Telegram/WebSocket.
    """
    _validate_webhook_secret(x_webhook_secret)

    event_id = str(uuid.uuid4())
    title = f"Lead: {payload.name}"
    if payload.company:
        title += f" ({payload.company})"

    event_payload = {
        "name": payload.name,
        "email": payload.email,
        "company": payload.company,
        "phone": payload.phone,
        "message": payload.message,
        "source": payload.source,
        "budget": payload.budget,
        "service_interest": payload.service_interest,
        **payload.metadata,
    }

    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO business_events (id, event_type, title, payload, status)
               VALUES ($1, 'lead', $2, $3, 'new')""",
            uuid.UUID(event_id),
            title,
            json.dumps(event_payload),
        )

    logger.info(f"New lead received: {title} via {payload.source}")

    # Fire an immediate notification for hot leads (email or urgent keywords)
    urgent_keywords = {"urgent", "asap", "immediately", "enterprise", "critical"}
    is_hot = (
        any(kw in (payload.message or "").lower() for kw in urgent_keywords)
        or payload.budget in ("enterprise", "250k+", "100k-250k")
    )

    if is_hot:
        try:
            from worker.notifier import notify
            owner_name = get_settings().owner_name
            await notify(
                f"🔥 Hot Lead: {payload.name}",
                f"{owner_name}, a high-priority lead just arrived.\n\n"
                f"Name: {payload.name}\n"
                f"Email: {payload.email}\n"
                f"Company: {payload.company or 'N/A'}\n"
                f"Budget: {payload.budget or 'N/A'}\n"
                f"Message: {(payload.message or '')[:200]}\n\n"
                f"IRA recommends responding within the hour.",
                category="business",
                priority="critical",
                metadata={"lead_id": event_id, "source": payload.source},
            )
        except Exception as e:
            logger.warning(f"Hot lead notification failed: {e}")

    return {
        "status": "received",
        "lead_id": event_id,
        "title": title,
    }


# ── Booking intake ────────────────────────────────────────────────────────────

class BookingPayload(BaseModel):
    booking_id: str = ""
    client_name: str = Field(..., min_length=1, max_length=200)
    client_email: EmailStr   # validated RFC email
    service: str = ""
    scheduled_at: str = ""        # ISO 8601
    duration_minutes: int = 60
    notes: str | None = None
    source: str = "calcom"
    metadata: dict = {}


@router.post("/booking", status_code=201)
async def receive_booking(
    payload: BookingPayload,
    x_webhook_secret: str | None = Header(None),
):
    """Receive a new booking confirmation from Cal.com or any booking platform."""
    _validate_webhook_secret(x_webhook_secret)

    event_id = str(uuid.uuid4())
    title = f"Booking: {payload.client_name} — {payload.service}"
    event_payload = {
        "booking_id": payload.booking_id,
        "client_name": payload.client_name,
        "client_email": payload.client_email,
        "service": payload.service,
        "scheduled_at": payload.scheduled_at,
        "duration_minutes": payload.duration_minutes,
        "notes": payload.notes,
        "source": payload.source,
        **payload.metadata,
    }

    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO business_events (id, event_type, title, payload, status)
               VALUES ($1, 'booking', $2, $3, 'confirmed')""",
            uuid.UUID(event_id),
            title,
            json.dumps(event_payload),
        )

    logger.info(f"New booking received: {title}")

    try:
        from worker.notifier import notify
        await notify(
            f"📅 New Booking: {payload.client_name}",
            f"{get_settings().owner_name}, a new consultation has been booked.\n\n"
            f"Client: {payload.client_name}\n"
            f"Email: {payload.client_email}\n"
            f"Service: {payload.service or 'N/A'}\n"
            f"Scheduled: {payload.scheduled_at or 'TBD'}\n"
            f"Duration: {payload.duration_minutes} minutes\n"
            f"Notes: {(payload.notes or 'None')[:200]}",
            category="business",
            priority="warning",
            metadata={"booking_id": event_id},
        )
    except Exception as e:
        logger.warning(f"Booking notification failed: {e}")

    return {
        "status": "received",
        "booking_id": event_id,
        "title": title,
    }


# ── LiveKit room events ────────────────────────────────────────────────────────

@router.post("/livekit")
async def livekit_events(
    request: Request,
    x_webhook_secret: str | None = Header(None),
):
    """
    Receive LiveKit room event notifications.
    Used to track voice session starts/ends and participant joins.
    """
    _validate_webhook_secret(x_webhook_secret)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = body.get("event", "unknown")
    room = body.get("room", {}).get("name", "unknown")
    logger.info(f"LiveKit event: {event} in room {room}")

    # Log significant events
    if event in ("room_started", "room_finished", "participant_joined", "participant_left"):
        async with acquire() as conn:
            await conn.execute(
                """INSERT INTO security_events (severity, event_type, description, metadata)
                   VALUES ('info', 'livekit_event', $1, $2)""",
                f"LiveKit {event} in room {room}",
                json.dumps(body),
            )

    return {"status": "ok", "event": event}
