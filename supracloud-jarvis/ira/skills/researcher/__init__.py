"""ira/skills/researcher/ — deep research & analysis, ported as a Cortex skill (Option A).

No IRA tools/DB — persona + memory only. Mirrors agents/researcher.py, routing the
reasoning through the bridge instead of chat_complete().
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill


def research(
    query: str,
    *,
    memory_context: Optional[str] = None,
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = [f"Relevant past context:\n{memory_context}"] if memory_context else None
    return run_skill("researcher", query, context_blocks=blocks, bridge=bridge, session_key=session_key)


__all__ = ["research"]
