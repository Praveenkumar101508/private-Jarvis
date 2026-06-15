"""ira/skills/website/ — Business Manager, ported as a Cortex skill (Option A).

IRA keeps the owner-gate and the business_events DB read; the snapshot is passed in.
Mirrors agents/website.py::website_manager.
"""
from __future__ import annotations

import json
from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill


def website(
    query: str,
    *,
    business_summary: Optional[dict] = None,
    memory_context: Optional[str] = None,
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = []
    if business_summary is not None:
        blocks.append(f"Current business snapshot:\n{json.dumps(business_summary, indent=2)}")
    if memory_context:
        blocks.append(f"Relevant past business context:\n{memory_context}")
    return run_skill("website", query, context_blocks=blocks, bridge=bridge, session_key=session_key)


__all__ = ["website"]
