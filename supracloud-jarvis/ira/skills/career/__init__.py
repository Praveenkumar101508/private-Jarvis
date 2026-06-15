"""ira/skills/career/ — career automation, ported as a Cortex skill (Option A).

IRA runs utils.career_tools (codebase analysis / job scrape / resume tailoring) and
passes the results in as context. Mirrors agents/career.py.
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

from cortex_bridge import CortexBridge
from skills._common import run_skill


def career(
    query: str,
    *,
    tool_results: Optional[Sequence[dict]] = None,
    memory_context: Optional[str] = None,
    owner_name: str = "the owner",
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = []
    if tool_results:
        blocks.append(f"Tool execution results:\n{json.dumps(list(tool_results), indent=2)[:4000]}")
    if memory_context:
        blocks.append(f"Relevant memory:\n{memory_context}")
    return run_skill(
        "career", query, context_blocks=blocks, owner_name=owner_name,
        bridge=bridge, session_key=session_key,
    )


__all__ = ["career"]
