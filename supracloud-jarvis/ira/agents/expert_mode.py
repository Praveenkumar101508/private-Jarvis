"""
IRA Expert Mode — Grok-style 5-agent parallel collaboration.

When Expert Mode is enabled, 5 specialist agents run simultaneously, share
their findings, debate, and produce a single polished answer with citations.

Agents:
  1. researcher        — deep factual research, sources, data
  2. critic            — identifies flaws, security issues, alternatives
  3. executor          — tool execution, code testing, verification
  4. creator           — synthesis, writing, structured output
  5. supervisor        — coordinates all, produces final answer

All 5 agents run in true parallel via asyncio.gather(). Results are combined
by the supervisor into a single response with inline citations from each agent.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from agents.state import IRAState
from utils.llm import chat_complete, stream_tokens
from config import get_settings

logger = logging.getLogger("ira.expert_mode")


# ── Expert agent system prompts ───────────────────────────────────────────────

def _researcher_prompt(owner: str) -> str:
    return (
        f"You are the Researcher agent in {owner}'s Expert Mode panel.\n"
        "Your role: deep factual analysis, find authoritative sources, surface data.\n"
        "Format: Start with '🔬 RESEARCHER:' then your findings in 3-5 bullet points.\n"
        "Be precise — cite specific facts, numbers, and sources when possible.\n"
        "End with: 'Confidence: [HIGH/MEDIUM/LOW]'"
    )


def _critic_prompt(owner: str) -> str:
    return (
        f"You are the Critic & Security Guardian in {owner}'s Expert Mode panel.\n"
        "Your role: identify flaws, risks, security issues, missing edge cases, and better alternatives.\n"
        "Format: Start with '🛡️ CRITIC:' then your analysis.\n"
        "Be constructive but direct — name specific risks and vulnerabilities.\n"
        "If you find no critical issues, state that clearly.\n"
        "End with: 'Risk Level: [CRITICAL/HIGH/MEDIUM/LOW/CLEAR]'"
    )


def _executor_prompt(owner: str) -> str:
    return (
        f"You are the Executor & Verifier in {owner}'s Expert Mode panel.\n"
        "Your role: practical verification — would this actually work? What are the exact implementation steps?\n"
        "Format: Start with '⚙️ EXECUTOR:' then step-by-step implementation or verification.\n"
        "Focus on: correct syntax, working commands, actual file paths, real APIs.\n"
        "If you need to call a tool to verify — describe exactly what you would run.\n"
        "End with: 'Feasibility: [READY/NEEDS_ADJUSTMENT/BLOCKED]'"
    )


def _creator_prompt(owner: str) -> str:
    return (
        f"You are the Creator & Synthesizer in {owner}'s Expert Mode panel.\n"
        "Your role: generate the best possible structured output — code, writing, plans, creative solutions.\n"
        "Format: Start with '✨ CREATOR:' then your synthesized output.\n"
        "Produce clean, production-ready work. If code: working, commented, best practices.\n"
        "If writing: clear, professional, precise. If plan: numbered, actionable.\n"
        "End with: 'Output Quality: [PRODUCTION/DRAFT/CONCEPT]'"
    )


def _supervisor_prompt(owner: str) -> str:
    return (
        f"You are the Supervisor & Coordinator for {owner}'s Expert Mode session.\n"
        "You have received analysis from 4 specialist agents. Your job:\n"
        "1. Synthesize the strongest insights from each agent\n"
        "2. Resolve any conflicts or disagreements between agents\n"
        "3. Produce ONE final, polished, definitive answer\n"
        "4. Cite which agent contributed which key insight\n\n"
        "Format:\n"
        "**Final Answer** (comprehensive, actionable)\n\n"
        "**Agent Contributions:**\n"
        "- 🔬 Researcher: [key insight used]\n"
        "- 🛡️ Critic: [key risk/validation]\n"
        "- ⚙️ Executor: [feasibility/steps]\n"
        "- ✨ Creator: [best output/synthesis]\n\n"
        "Be decisive. The user wants expert-level clarity, not hedging."
    )


# ── Expert agent runners ──────────────────────────────────────────────────────

@dataclass
class AgentResult:
    name: str
    label: str
    emoji: str
    content: str
    latency_ms: int
    error: str | None = None


async def _run_single_agent(
    name: str,
    label: str,
    emoji: str,
    system: str,
    user_query: str,
    memory_context: str,
) -> AgentResult:
    t0 = time.monotonic()
    messages = [{"role": "system", "content": system}]
    if memory_context:
        messages.append({"role": "system", "content": f"Relevant context:\n{memory_context}"})
    messages.append({"role": "user", "content": user_query})

    try:
        response = await chat_complete(messages, use_deep=True, temperature=0.4, max_tokens=1024)
        return AgentResult(
            name=name,
            label=label,
            emoji=emoji,
            content=response,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as e:
        logger.error(f"Expert agent '{name}' failed: {e}")
        return AgentResult(
            name=name,
            label=label,
            emoji=emoji,
            content=f"[Agent unavailable: {e}]",
            latency_ms=int((time.monotonic() - t0) * 1000),
            error=str(e),
        )


async def run_expert_mode(state: IRAState) -> IRAState:
    """
    Run all 5 expert agents in true parallel, then synthesize with supervisor.
    Returns an IRAState with structured expert collaboration in final_response.
    """
    t0 = time.monotonic()
    cfg = get_settings()
    owner = cfg.owner_name
    query = state["user_query"]
    memory_ctx = state.get("memory_context", "")

    logger.info(f"Expert Mode: launching 5 parallel agents for query: {query[:80]}...")

    # Launch all 4 specialist agents simultaneously
    specialist_tasks = await asyncio.gather(
        _run_single_agent("researcher", "Researcher", "🔬", _researcher_prompt(owner), query, memory_ctx),
        _run_single_agent("critic", "Critic", "🛡️", _critic_prompt(owner), query, memory_ctx),
        _run_single_agent("executor", "Executor", "⚙️", _executor_prompt(owner), query, memory_ctx),
        _run_single_agent("creator", "Creator", "✨", _creator_prompt(owner), query, memory_ctx),
        return_exceptions=False,
    )

    researcher_result, critic_result, executor_result, creator_result = specialist_tasks

    # Build supervisor context with all agent outputs
    agent_outputs = "\n\n".join([
        f"=== {r.emoji} {r.label.upper()} (latency: {r.latency_ms}ms) ===\n{r.content}"
        for r in [researcher_result, critic_result, executor_result, creator_result]
    ])

    supervisor_messages = [
        {"role": "system", "content": _supervisor_prompt(owner)},
        {
            "role": "system",
            "content": f"The 4 specialist agents have produced the following analysis:\n\n{agent_outputs}",
        },
        {"role": "user", "content": f"Original question: {query}\n\nSynthesize a definitive answer."},
    ]

    supervisor_result = await _run_single_agent(
        "supervisor", "Supervisor", "🧠",
        _supervisor_prompt(owner),
        f"Original question: {query}\n\nAgent outputs:\n{agent_outputs}",
        "",
    )

    # Build the full expert response with all agent contributions visible
    expert_response = (
        f"## Expert Mode — Collaborative Analysis\n\n"
        f"{researcher_result.content}\n\n"
        f"---\n\n"
        f"{critic_result.content}\n\n"
        f"---\n\n"
        f"{executor_result.content}\n\n"
        f"---\n\n"
        f"{creator_result.content}\n\n"
        f"---\n\n"
        f"## 🧠 Supervisor Synthesis\n\n"
        f"{supervisor_result.content}"
    )

    total_latency = int((time.monotonic() - t0) * 1000)
    logger.info(f"Expert Mode complete in {total_latency}ms")

    # Store individual agent results in metadata for streaming UI
    agent_details = [
        {"name": r.name, "label": r.label, "emoji": r.emoji,
         "content": r.content, "latency_ms": r.latency_ms}
        for r in [researcher_result, critic_result, executor_result, creator_result, supervisor_result]
    ]

    from langchain_core.messages import AIMessage
    return {
        **state,
        "final_response": expert_response,
        "messages": [AIMessage(content=expert_response)],
        "active_agent": "expert_mode",
        "model_used": "expert-parallel",
        "latency_ms": total_latency,
        "expert_agents": agent_details,  # type: ignore[typeddict-unknown-key]
    }


async def stream_expert_mode(
    query: str,
    memory_context: str = "",
    is_owner: bool = False,
    image_b64: str | None = None,
    mime_type: str = "image/jpeg",
) -> AsyncIterator[dict]:
    """
    Stream Expert Mode results agent-by-agent as they complete.

    If image_b64 is provided, all 5 agents receive the image as part of
    their multimodal user message (requires a vision-capable model).

    Yields dicts with:
      {"agent": name, "label": label, "emoji": emoji, "chunk": text, "done": False}
      {"agent": "supervisor", "final": True, "done": True, "latency_ms": N}
    """
    cfg = get_settings()
    owner = cfg.owner_name
    t0 = time.monotonic()

    def _user_content(text: str):
        """Build user message content — multimodal if image attached."""
        if image_b64:
            return [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
            ]
        return text

    # Stream each specialist result as soon as it's ready
    async def _stream_agent(name, label, emoji, system):
        messages = [{"role": "system", "content": system}]
        if memory_context:
            messages.append({"role": "system", "content": f"Context:\n{memory_context}"})
        messages.append({"role": "user", "content": _user_content(query)})
        result_chunks = []
        try:
            async for token in stream_tokens(messages, use_deep=True):
                result_chunks.append(token)
                yield {"agent": name, "label": label, "emoji": emoji, "chunk": token, "done": False}
        except Exception as e:
            err = f"[{label} error: {e}]"
            result_chunks.append(err)
            yield {"agent": name, "label": label, "emoji": emoji, "chunk": err, "done": False}
        yield {"agent": name, "label": label, "emoji": emoji,
               "chunk": "", "agent_done": True, "full": "".join(result_chunks)}

    # Run all 4 specialists in parallel via queue
    results: dict[str, str] = {}
    queue: asyncio.Queue = asyncio.Queue()

    async def _collect(name, label, emoji, system):
        full_text = []
        async for event in _stream_agent(name, label, emoji, system):
            await queue.put(event)
            if event.get("agent_done"):
                results[name] = event.get("full", "")

    tasks = [
        asyncio.create_task(_collect("researcher", "Researcher", "🔬", _researcher_prompt(owner))),
        asyncio.create_task(_collect("critic", "Critic", "🛡️", _critic_prompt(owner))),
        asyncio.create_task(_collect("executor", "Executor", "⚙️", _executor_prompt(owner))),
        asyncio.create_task(_collect("creator", "Creator", "✨", _creator_prompt(owner))),
    ]

    # Drain queue while tasks run
    completed = 0
    while completed < len(tasks):
        try:
            event = await asyncio.wait_for(queue.get(), timeout=120.0)
            yield event
            if event.get("agent_done"):
                completed += 1
        except asyncio.TimeoutError:
            break

    await asyncio.gather(*tasks, return_exceptions=True)

    # Supervisor synthesis
    agent_summary = "\n\n".join(
        f"=== {name.upper()} ===\n{text}"
        for name, text in results.items()
    )
    sup_messages = [
        {"role": "system", "content": _supervisor_prompt(owner)},
        {
            "role": "system",
            "content": f"Specialist agent outputs:\n\n{agent_summary}",
        },
        {"role": "user", "content": _user_content(f"Question: {query}\n\nSynthesize the definitive answer.")},
    ]

    try:
        async for token in stream_tokens(sup_messages, use_deep=True):
            yield {"agent": "supervisor", "label": "Supervisor", "emoji": "🧠",
                   "chunk": token, "done": False}
    except Exception as e:
        yield {"agent": "supervisor", "label": "Supervisor", "emoji": "🧠",
               "chunk": f"[Supervisor error: {e}]", "done": False}

    yield {
        "agent": "supervisor",
        "label": "Supervisor",
        "emoji": "🧠",
        "chunk": "",
        "done": True,
        "latency_ms": int((time.monotonic() - t0) * 1000),
    }


def is_expert_mode_request(query: str) -> bool:
    """Detect if the user wants to enable Expert Mode."""
    import re
    pattern = re.compile(
        r"\b(expert\s*mode|use\s+experts?|think\s+(step.by.step\s+)?with\s+(team|agents?|experts?)|"
        r"enable\s+expert|deep\s+analysis\s+mode|multi.?agent)\b",
        re.I,
    )
    return bool(pattern.search(query))
