"""
ira/skills/tutor/ — Socratic Tutor, ported as a Cortex skill (Option A).

Persona in SKILL.md. IRA keeps the private submission-evaluator (utils.tutor_tools)
and session memory, passing the private evaluation in as context. Mirrors
agents/tutor.py::tutor_agent, routing the reasoning through the bridge instead of
chat_complete().
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill


def tutor(
    query: str,
    *,
    eval_context: Optional[str] = None,
    memory_context: Optional[str] = None,
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    """Tutor reasoning step: persona (+ IRA-gathered private eval / memory) -> bridge."""
    blocks = []
    if eval_context:
        blocks.append(eval_context)
    if memory_context:
        blocks.append(f"Session history:\n{memory_context}")
    return run_skill("tutor", query, context_blocks=blocks, bridge=bridge, session_key=session_key)


__all__ = ["tutor"]
