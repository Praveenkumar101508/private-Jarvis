"""
Experimental Android actuator endpoints — OFF by default.

GET    /api/v1/android/screen   — read + sanitise the current screen (owner-only)
POST   /api/v1/android/act      — perform ONE action (owner + confirmation gated)

The whole surface is inert unless `android_actuator_enabled` is True: both
endpoints return {"status": "disabled"} when the flag is off. Actuation is
destructive, so it goes through the approval guardrail (owner + explicit
confirmation), and screen reads are owner-only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from actions import android_actuator
from api.middleware.auth import require_auth, is_owner
from utils.approval import owner_gated_action

router = APIRouter(prefix="/android", tags=["android"])


class ActionRequest(BaseModel):
    action: str = Field(..., description="tap | swipe | type | key")
    params: dict = Field(default_factory=dict)
    confirm_token: str | None = Field(None, description="Approval token; omit to receive a draft")


@router.get("/screen")
async def read_screen(_user: str = Depends(require_auth)):
    """Read the current Android screen — owner-only, read-only, sanitised."""
    if not is_owner(_user):
        raise HTTPException(status_code=403, detail="The Android actuator is restricted to the verified owner.")
    return await android_actuator.read_screen()


@router.post("/act")
async def perform_action(body: ActionRequest, _user: str = Depends(require_auth)):
    """Perform one Android action — owner-gated and confirmation-gated (destructive)."""

    async def _do():
        return await android_actuator.act(body.action, **body.params)

    preview = f"Android action: {body.action} {body.params}"
    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="android_act", preview=preview, execute=_do,
        confirm_token=body.confirm_token,
    )
    if outcome["status"] == "forbidden":
        raise HTTPException(status_code=403, detail=outcome["detail"])
    if outcome["status"] in ("expired", "not_found"):
        raise HTTPException(status_code=409, detail=outcome["detail"])
    if outcome["status"] == "executed":
        return outcome["result"]
    return outcome  # confirmation_required
