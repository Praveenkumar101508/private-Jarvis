"""ira/skills/digital/ — Digital Brain, ported as a Cortex skill (Option A).

IRA keeps the OS/browser tools (os_tools.open_application/run_terminal_command,
browser_tools.browse_and_summarize_website); their results are passed in as context.
Mirrors agents/digital.py::digital_agent.
"""
from __future__ import annotations

import json
from typing import Optional, Sequence

from cortex_bridge import CortexBridge
from skills._common import run_skill


def digital(
    query: str,
    *,
    tool_results: Optional[Sequence[dict]] = None,
    memory_context: Optional[str] = None,
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = []
    if tool_results:
        blocks.append(f"Tool execution results:\n{json.dumps(list(tool_results), indent=2)[:4000]}")
    if memory_context:
        blocks.append(f"Memory:\n{memory_context}")
    return run_skill("digital", query, context_blocks=blocks, bridge=bridge, session_key=session_key)


__all__ = ["digital"]
