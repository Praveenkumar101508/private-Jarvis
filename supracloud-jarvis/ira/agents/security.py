"""
Security Guardian Agent — real-time threat analysis, active security tools, bodyguard mode.

Reads recent security events from the database, analyses them, and provides
actionable recommendations. When the user requests active operations (scan, lockdown,
dispatch message), executes the corresponding tool before responding.
"""

from __future__ import annotations

import re
import time
import json

from langchain_core.messages import AIMessage

from agents.state import IRAState
from utils.llm import chat_complete
from utils.db import acquire
from config import get_settings

def _build_system(owner_name: str) -> str:
    return (
        f"You are the primary security overwatch and personal digital bodyguard for {owner_name}.\n\n"
        "Your responsibilities:\n"
        "- Analyse security logs and events for anomalies, intrusion attempts, and policy violations\n"
        "- Classify threats by severity: INFO / LOW / MEDIUM / HIGH / CRITICAL\n"
        "- Provide precise, actionable remediation steps — not vague advice\n"
        "- Prioritise ruthlessly: address CRITICAL and HIGH threats first\n"
        "- When you find a pattern (repeated IPs, timing correlation, lateral movement), call it out explicitly\n"
        f"- If asked to scan for threats, lock down the system, or send a secure message — execute immediately without hesitation\n"
        f"- Prioritise extreme security and privacy for {owner_name} at all times\n\n"
        "Format every security report as:\n"
        "  🔴 CRITICAL / 🟠 HIGH / 🟡 MEDIUM / 🟢 LOW / ℹ️ INFO\n"
        "  [Threat name]: [1-line description]\n"
        "  Impact: [what could happen]\n"
        "  Action: [exact steps to take]\n\n"
        "Be direct. This is a high-security environment."
    )

# ── Intent patterns for active tool dispatch ─────────────────────────────────

_SCAN_RE = re.compile(
    r"\b(scan|check|inspect|monitor|look for|detect).{0,30}(threat|network|connect|ip|intru|hack)",
    re.I,
)
_LOCKDOWN_RE = re.compile(
    r"\b(lock\s*down|lockdown|engage\s+lock|initiate\s+lock|secure\s+mode|panic|emergency\s+lock)",
    re.I,
)
_LIFT_RE = re.compile(
    r"\b(lift|remove|disengage|cancel|end|stop).{0,20}(lock\s*down|lockdown|lock)",
    re.I,
)
_DISPATCH_RE = re.compile(
    r"\b(text|message|send|tell|notify|alert).{0,30}(phone|telegram|pocket|me\b)",
    re.I,
)


# Module-level constant required by chat.py streaming router
_SYSTEM = _build_system(get_settings().owner_name)


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
    if not state.get("is_owner"):
        return {**state, "response": "I can only perform security operations for the verified owner."}

    t0 = time.monotonic()
    query = state["user_query"]
    tool_output: str = ""
    _SYSTEM = _build_system(get_settings().owner_name)

    # ── Active tool dispatch (runs before LLM so result enriches the prompt) ──
    try:
        from utils.security_tools import (
            scan_threats,
            initiate_lockdown,
            lift_lockdown,
            dispatch_secure_message,
        )

        if _LOCKDOWN_RE.search(query):
            result = await initiate_lockdown(reason=f"voice/chat command: {query[:80]}")
            tool_output = f"[LOCKDOWN TOOL RESULT]\n{json.dumps(result, indent=2)}"

        elif _LIFT_RE.search(query):
            result = await lift_lockdown()
            tool_output = f"[LIFT LOCKDOWN RESULT]\n{json.dumps(result, indent=2)}"

        elif _SCAN_RE.search(query):
            result = await scan_threats()
            tool_output = f"[NETWORK SCAN RESULT]\n{json.dumps(result, indent=2)}"

        elif _DISPATCH_RE.search(query):
            # Extract the message content after the trigger phrase
            msg_match = re.search(
                r"(?:text|message|send|tell|notify|alert).{0,30}(?:phone|telegram|pocket|me)[,:\s]+(.+)",
                query,
                re.I | re.S,
            )
            msg_body = msg_match.group(1).strip() if msg_match else query
            result = await dispatch_secure_message(msg_body)
            tool_output = f"[DISPATCH RESULT]\n{json.dumps(result, indent=2)}"

    except Exception as e:
        tool_output = f"[TOOL ERROR] {e}"

    # ── Fetch recent security events ─────────────────────────────────────────
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

    if tool_output:
        messages.append({
            "role": "system",
            "content": f"Active tool execution result (just ran):\n{tool_output}",
        })

    if state.get("memory_context"):
        messages.append({
            "role": "system",
            "content": f"Related past security context:\n{state['memory_context']}",
        })

    messages.append({"role": "user", "content": query})

    response = await chat_complete(messages, use_deep=True, temperature=0.2)

    latency = int((time.monotonic() - t0) * 1000)
    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen-deep",
    }
