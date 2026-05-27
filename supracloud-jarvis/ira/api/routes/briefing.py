"""Briefing endpoints — trigger and retrieve IRA's briefings."""

from __future__ import annotations

import asyncio
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.middleware.auth import require_auth
from utils.db import acquire

router = APIRouter(prefix="/briefing", tags=["briefing"])

# Fix #91: keep strong references to background briefing tasks so Python's
# garbage collector cannot collect them before they finish.  The asyncio
# event loop only keeps a *weak* reference to tasks; without a live strong
# reference the task can be silently dropped mid-execution.
_background_tasks: set[asyncio.Task] = set()


@router.post("/now")
async def trigger_briefing(
    briefing_type: str = Query("morning", regex="^(morning|evening|security|business)$"),
    _user: str = Depends(require_auth),
):
    """Trigger an immediate briefing. Runs asynchronously and delivers via all channels."""
    import logging as _log
    from worker.briefing import generate_briefing

    # Fix #91: store in module-level set so the task cannot be GC'd before it
    # finishes.  The discard callback removes it once done to avoid the set
    # growing unbounded.
    _t = asyncio.create_task(generate_briefing(briefing_type))
    _background_tasks.add(_t)
    _t.add_done_callback(_background_tasks.discard)
    _t.add_done_callback(
        lambda t: t.exception() and _log.getLogger("ira.briefing").warning(
            f"Briefing task failed: {t.exception()}"
        )
    )
    return {"status": "generating", "message": "IRA is preparing your briefing now, Sir."}


@router.get("/latest")
async def get_latest(
    briefing_type: str = Query("morning"),
    _user: str = Depends(require_auth),
):
    """Retrieve the most recent briefing of a given type."""
    async with acquire() as conn:
        row = await conn.fetchrow(
            """SELECT id, briefing_type, content, summary, created_at
               FROM briefings WHERE briefing_type=$1
               ORDER BY created_at DESC LIMIT 1""",
            briefing_type,
        )
    if not row:
        return {"message": "No briefings found yet. Trigger one with POST /briefing/now"}
    return {
        "id": str(row["id"]),
        "type": row["briefing_type"],
        "content": row["content"],
        "summary": row["summary"],
        "created_at": row["created_at"].isoformat(),
    }


@router.get("/history")
async def briefing_history(
    limit: int = Query(10, le=50),
    _user: str = Depends(require_auth),
):
    async with acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, briefing_type, summary, created_at FROM briefings
               ORDER BY created_at DESC LIMIT $1""",
            limit,
        )
    return [
        {
            "id": str(r["id"]),
            "type": r["briefing_type"],
            "summary": r["summary"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]
