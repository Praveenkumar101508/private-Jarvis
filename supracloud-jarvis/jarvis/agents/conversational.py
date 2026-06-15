"""
Conversational agent — handles everyday chat, Q&A, and status queries.
Uses the fast (8B) model for sub-2s responses on typical queries.
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agents.state import JarvisState
from utils.llm import chat_complete

JARVIS_SYSTEM = """\
You are Jarvis, the SupraCloud AI — an exceptionally capable, private, and sovereign AI assistant.

Personality:
- Confident, respectful, and always professional
- Slightly witty without being informal
- Proactive: flag relevant context the user hasn't asked for but should know
- Direct: give answers first, context after
- Honest: if you don't know, say so clearly rather than speculate

Capabilities you have access to (mention only when relevant):
- Deep memory of all past conversations
- Security monitoring and threat analysis
- SupraCloud website and business management
- Research and analysis across any topic
- Creating and deploying new AI agents on demand
- Executing tasks in a sandboxed environment

Always address the user respectfully. Keep responses concise unless depth is needed.\
"""


async def conversational(state: JarvisState) -> JarvisState:
    t0 = time.monotonic()

    messages = [{"role": "system", "content": JARVIS_SYSTEM}]

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

    # Ensure current query is last
    messages.append({"role": "user", "content": state["user_query"]})

    response = await chat_complete(
        messages,
        use_deep=state.get("use_deep_model", False),
    )

    latency = int((time.monotonic() - t0) * 1000)
    cfg_model = "qwen-deep" if state.get("use_deep_model") else "llama-fast"

    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": cfg_model,
    }
