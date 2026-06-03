"""
ira/subagents/ — multi-agent deliberation (Expert Mode), ported to the Hermes bridge.

Ports agents/expert_mode.py: four specialist role-personas (researcher, critic,
executor, creator) reason over the question through the bridge, then a supervisor
synthesizes one answer. Each role is a reasoning-only call (IRA orchestrates; the
gateway reasons) carrying the same no-tools directive as skills.

Calls run sequentially: the gateway serves ONE local model, so the original
asyncio parallelism (built for multi-endpoint vLLM) gives no speedup here and would
just contend on the single backend. `bridge.deliberate()` delegates to deliberate().
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from hermes_bridge import HermesBridge
from skills._common import _REASONING_DIRECTIVE


def _specialists(owner: str) -> List[Tuple[str, str]]:
    """(label, persona) for the 4 parallel specialists (faithful to expert_mode.py)."""
    return [
        ("🔬 Researcher",
         f"You are the Researcher agent in {owner}'s Expert Mode panel. Role: deep factual "
         "analysis — find authoritative sources and surface data. Start with '🔬 RESEARCHER:' "
         "then 3-5 precise bullet findings (cite specific facts/numbers/sources). "
         "End with 'Confidence: [HIGH/MEDIUM/LOW]'."),
        ("🛡️ Critic",
         f"You are the Critic & Security Guardian in {owner}'s Expert Mode panel. Role: identify "
         "flaws, risks, security issues, missing edge cases, and better alternatives. Start with "
         "'🛡️ CRITIC:'. Be constructive but direct; name specific risks. If none, say so. "
         "End with 'Risk Level: [CRITICAL/HIGH/MEDIUM/LOW/CLEAR]'."),
        ("⚙️ Executor",
         f"You are the Executor & Verifier in {owner}'s Expert Mode panel. Role: practical "
         "verification — would this work, and what are the exact steps? Start with '⚙️ EXECUTOR:' "
         "then step-by-step implementation/verification (correct syntax, real paths/APIs). "
         "End with 'Feasibility: [READY/NEEDS_ADJUSTMENT/BLOCKED]'."),
        ("✨ Creator",
         f"You are the Creator & Synthesizer in {owner}'s Expert Mode panel. Role: produce the best "
         "structured output (code, writing, plan). Start with '✨ CREATOR:' then clean, "
         "production-ready work. End with 'Output Quality: [PRODUCTION/DRAFT/CONCEPT]'."),
    ]


def _supervisor(owner: str) -> str:
    return (
        f"You are the Supervisor & Coordinator for {owner}'s Expert Mode session. You received "
        "analysis from 4 specialist agents. Synthesize their strongest insights, resolve conflicts, "
        "and produce ONE final, polished, definitive answer. Then add an 'Agent Contributions:' list "
        "noting each agent's key insight (🔬 Researcher, 🛡️ Critic, ⚙️ Executor, ✨ Creator). Be decisive."
    )


def deliberate(
    question: str,
    *,
    bridge: Optional[HermesBridge] = None,
    owner_name: str = "the owner",
    memory_context: Optional[str] = None,
) -> str:
    """Run the 5-agent deliberation through the bridge and return the combined response.

    Mirrors agents/expert_mode.py::run_expert_mode: 4 specialists then a supervisor
    synthesis — but every call goes through the out-of-process Hermes gateway.
    """
    bridge = bridge or HermesBridge()
    ctx = f"\n\nRelevant context:\n{memory_context}" if memory_context else ""

    outputs: List[Tuple[str, str]] = []
    for label, persona in _specialists(owner_name):
        system = persona + ctx + "\n\n" + _REASONING_DIRECTIVE
        outputs.append((label, bridge.ask(question, system=system)))

    panel = "\n\n".join(f"=== {label} ===\n{text}" for label, text in outputs)
    synthesis = bridge.ask(
        f"Original question: {question}\n\nThe 4 specialist agents produced:\n\n{panel}\n\n"
        "Synthesize the definitive answer.",
        system=_supervisor(owner_name) + "\n\n" + _REASONING_DIRECTIVE,
    )

    body = "\n\n---\n\n".join(text for _, text in outputs)
    return (
        "## Expert Mode — Collaborative Analysis\n\n"
        f"{body}\n\n---\n\n## 🧠 Supervisor Synthesis\n\n{synthesis}"
    )


__all__ = ["deliberate"]
