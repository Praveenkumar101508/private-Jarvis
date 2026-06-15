"""
Researcher Agent — deep analysis, explanation, and synthesis.
Routes to deep model for thorough, well-structured responses.
Produces structured reports with clear sections.
"""

from __future__ import annotations

import time

from langchain_core.messages import AIMessage

from agents.state import JarvisState
from utils.llm import chat_complete

_SYSTEM = """\
You are the Researcher module of Jarvis — a rigorous, precise research and analysis engine.

When researching a topic:
1. Lead with the most critical insight or answer
2. Structure longer responses with clear headings
3. Distinguish facts from inference — never fabricate
4. When information might be outdated, say so and give the knowledge cutoff
5. End with actionable next steps or recommendations when relevant

You have access to the full conversation history and retrieved memories for context.
Respond as Jarvis would: confident, authoritative, and concise.\
"""


async def researcher(state: JarvisState) -> JarvisState:
    t0 = time.monotonic()

    messages = [{"role": "system", "content": _SYSTEM}]

    if state.get("memory_context"):
        messages.append({
            "role": "system",
            "content": f"Relevant past context:\n{state['memory_context']}",
        })

    messages.append({"role": "user", "content": state["user_query"]})

    # Researcher always uses deep model for quality
    response = await chat_complete(messages, use_deep=True, temperature=0.3)

    latency = int((time.monotonic() - t0) * 1000)
    return {
        **state,
        "final_response": response,
        "messages": [AIMessage(content=response)],
        "latency_ms": latency,
        "model_used": "qwen-deep",
    }
