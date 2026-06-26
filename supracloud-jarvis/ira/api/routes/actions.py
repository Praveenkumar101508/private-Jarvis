"""
Action endpoints that need the approval guardrail.

POST /api/v1/actions/email — send an email (owner-gated + confirmation-gated).
  Without confirm_token: returns a draft (preview + token), sending nothing.
  With a valid token: sends via SMTP, failing soft if SMTP isn't configured.

GET  /api/v1/actions       — the v1 action set with each action's configured status.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from actions import action_status
from actions.email_triage import fetch_recent
from api.middleware.auth import require_auth, is_owner
from utils.approval import owner_gated_action
from utils.email_send import send_email

router = APIRouter(prefix="/actions", tags=["actions"])


class EmailRequest(BaseModel):
    to: str
    subject: str
    body: str
    confirm_token: str | None = None


@router.get("")
async def list_action_status(_user: str = Depends(require_auth)):
    """Report which v1 actions are configured (fail-soft introspection)."""
    return {"actions": action_status()}


@router.get("/email/triage")
async def email_triage(
    limit: int = 10,
    _user: str = Depends(require_auth),
):
    """Read-only IMAP inbox triage. Owner-only; sanitises all fetched content.

    Returns recent messages with each field wrapped as untrusted external data,
    plus any prompt-injection patterns detected (audit). Never marks, moves,
    deletes, or replies — sending stays behind POST /actions/email.
    """
    if not is_owner(_user):
        raise HTTPException(status_code=403, detail="Inbox triage is restricted to the verified owner.")
    limit = max(1, min(int(limit), 50))
    return await fetch_recent(limit=limit, is_owner=is_owner(_user))


@router.post("/email")
async def send_email_action(body: EmailRequest, _user: str = Depends(require_auth)):
    """Send an email behind the owner-gate + approval guardrail (high-stakes)."""

    async def _do():
        # send_email fails soft (returns a status dict) — never raises.
        return await send_email(to=body.to, subject=body.subject, body=body.body)

    preview = f"Send email to {body.to}\nSubject: {body.subject}\n\n{body.body}"
    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="send_email", preview=preview, execute=_do,
        confirm_token=body.confirm_token,
    )
    if outcome["status"] == "forbidden":
        raise HTTPException(status_code=403, detail=outcome["detail"])
    if outcome["status"] in ("expired", "not_found"):
        raise HTTPException(status_code=409, detail=outcome["detail"])
    if outcome["status"] == "executed":
        return outcome["result"]      # {"status": "sent" | "not_configured" | "error", ...}
    return outcome                    # confirmation_required
