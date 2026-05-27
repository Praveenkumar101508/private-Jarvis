"""
Conversational agent — handles everyday chat, Q&A, and status queries.
Uses the fast (8B) model for sub-2s responses on typical queries.
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.state import IRAState
from utils.llm import chat_complete

from agents.grok_personality import build_grok_system_prompt

# IRA_SYSTEM is the Grok-style personality used by this agent and referenced
# across chat.py routing and the Expert Mode supervisor.
IRA_SYSTEM = build_grok_system_prompt()


async def conversational(state: IRAState) -> IRAState:
    t0 = time.monotonic()

    messages = [{"role": "system", "content": IRA_SYSTEM}]

    # Inject retrieved memories as context
    if state.get("memory_context"):
        messages.append({
            "role": "system",
            "content": f"Relevant context from memory:\n{state['memory_context']}",
        })

    # Include recent conversation history
    for msg in state.get("messages", [])[-20:]:
        if isinstance(msg, HumanMessage):
            messages.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            messages.append({"role": "assistant", "content": msg.content})

    # Ensure current query is last — guard against duplicate if history already ends with it
    if not messages or messages[-1].get("content") != state["user_query"]:
        messages.append({"role": "user", "content": state["user_query"]})

    response = await chat_complete(
        messages,
        use_deep=state.get("use_deep_model", False),
    )

    latency = int((time.monotonic() - t0) * 1000)
    cfg_model = "qwen3-deep" if state.get("use_deep_model") else "qwen3-fast"  # Fix L11+L12: stale names

    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": cfg_model,
    }
