"""
Local-first notes endpoints (on-disk markdown — no cloud, no database).

GET    /api/v1/notes            — list notes (or ?q= to search)
GET    /api/v1/notes/{note_id}  — read one note (with body)
POST   /api/v1/notes            — create a note (local write, not destructive)
DELETE /api/v1/notes/{note_id}  — delete a note (owner-gated + confirmation-gated)

Create/read are non-destructive and run directly. Delete is the only destructive
op, so it goes through the approval guardrail (owner + explicit confirmation).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from actions import notes as notes_store
from api.middleware.auth import require_auth, is_owner
from utils.approval import owner_gated_action

router = APIRouter(prefix="/notes", tags=["notes"])


class CreateNoteRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = Field("", max_length=100_000)
    tags: list[str] = Field(default_factory=list)


@router.get("")
async def list_or_search_notes(
    q: str | None = Query(None, description="Optional substring search"),
    _user: str = Depends(require_auth),
):
    """List note metadata, or search across title/body/tags when ?q= is given."""
    items = notes_store.search_notes(q) if q else notes_store.list_notes()
    return {"notes": items, "count": len(items)}


@router.get("/{note_id}")
async def read_note(note_id: str, _user: str = Depends(require_auth)):
    """Read a single note (with body)."""
    note = notes_store.get_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail=f"Note {note_id!r} not found.")
    return note


@router.post("")
async def create_note(body: CreateNoteRequest, _user: str = Depends(require_auth)):
    """Create a note on local disk (non-destructive local write)."""
    return notes_store.create_note(title=body.title, body=body.body, tags=body.tags)


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    confirm_token: str | None = Query(None, description="Approval token; omit to receive a draft"),
    _user: str = Depends(require_auth),
):
    """Delete a note — owner-gated and confirmation-gated (destructive)."""

    def _do():
        return notes_store.delete_note(note_id)

    outcome = await owner_gated_action(
        owner_username=_user, is_owner=is_owner(_user),
        action="delete_note", preview=f"Delete note {note_id!r} (cannot be undone)",
        execute=_do, confirm_token=confirm_token,
    )
    if outcome["status"] == "forbidden":
        raise HTTPException(status_code=403, detail=outcome["detail"])
    if outcome["status"] in ("expired", "not_found"):
        raise HTTPException(status_code=409, detail=outcome["detail"])
    if outcome["status"] == "executed":
        return outcome["result"]
    return outcome  # confirmation_required
