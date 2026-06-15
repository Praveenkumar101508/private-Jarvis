"""
Jarvis LangGraph — hierarchical multi-agent graph.

Flow:
  START
    → retrieve_memory          (fetch relevant past context)
    → classify                 (route to the right specialist)
    → [conversational | researcher | security | website | creator | executor]
    → store_interaction        (persist message + async embedding)
  END

The graph is compiled once at startup and reused for every request.
LangGraph's MemorySaver provides in-process checkpointing for conversation state.
"""

from __future__ import annotations

import asyncio
import time

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

from agents.state import JarvisState
from agents.supervisor import classify, route_after_classify
from agents.conversational import conversational
from agents.researcher import researcher
from agents.security import security_guardian
from agents.website import website_manager
from agents.creator import meta_agent_creator
from agents.executor import executor
from memory.store import retrieve, ensure_conversation, save_message


# ── Memory retrieval node ──────────────────────────────────────────────────────

async def retrieve_memory(state: JarvisState) -> JarvisState:
    """Fetch top-K relevant memories and format them for prompt injection."""
    memories = await retrieve(state["user_query"])
    if not memories:
        return {**state, "memory_context": ""}

    lines = []
    for m in memories:
        score = f"{m['similarity']:.2f}"
        lines.append(f"[{m['source_type']} | similarity={score}] {m['content']}")
    context = "\n".join(lines)

    return {**state, "memory_context": context}


# ── Interaction persistence node ───────────────────────────────────────────────

async def store_interaction(state: JarvisState) -> JarvisState:
    """
    Persist the user message and Jarvis response.
    Embeddings are stored asynchronously — this node returns immediately.
    """
    conv_id = state.get("conversation_id", "")
    if not conv_id:
        return state

    await save_message(
        conv_id,
        role="user",
        content=state["user_query"],
    )
    await save_message(
        conv_id,
        role="assistant",
        content=state["final_response"],
        model_used=state.get("model_used"),
        latency_ms=state.get("latency_ms"),
    )
    return state


# ── Graph construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(JarvisState)

    # Nodes
    g.add_node("retrieve_memory", retrieve_memory)
    g.add_node("classify", classify)
    g.add_node("conversational", conversational)
    g.add_node("researcher", researcher)
    g.add_node("security", security_guardian)
    g.add_node("website", website_manager)
    g.add_node("creator", meta_agent_creator)
    g.add_node("executor", executor)
    g.add_node("store_interaction", store_interaction)

    # Entry → memory retrieval → classification
    g.add_edge(START, "retrieve_memory")
    g.add_edge("retrieve_memory", "classify")

    # Conditional routing from classifier to specialist
    g.add_conditional_edges(
        "classify",
        route_after_classify,
        {
            "conversational": "conversational",
            "researcher":     "researcher",
            "security":       "security",
            "website":        "website",
            "creator":        "creator",
            "executor":       "executor",
        },
    )

    # All specialists → store → END
    for node in ["conversational", "researcher", "security", "website", "creator", "executor"]:
        g.add_edge(node, "store_interaction")
    g.add_edge("store_interaction", END)

    return g


# Compiled graph — singleton, initialised at app startup
_checkpointer = MemorySaver()
_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph().compile(checkpointer=_checkpointer)
    return _compiled_graph


async def run_graph(
    session_id: str,
    conversation_id: str,
    user_query: str,
    message_history: list | None = None,
) -> JarvisState:
    """
    Execute the full agent graph for a single user turn.
    Returns the completed state with final_response populated.
    """
    graph = get_graph()

    initial_state: JarvisState = {
        "messages": [HumanMessage(content=user_query)] if not message_history else message_history,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "user_query": user_query,
        "active_agent": "conversational",
        "use_deep_model": False,
        "memory_context": "",
        "final_response": "",
        "stream_tokens": [],
        "latency_ms": 0,
        "model_used": "llama-fast",
        "error": None,
    }

    # thread_id scopes LangGraph's checkpointer to this conversation
    config = {"configurable": {"thread_id": session_id}}

    final_state = await graph.ainvoke(initial_state, config=config)
    return final_state
