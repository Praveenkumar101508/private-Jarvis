"""
SupraCloud Website & Business Manager Agent.
Handles: lead summaries, booking status, content update requests,
         site health reports, and business metric insights.
"""

from __future__ import annotations

import json
import time

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete
from utils.db import acquire

_SYSTEM = """\
You are the Business Manager module of IRA — responsible for SupraCloud's web presence and business operations.

Your scope:
- Summarise incoming leads and bookings with priority ranking
- Generate clear business reports: conversion rates, traffic trends, top lead sources
- Draft content updates (blog posts, landing page copy, CTAs) in SupraCloud's voice
- Flag anomalies: sudden traffic drops, booking cancellations, high-value leads
- Recommend actions to improve conversion and engagement

Tone for all business output: professional, data-driven, and direct.
Tone for all content drafts: confident, innovative, client-focused.

Always quantify where possible. Vague business advice is useless.\
"""


async def _fetch_business_summary() -> dict:
    """Pull recent business events from the database."""
    async with acquire() as conn:
        leads = await conn.fetchval(
            "SELECT COUNT(*) FROM business_events WHERE event_type='lead' AND created_at > NOW() - INTERVAL '7 days'"
        )
        bookings = await conn.fetchval(
            "SELECT COUNT(*) FROM business_events WHERE event_type='booking' AND created_at > NOW() - INTERVAL '7 days'"
        )
        recent = await conn.fetch(
            """SELECT event_type, title, status, created_at
               FROM business_events ORDER BY created_at DESC LIMIT 10"""
        )
    return {
        "leads_last_7d": leads or 0,
        "bookings_last_7d": bookings or 0,
        "recent_events": [
            {"type": r["event_type"], "title": r["title"], "status": r["status"]}
            for r in recent
        ],
    }


async def website_manager(state: IRAState) -> IRAState:
    t0 = time.monotonic()

    summary = await _fetch_business_summary()

    messages = [{"role": "system", "content": _SYSTEM}]
    messages.append({
        "role": "system",
        "content": f"Current business snapshot:\n{json.dumps(summary, indent=2)}",
    })

    if state.get("memory_context"):
        messages.append({
            "role": "system",
            "content": f"Relevant past business context:\n{state['memory_context']}",
        })

    messages.append({"role": "user", "content": state["user_query"]})

    response = await chat_complete(
        messages,
        use_deep=state.get("use_deep_model", False),
        temperature=0.5,
    )

    latency = int((time.monotonic() - t0) * 1000)
    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen-deep" if state.get("use_deep_model") else "llama-fast",
    }
