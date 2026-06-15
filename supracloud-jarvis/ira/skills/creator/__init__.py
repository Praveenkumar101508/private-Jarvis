"""ira/skills/creator/ — Meta Skill Creator, a Cortex skill (Option A).

Modernized for the Cortex architecture: the persona now generates **Cortex skills**
(SKILL.md + optional scripts, agentskills.io format) instead of LangGraph agents (the
original target) — matching how IRA's own agents were ported. IRA keeps the DB
persistence of generated skills (_save_agent -> agents table).
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill


def create_skill(
    query: str,
    *,
    memory_context: Optional[str] = None,
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = (
        [f"Previously created skills (for reference):\n{memory_context}"]
        if memory_context else None
    )
    return run_skill("creator", query, context_blocks=blocks, bridge=bridge, session_key=session_key)


__all__ = ["create_skill"]
