"""
Calendar write-back endpoints — Cal.com.  # Feat P27

POST   /api/v1/calendar/event                  — create a booking
DELETE /api/v1/calendar/event/{external_id}    — cancel a booking

Both endpoints gracefully return an appropriate response when CALCOM_API_KEY
is not configured, so they're safe to call without checking first.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.middleware.auth import require_auth
from tasks.calendar import create_calcom_event, cancel_calcom_event

router = APIRouter(prefix="/calendar", tags=["calendar"])


class CreateEventRequest(BaseModel):
    event_type_id: int = Field(..., description="Cal.com eventTypeId")
    start: str = Field(..., description="ISO-8601 start time (e.g. 2026-06-01T10:00:00Z)")
    name: str = Field(..., description="Attendee display name")
    email: str = Field(..., description="Attendee e-mail address")
    notes: str = Field("", description="Optional meeting notes")
    idempotency_key: str | None = Field(
        None,
        description="Caller-supplied UUID for safe retries; auto-generated if omitted",
    )


@router.post("/event", status_code=201)
async def create_event(body: CreateEventRequest, _user: str = Depends(require_auth)):
    """Create a Cal.com booking and persist it to calendar_events."""
    ikey = body.idempotency_key or str(uuid.uuid4())
    result = await create_calcom_event(
        event_type_id=body.event_type_id,
        start=body.start,
        name=body.name,
        email=body.email,
        notes=body.notes,
        idempotency_key=ikey,
    )
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="Cal.com integration not configured — set CALCOM_API_KEY in .env",
        )
    return result


@router.delete("/event/{external_id}", status_code=200)
async def cancel_event(external_id: str, _user: str = Depends(require_auth)):
    """Cancel a Cal.com booking by its external ID."""
    ok = await cancel_calcom_event(external_id)
    if not ok:
        raise HTTPException(status_code=502, detail="Cal.com cancellation failed — check logs")
    return {"cancelled": True, "external_id": external_id}
