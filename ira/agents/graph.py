"""
IRA LangGraph — hierarchical multi-agent graph with biometric security gate.

Flow:
  START
    → retrieve_memory          (fetch relevant past context)
    → classify                 (route to the right specialist)
    → biometric_gate           (block restricted domains for non-owners)
    → [conversational | researcher | security | website | creator | executor
       | access_denied]
    → store_interaction        (persist message + async embedding)
  END

The biometric_gate node is the Context-Aware Security Guardrail:
  - Public domain requests (anyone): pass straight through to the specialist
  - Restricted domain + is_owner=True: full clearance, pass through
  - Restricted domain + is_owner=False: block, set final_response to refusal
    message, route to access_denied (skips specialist + store)

The graph is compiled once at startup and reused for every request.
"""

from __future__ import annotations

import asyncio
import time

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.messages import HumanMessage

from agents.state import IRAState
from agents.supervisor import classify, is_restricted_domain
from agents.conversational import conversational
from agents.researcher import researcher
from agents.security import security_guardian
from agents.website import website_manager
from agents.creator import meta_agent_creator
from agents.executor import executor
from memory.store import retrieve, ensure_conversation, save_message
from config import get_settings


# ── Memory retrieval node ──────────────────────────────────────────────────────

async def retrieve_memory(state: IRAState) -> IRAState:
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


# ── Biometric / Context-Aware Security Gate ────────────────────────────────────

async def biometric_gate(state: IRAState) -> IRAState:
    """
    The Biometric Dual-Role Clearance Gate.

    Checks whether the incoming query touches a restricted domain.
    If it does, validates the owner identity flag (`is_owner`).

    Two outcomes:
      PASS  → is_owner=True, or query is not in a restricted domain
              State passes unchanged to the specialist agent.
      BLOCK → is_owner=False AND query is in a restricted domain
              State is modified: `final_response` is set to the polite
              refusal message and `active_agent` is set to "access_denied".
              The specialist agent node is bypassed entirely.
    """
    cfg = get_settings()

    # Public query or owner — pass through
    if not is_restricted_domain(state["user_query"]) or state.get("is_owner", False):
        return state

    # Restricted domain + not owner → block
    owner_name = cfg.owner_name
    refusal = (
        f"I'm sorry — I'm an automated assistant for SupraCloud. "
        f"That administrative information is strictly restricted to "
        f"{owner_name}, the company founder. "
        f"I cannot share security logs, personal data, system credentials, "
        f"or internal architecture details with anyone else. "
        f"If you have a general enquiry about SupraCloud's services or need "
        f"technical assistance, I'm delighted to help with that instead."
    )

    return {
        **state,
        "active_agent": "access_denied",
        "final_response": refusal,
        "model_used": "security_gate",
        "latency_ms": 0,
        "error": None,
    }


def route_after_gate(state: IRAState) -> str:
    """Route from biometric_gate to specialist or access_denied."""
    agent = state["active_agent"]
    if agent == "access_denied":
        return "access_denied"
    return agent


# ── Access-denied terminal node ────────────────────────────────────────────────

async def access_denied(state: IRAState) -> IRAState:
    """
    Terminal node for blocked requests.
    The refusal message is already set by biometric_gate.
    This node just returns state so store_interaction can persist the event.
    """
    return state


# ── Interaction persistence node ───────────────────────────────────────────────

async def store_interaction(state: IRAState) -> IRAState:
    """
    Persist the user message and IRA response.
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
    g = StateGraph(IRAState)

    # Core nodes
    g.add_node("retrieve_memory",  retrieve_memory)
    g.add_node("classify",         classify)
    g.add_node("biometric_gate",   biometric_gate)
    g.add_node("access_denied",    access_denied)
    g.add_node("conversational",   conversational)
    g.add_node("researcher",       researcher)
    g.add_node("security",         security_guardian)
    g.add_node("website",          website_manager)
    g.add_node("creator",          meta_agent_creator)
    g.add_node("executor",         executor)
    g.add_node("store_interaction", store_interaction)

    # Entry → memory retrieval → classification → biometric gate
    g.add_edge(START, "retrieve_memory")
    g.add_edge("retrieve_memory", "classify")
    # classify always routes to biometric_gate (see supervisor.route_after_classify)
    g.add_edge("classify", "biometric_gate")

    # Conditional routing from biometric_gate to specialist (or access_denied)
    g.add_conditional_edges(
        "biometric_gate",
        route_after_gate,
        {
            "conversational": "conversational",
            "researcher":     "researcher",
            "security":       "security",
            "website":        "website",
            "creator":        "creator",
            "executor":       "executor",
            "access_denied":  "access_denied",
        },
    )

    # All specialists + access_denied → store → END
    for node in ["conversational", "researcher", "security", "website",
                 "creator", "executor", "access_denied"]:
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
    is_owner: bool = False,
) -> IRAState:
    """
    Execute the full agent graph for a single user turn.
    Returns the completed state with final_response populated.

    Args:
        is_owner: True when the request comes from the authenticated admin user
                  (text) or has passed biometric voice verification (voice).
    """
    graph = get_graph()

    initial_state: IRAState = {
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
        "is_owner": is_owner,
        "clearance_level": "admin" if is_owner else "public",
        "error": None,
    }

    # thread_id scopes LangGraph's checkpointer to this conversation
    config = {"configurable": {"thread_id": session_id}}

    final_state = await graph.ainvoke(initial_state, config=config)
    return final_state
