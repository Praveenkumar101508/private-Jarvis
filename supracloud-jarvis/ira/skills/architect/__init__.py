"""ira/skills/architect/ — Architect: feature proposals + code-gen, ported (Option A).

- propose() runs the 5-agent Evolution-Team debate (ira/subagents/architect.py) through the bridge.
- implement() is the code-gen step: produces an implementation as unified diffs (reasoning only).

SECURITY (Guardrail 5): diffs are NEVER applied here. The gated apply pipeline
(git apply → commit → docker compose restart) stays in IRA (utils/auto_implement.py) and runs
ONLY on an explicit human `architect apply` (is_apply_trigger in api/routes/chat.py). No remote push.
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge
from skills._common import run_skill
from subagents.architect import architect_proposal


def propose(
    trigger: str = "Analyse IRA's current capabilities and propose the most valuable next feature.",
    *,
    bridge: Optional[CortexBridge] = None,
    owner_name: str = "the owner",
    memory_context: Optional[str] = None,
) -> str:
    """5-agent Evolution-Team debate → feature proposal (delegates to subagents.architect)."""
    return architect_proposal(trigger, bridge=bridge, owner_name=owner_name, memory_context=memory_context)


def implement(
    feature_name: str,
    *,
    proposal_context: str = "",
    bridge: Optional[CortexBridge] = None,
    session_key: Optional[str] = None,
) -> str:
    """Code-gen for an approved feature: produce unified diffs (reasoning only; IRA applies, gated)."""
    blocks = []
    if proposal_context:
        blocks.append(f"Context from the approved proposal:\n{proposal_context[:4000]}")
    return run_skill(
        "architect",
        f"Implement the feature: {feature_name}. Output complete unified diffs.",
        context_blocks=blocks, bridge=bridge, session_key=session_key,
    )


__all__ = ["propose", "implement"]
