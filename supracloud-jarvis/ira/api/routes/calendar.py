"""
Calendar write-back endpoints — Cal.com.  # Feat P27

POST   /api/v1/calendar/event                  — create a booking
DELETE /api/v1/calendar/event/{external_id}    — cancel a booking

Both endpoints gracefully return an appropriate response when CALCOM_API_KEY
is not configured, so they're safe to call without checking first.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.middleware.auth import require_auth, is_owner
from tasks.calendar import create_calcom_event, cancel_calcom_event
from utils.approval import owner_gated_action

router = APIRouter(prefix="/calendar", tags=["calendar"])


def _apply_outcome(outcome: dict):
    """Map an owner_gated_action result to HTTP, or return it (draft/executed)."""
    if outcome["status"] == "forbidden":
        raise HTTPException(status_code=403, detail=outcome["detail"])
    if outcome["status"] in ("expired", "not_found"):
        raise HTTPException(status_code=409, detail=outcome["detail"])
    if outcome["status"] == "executed":
        return outcome["result"]
    return outcome  # confirmation_required: token + preview for the caller to confirm


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
    confirm_token: str | None = Field(
        None,
        description="Approval token from the prior draft; omit to receive a draft to confirm",
    )


@router.post("/event")
async def create_event(body: CreateEventRequest, _user: str = Depends(require_auth)):
    """Create a Cal.com booking — owner-gated and confirmation-gated (high-stakes)."""
    ikey = body.idempotency_key or str(uuid.uuid4())

    async def _do():
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

    preview = (
        f"Create Cal.com booking for {body.name} <{body.email}> "
        f"at {body.start} (event type {body.event_type_id})"
    )
    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="create_calendar_event", preview=preview, execute=_do,
        confirm_token=body.confirm_token,
    )
    return _apply_outcome(outcome)


@router.delete("/event/{external_id}")
async def cancel_event(
    external_id: str,
    confirm_token: str | None = Query(None, description="Approval token; omit to receive a draft"),
    _user: str = Depends(require_auth),
):
    """Cancel a Cal.com booking — owner-gated and confirmation-gated (high-stakes)."""

    async def _do():
        ok = await cancel_calcom_event(external_id)
        if not ok:
            raise HTTPException(status_code=502, detail="Cal.com cancellation failed — check logs")
        return {"cancelled": True, "external_id": external_id}

    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="cancel_calendar_event", preview=f"Cancel Cal.com booking {external_id}",
        execute=_do, confirm_token=confirm_token,
    )
    return _apply_outcome(outcome)
