"""
Local-first CalDAV calendar endpoints (self-hosted — no third-party cloud).

GET    /api/v1/calendar/dav/events            — list upcoming events (read-only)
POST   /api/v1/calendar/dav/event             — create an event (owner + confirm gated)
DELETE /api/v1/calendar/dav/event/{uid}       — delete an event (owner + confirm gated)

Kept under a distinct /calendar/dav prefix so it sits alongside the existing
Cal.com endpoints without colliding. Create/delete are destructive, so they go
through the approval guardrail (owner + explicit confirmation).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from actions import calendar_dav
from api.middleware.auth import require_auth, is_owner
from utils.approval import owner_gated_action

router = APIRouter(prefix="/calendar/dav", tags=["calendar"])


def _apply_outcome(outcome: dict):
    if outcome["status"] == "forbidden":
        raise HTTPException(status_code=403, detail=outcome["detail"])
    if outcome["status"] in ("expired", "not_found"):
        raise HTTPException(status_code=409, detail=outcome["detail"])
    if outcome["status"] == "executed":
        return outcome["result"]
    return outcome  # confirmation_required


class CreateEventRequest(BaseModel):
    summary: str = Field(..., min_length=1, max_length=300)
    start: str = Field(..., description="ISO-8601 start (e.g. 2026-06-01T10:00:00Z)")
    end: str | None = Field(None, description="ISO-8601 end time")
    description: str = Field("", max_length=10_000)
    location: str = Field("", max_length=500)
    confirm_token: str | None = Field(None, description="Approval token; omit to receive a draft")


@router.get("/events")
async def list_events(limit: int = 20, _user: str = Depends(require_auth)):
    """List upcoming events — read-only, sanitised, fail-soft. Owner-only."""
    return await calendar_dav.list_events(limit=max(1, min(int(limit), 100)), is_owner=is_owner(_user))


@router.post("/event")
async def create_event(body: CreateEventRequest, _user: str = Depends(require_auth)):
    """Create a CalDAV event — owner-gated and confirmation-gated (destructive)."""

    async def _do():
        return await calendar_dav.create_event(
            summary=body.summary, start=body.start, end=body.end,
            description=body.description, location=body.location,
            is_owner=is_owner(_user),
        )

    preview = f"Create calendar event '{body.summary}' at {body.start}" + (f"–{body.end}" if body.end else "")
    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="create_calendar_dav_event", preview=preview, execute=_do,
        confirm_token=body.confirm_token,
    )
    return _apply_outcome(outcome)


@router.delete("/event/{uid}")
async def delete_event(
    uid: str,
    confirm_token: str | None = Query(None, description="Approval token; omit to receive a draft"),
    _user: str = Depends(require_auth),
):
    """Delete a CalDAV event by UID — owner-gated and confirmation-gated (destructive)."""

    async def _do():
        return await calendar_dav.delete_event(uid, is_owner=is_owner(_user))

    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="delete_calendar_dav_event", preview=f"Delete calendar event {uid}",
        execute=_do, confirm_token=confirm_token,
    )
    return _apply_outcome(outcome)
