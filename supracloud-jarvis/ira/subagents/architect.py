"""
ira/subagents/architect.py — IRA Evolution Team debate, ported to the Cortex bridge.

Ports agents/architect_agent.py::stream_architect_proposal: a 5-agent debate
(Researcher + Creator in wave 1; Critic + Executor in wave 2 with wave-1 context;
Supervisor synthesises a final proposal). Reasoning-only, through the bridge,
sequential (one gateway model). Streaming/Redis storage stay an IRA concern.

The gated apply pipeline (git apply -> commit -> docker restart) is NOT here — it
lives in utils/auto_implement.py and only runs on an explicit `architect apply`
(is_apply_trigger in chat.py). This module proposes; the code-gen is skills/architect.
"""
from __future__ import annotations

from typing import Optional

from cortex_bridge import CortexBridge

# Capability map the team reasons over (kept in sync with agents/architect_agent.py).
IRA_CAPABILITY_MAP = {
    "implemented": [
        "Multi-agent Expert Mode (5 parallel agents)",
        "Real-time web + X/Twitter search",
        "Image generation / editing / vision",
        "Voice interface (LiveKit + Whisper + Kokoro TTS)",
        "Engineer Mode (4-step diff workflow)",
        "Grok personality + persistent memory (RAG)",
        "Biometric voice verification (ECAPA-TDNN)",
        "Self-healing + gated local apply pipeline",
    ],
    "missing": [
        "Persistent file storage between sessions",
        "Calendar write-back (Google Calendar / Cal.com)",
        "Multi-user profiles, memories, and permissions",
        "Proactive email drafting for review",
        "Playwright auto-apply job pipeline",
        "Mobile push notifications beyond Telegram",
        "Long-term goal tracking + weekly progress reports",
    ],
    "unique_ira_advantages": [
        "Fully private, 100% self-hosted (sovereign)",
        "Biometric voice gate on sensitive commands",
        "Self-healing with human-gated apply",
        "24/7 Evolution Team proposing features",
    ],
}


def _capability_context() -> str:
    impl = "\n".join(f"  - {f}" for f in IRA_CAPABILITY_MAP["implemented"])
    miss = "\n".join(f"  - {f}" for f in IRA_CAPABILITY_MAP["missing"])
    uniq = "\n".join(f"  - {f}" for f in IRA_CAPABILITY_MAP["unique_ira_advantages"])
    return (
        f"IRA already has:\n{impl}\n\nFeatures still missing:\n{miss}\n\n"
        f"IRA's unique advantages:\n{uniq}"
    )


def _researcher(owner: str) -> str:
    return (
        f"You are the RESEARCHER in {owner}'s IRA Evolution Team. Pick the TOP 3 most impactful "
        "missing features; for each, compare what Grok/the assistant/Gemini/ChatGPT do vs IRA's gap, and "
        "give one UNIQUE angle. Format: '🔬 RESEARCHER:' then Priority 1/2/3 (3 sentences each), "
        "then 'Verdict: [which most changes the daily workflow]'."
    )


def _creator(owner: str) -> str:
    return (
        f"You are the CREATOR / VISIONARY in {owner}'s IRA Evolution Team. Invent 2 features NO other "
        "AI offers, buildable on IRA's stack, each a genuine superpower (combine IRA's unique "
        "advantages). Format: '✨ CREATOR:' then Invention 1/2 (concept, uniqueness, daily use case), "
        "then 'Innovation Score: BREAKTHROUGH|HIGH|MEDIUM'."
    )


def _critic(owner: str) -> str:
    return (
        f"You are the CRITIC / RISK GUARDIAN in {owner}'s IRA Evolution Team. For each proposed "
        "feature: implementation complexity (1-10), what could break, maintenance burden for a "
        "single-person system, the 20%-effort/80%-value cut, and whether to REJECT it now. "
        "Format: '🛡️ CRITIC:' per-feature analysis, then 'Top Pick' and 'REJECT List'."
    )


def _executor(owner: str) -> str:
    return (
        f"You are the EXECUTOR / LEAD ENGINEER in {owner}'s IRA Evolution Team. For the top 2 features "
        "after the Critic: exact files to create/modify, libraries needed, new services/env vars, a "
        "realistic time estimate, and a short implementation sketch for the #1 pick. Format: "
        "'⚙️ EXECUTOR:' then #1/#2 picks, 'Recommendation', 'Feasibility: READY|NEEDS_PREP|BLOCKED'."
    )


def _supervisor(owner: str) -> str:
    return (
        f"You are the SUPERVISOR of {owner}'s IRA Evolution Team. From the full debate, produce the "
        "FINAL PROPOSAL: 🏆 Recommendation (1 feature + justification), 📊 Debate Summary (2-3 lines/agent), "
        "🔍 Feature Details + competitor comparison, 💡 IRA's Unique Angle, 🛠️ Implementation Plan "
        "(5-8 steps), 📦 Requirements, ⏱️ Effort, ⚠️ Risks + mitigations, 🥈 Alternatives. End with an "
        "approval block instructing the owner to reply `architect implement: [feature]` to approve "
        "(nothing is implemented without that explicit approval)."
    )


def architect_proposal(
    trigger: str = "Analyse IRA's current capabilities and propose the most valuable next feature.",
    *,
    bridge: Optional[CortexBridge] = None,
    owner_name: str = "the owner",
    memory_context: Optional[str] = None,
) -> str:
    """Run the 5-agent evolution-team debate through the bridge; return debate + proposal."""
    bridge = bridge or CortexBridge()
    ctx = _capability_context() + (f"\n\nMemory context:\n{memory_context}" if memory_context else "")
    user = f"Perform a complete feature proposal cycle for {owner_name}'s IRA. Context: {trigger}"

    # Wave 1 — Researcher + Creator (capability-map context)
    researcher = bridge.ask(user, system=_researcher(owner_name) + "\n\n" + ctx, reasoning_only=True)
    creator = bridge.ask(user, system=_creator(owner_name) + "\n\n" + ctx, reasoning_only=True)
    wave1 = f"RESEARCHER OUTPUT:\n{researcher}\n\nCREATOR OUTPUT:\n{creator}"

    # Wave 2 — Critic + Executor (have wave-1 context)
    critic = bridge.ask(user, system=_critic(owner_name) + "\n\nPrevious debate:\n" + wave1, reasoning_only=True)
    executor = bridge.ask(user, system=_executor(owner_name) + "\n\nPrevious debate:\n" + wave1, reasoning_only=True)

    debate = (
        f"=== 🔬 RESEARCHER ===\n{researcher}\n\n=== ✨ CREATOR ===\n{creator}\n\n"
        f"=== 🛡️ CRITIC ===\n{critic}\n\n=== ⚙️ EXECUTOR ===\n{executor}"
    )
    proposal = bridge.ask(
        f"{user}\n\nFull team debate:\n{debate}\n\nSynthesise the final proposal.",
        system=_supervisor(owner_name), reasoning_only=True,
    )
    return f"# 🏛️ IRA Evolution Team — Feature Proposal\n\n{debate}\n\n---\n\n## 🧠 Supervisor Proposal\n\n{proposal}"


__all__ = ["architect_proposal", "IRA_CAPABILITY_MAP"]
