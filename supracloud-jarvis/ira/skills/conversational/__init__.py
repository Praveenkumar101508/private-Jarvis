"""ira/skills/conversational/ — IRA's core personality, ported as a Cortex skill (Option A).

Persona = the grok personality. SKILL.md is a synced snapshot of
agents/grok_personality.py::_GROK_BASE (the canonical source, also used by chat.py and
the Expert Mode supervisor).

History/recall: handled by the Cortex gateway's SESSION memory via `session_key`
(per MERGE_PLAN: "Cortex owns memory") rather than replaying conversation turns. IRA may
still pass long-term `memory_context` during the transition.

NOTE: the old agent switched fast/deep models per request; the gateway currently serves
one configured model, so that distinction isn't preserved here (per-request model
selection at the gateway is a separate enhancement).
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill


def converse(
    query: str,
    *,
    memory_context: Optional[str] = None,
    owner_name: str = "the owner",
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = [f"Relevant context from memory:\n{memory_context}"] if memory_context else None
    return run_skill(
        "conversational", query, context_blocks=blocks, owner_name=owner_name,
        bridge=bridge, session_key=session_key,
    )


__all__ = ["converse"]
