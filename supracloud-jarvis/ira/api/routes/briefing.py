"""Briefing endpoints — trigger and retrieve IRA's briefings."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from api.middleware.auth import require_auth
from utils.db import acquire

router = APIRouter(prefix="/briefing", tags=["briefing"])


@router.post("/now")
async def trigger_briefing(
    briefing_type: str = Query("morning", regex="^(morning|evening|security|business)$"),
    _user: str = Depends(require_auth),
):
    """Trigger an immediate briefing. Runs asynchronously and delivers via all channels."""
    import asyncio
    import logging as _log
    from worker.briefing import generate_briefing
    # Fire and forget — keep reference so task isn't silently GC'd
    _t = asyncio.create_task(generate_briefing(briefing_type))
    _t.add_done_callback(lambda t: t.exception() and _log.getLogger("ira.briefing").warning(f"Briefing task failed: {t.exception()}"))
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
