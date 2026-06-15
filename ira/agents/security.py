"""
Security Guardian Agent — real-time threat analysis, log review, vulnerability assessment.

Reads recent security events from the database, analyses them, and provides
actionable recommendations. Always uses the deep model for accuracy.
"""

from __future__ import annotations

import time
import json

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete
from utils.db import acquire

_SYSTEM = """\
You are the Security Guardian module of IRA — an elite cybersecurity analyst and incident responder.

Your responsibilities:
- Analyse security logs and events for anomalies, intrusion attempts, and policy violations
- Classify threats by severity: INFO / LOW / MEDIUM / HIGH / CRITICAL
- Provide precise, actionable remediation steps — not vague advice
- Prioritise ruthlessly: address CRITICAL and HIGH threats first
- When you find a pattern (repeated IPs, timing correlation, lateral movement), call it out explicitly
- Recommend prevention measures after resolving immediate threats

Format every security report as:
  🔴 CRITICAL / 🟠 HIGH / 🟡 MEDIUM / 🟢 LOW / ℹ️ INFO
  [Threat name]: [1-line description]
  Impact: [what could happen]
  Action: [exact steps to take]

Be direct. Lives and systems depend on fast, accurate assessment.\
"""


async def _fetch_recent_events(limit: int = 20) -> list[dict]:
    """Pull the most recent unresolved security events from the database."""
    async with acquire() as conn:
        rows = await conn.fetch(
            """SELECT severity, event_type, source_ip, description, created_at
               FROM security_events
               WHERE resolved = FALSE
               ORDER BY created_at DESC
               LIMIT $1""",
            limit,
        )
    return [
        {
            "severity": r["severity"],
            "type": r["event_type"],
            "source_ip": str(r["source_ip"]) if r["source_ip"] else "unknown",
            "description": r["description"],
            "time": r["created_at"].isoformat(),
        }
        for r in rows
    ]


async def security_guardian(state: IRAState) -> IRAState:
    t0 = time.monotonic()

    recent_events = await _fetch_recent_events()

    messages = [{"role": "system", "content": _SYSTEM}]

    if recent_events:
        events_text = json.dumps(recent_events, indent=2)
        messages.append({
            "role": "system",
            "content": f"Current unresolved security events ({len(recent_events)} total):\n{events_text}",
        })
    else:
        messages.append({
            "role": "system",
            "content": "No unresolved security events in the database at this time.",
        })

    if state.get("memory_context"):
        messages.append({
            "role": "system",
            "content": f"Related past security context:\n{state['memory_context']}",
        })

    messages.append({"role": "user", "content": state["user_query"]})

    response = await chat_complete(messages, use_deep=True, temperature=0.2)

    latency = int((time.monotonic() - t0) * 1000)
    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen-deep",
    }
