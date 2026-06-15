"""ira/skills/engineer/ — Engineer Mode (4-step diff-first workflow), ported as a Cortex skill (Option A).

Pure persona — no tools/DB. Mirrors agents/engineer_agent.py::build_engineer_prompt.

SECURITY: this skill only PRODUCES diffs (reasoning). The gated local apply pipeline
(git apply -> commit -> docker compose restart) stays in IRA (utils/auto_implement.py,
triggered ONLY by an explicit `architect apply`) and is never invoked here. No remote push.

NOTE: the original persona's codebase quick-reference described the pre-Cortex stack
(LangGraph/vLLM/Docker); refresh it for the Cortex/Ollama layout in a later pass.
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill


def engineer(
    query: str,
    *,
    context: Optional[str] = None,
    owner_name: str = "the owner",
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    blocks = [f"Retrieved context:\n{context}"] if context else None
    return run_skill(
        "engineer", query, context_blocks=blocks, owner_name=owner_name,
        bridge=bridge, session_key=session_key,
    )


__all__ = ["engineer"]
