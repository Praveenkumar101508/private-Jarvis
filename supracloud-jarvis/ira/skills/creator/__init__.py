"""ira/skills/creator/ — Meta Agent Creator, ported as a Hermes skill (Option A).

IRA keeps the DB persistence of generated agents (_save_agent -> agents table).

NOTE (flagged for review): the original persona targets LangGraph agents. Since the
merge retires LangGraph, this skill should likely be modernized to generate Hermes
SKILL.md skills instead — a deliberate future change, NOT part of this faithful port.
The persona here is generalized ("agent engineer") but otherwise preserved.
"""
from __future__ import annotations

from typing import Optional

from hermes_bridge import HermesBridge
from skills._common import run_skill


def create_agent(
    query: str,
    *,
    memory_context: Optional[str] = None,
    bridge: Optional[HermesBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = (
        [f"Previously created agents (for reference):\n{memory_context}"]
        if memory_context else None
    )
    return run_skill("creator", query, context_blocks=blocks, bridge=bridge, session_key=session_key)


__all__ = ["create_agent"]
