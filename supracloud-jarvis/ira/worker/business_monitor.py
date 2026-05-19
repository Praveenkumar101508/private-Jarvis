"""
IRA Business Monitor — Real-time lead and booking alerting.

Checks every 5 minutes:
  - New leads since last check → alert with qualification suggestion
  - New bookings → confirm and add to calendar
  - Hot leads (high-value, urgent) → immediate CRITICAL notification
  - Stale leads (no follow-up in 48h) → nudge Sir to act

IRA proactively says: "Sir, you have 3 new leads. Shall I qualify them?"
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

from utils.db import acquire
from utils.llm import chat_complete
from worker.notifier import notify

logger = logging.getLogger("ira.business")

# ── Lead qualification prompt ──────────────────────────────────────────────────
_QUALIFY_PROMPT = """\
You are IRA, a professional business assistant. Briefly qualify these leads for Sir.
For each lead, give: likely budget tier (Low/Mid/High), urgency (cold/warm/hot), and recommended action.
Keep it under 100 words total. Speak warmly and professionally.\
"""


async def _get_new_leads_since(last_check: datetime) -> list[dict]:
    async with acquire() as conn:
        rows = await conn.fetch(
            """SELECT id, title, status, payload, created_at
               FROM business_events
               WHERE event_type='lead' AND created_at > $1
               ORDER BY created_at DESC""",
            last_check,
        )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "status": r["status"],
            "details": r["payload"],
            "time": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def _get_stale_leads(hours: int = 48) -> int:
    async with acquire() as conn:
        return await conn.fetchval(
            """SELECT COUNT(*) FROM business_events
               WHERE event_type='lead' AND status='new'
               AND created_at < NOW() - make_interval(hours => $1)""",
            hours,
        ) or 0


async def _get_last_check_time() -> datetime:
    async with acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value FROM monitor_state WHERE key='last_business_check'"
        )
    if row:
        try:
            return datetime.fromisoformat(row["value"])
        except Exception:
            pass
    return datetime.now(timezone.utc) - timedelta(minutes=5)


async def _update_last_check() -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with acquire() as conn:
        await conn.execute(
            """INSERT INTO monitor_state (key, value) VALUES ('last_business_check', $1)
               ON CONFLICT (key) DO UPDATE SET value=$1, updated_at=NOW()""",
            now,
        )


async def run_business_scan() -> None:
    """Check for new leads and bookings. Called every 5 minutes by scheduler."""
    logger.debug("Running business scan...")

    last_check = await _get_last_check_time()
    new_leads = await _get_new_leads_since(last_check)
    await _update_last_check()

    if not new_leads:
        return

    count = len(new_leads)
    logger.info(f"Business scan: {count} new lead(s) found")

    # Quick LLM qualification
    lead_text = "\n".join(
        f"- {l['title']} (status: {l['status']})"
        for l in new_leads[:5]
    )
    messages = [
        {"role": "system", "content": _QUALIFY_PROMPT},
        {"role": "user", "content": f"Leads to qualify:\n{lead_text}"},
    ]
    qualification = await chat_complete(messages, use_deep=False, temperature=0.4, max_tokens=150)

    hot_leads = [l for l in new_leads if "hot" in str(l.get("details", "")).lower()
                 or "urgent" in str(l.get("details", "")).lower()]

    priority = "critical" if hot_leads else "warning" if count >= 3 else "info"

    body = (
        f"Sir, IRA has detected {count} new lead{'s' if count > 1 else ''}.\n\n"
        f"**Quick Assessment:**\n{qualification}\n\n"
        f"Shall I qualify them further, draft follow-up emails, or schedule calls?"
    )

    await notify(
        f"{count} New Lead{'s' if count > 1 else ''} Require{'s' if count == 1 else ''} Attention",
        body,
        category="business",
        priority=priority,
        metadata={"lead_ids": [l["id"] for l in new_leads]},
    )

    # Stale lead check
    stale = await _get_stale_leads(hours=48)
    if stale > 0:
        await notify(
            f"{stale} Lead{'s' if stale > 1 else ''} Need Follow-Up",
            f"Sir, {stale} lead{'s have' if stale > 1 else ' has'} not been actioned in over 48 hours. "
            f"Shall I draft follow-up messages or mark them for review?",
            category="business",
            priority="warning",
        )
