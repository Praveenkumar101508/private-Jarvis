"""
IRA LangGraph — hierarchical multi-agent graph with biometric security gate.

Flow:
  START
    → retrieve_memory          (fetch relevant past context)
    → classify                 (route to the right specialist)
    → biometric_gate           (block restricted domains for non-owners)
    → [conversational | researcher | security | website | creator | executor
       | career | tutor | digital | access_denied]
    → store_interaction        (persist message + async embedding)
  END

DEV_MODE: biometric gate is bypassed entirely (all requests treated as owner).
"""

from __future__ import annotations

import time

import logging

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import HumanMessage

_graph_logger = logging.getLogger("ira.graph")

from agents.state import IRAState
from agents.supervisor import classify
from agents.conversational import conversational
from agents.researcher import researcher
from agents.security import security_guardian
from agents.website import website_manager
from agents.creator import meta_agent_creator
from agents.executor import executor
from agents.career import career_agent
from agents.tutor import tutor_agent
from agents.digital import digital_agent
from memory.store import retrieve, ensure_conversation, save_message
from config import get_settings


# ── Memory retrieval node ──────────────────────────────────────────────────────

async def retrieve_memory(state: IRAState) -> IRAState:
    """Fetch top-K relevant memories + the owner profile, formatted for the prompt.

    The owner profile (who-I-am / goals / projects / prefs) is injected every turn so
    the brain stays grounded; it is prepended to the retrieved-memory context.
    """
    from owner_profile import get_profile_summary
    profile_summary = await get_profile_summary()

    memories = await retrieve(state["user_query"], user_id=state.get("user_id", "system"))
    lines = []
    for m in memories or []:
        score = f"{m['similarity']:.2f}"
        lines.append(f"[{m['source_type']} | similarity={score}] {m['content']}")

    sections = [s for s in (profile_summary, "\n".join(lines)) if s]
    return {**state, "memory_context": "\n\n".join(sections)}


# ── Biometric / Context-Aware Security Gate ────────────────────────────────────

async def biometric_gate(state: IRAState) -> IRAState:
    """
    The Biometric Dual-Role Clearance Gate.

    DEV_MODE: skipped entirely — all requests pass as owner.
    Production:
      PASS  → is_owner=True, or query is not in a restricted domain
      BLOCK → is_owner=False AND query is in a restricted domain
    """
    cfg = get_settings()

    # Dev mode: bypass gate completely
    if cfg.dev_mode:
        return {**state, "is_owner": True, "clearance_level": "admin"}

    # V1·Phase 3: decision comes from the unified owner-gate (single source of truth
    # shared with the router), so the graph and router paths can never diverge. The
    # branded refusal below stays a graph-path UX concern.
    from security.owner_gate import evaluate as _evaluate_gate

    if _evaluate_gate(state["user_query"], state.get("is_owner", False)).allowed:
        return state

    # Owner-only query + not owner → block
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
    return state["active_agent"]


# ── Access-denied terminal node ────────────────────────────────────────────────

async def access_denied(state: IRAState) -> IRAState:
    """Terminal node for blocked requests. Refusal message already set."""
    return state


# ── Interaction persistence node ───────────────────────────────────────────────

async def store_interaction(state: IRAState) -> IRAState:
    """Persist the user message and IRA response."""
    conv_id = state.get("conversation_id", "")
    if not conv_id:
        return state

    await save_message(
        conv_id,
        role="user",
        content=state["user_query"],
        user_id=state.get("user_id", "system"),
    )
    await save_message(
        conv_id,
        role="assistant",
        content=state["final_response"],
        model_used=state.get("model_used"),
        latency_ms=state.get("latency_ms"),
        user_id=state.get("user_id", "system"),
    )
    return state


# ── Graph construction ────────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(IRAState)

    # Core nodes
    g.add_node("retrieve_memory",   retrieve_memory)
    g.add_node("classify",          classify)
    g.add_node("biometric_gate",    biometric_gate)
    g.add_node("access_denied",     access_denied)
    g.add_node("conversational",    conversational)
    g.add_node("researcher",        researcher)
    g.add_node("security",          security_guardian)
    g.add_node("website",           website_manager)
    g.add_node("creator",           meta_agent_creator)
    g.add_node("executor",          executor)
    g.add_node("career",            career_agent)
    g.add_node("tutor",             tutor_agent)
    g.add_node("digital",           digital_agent)
    g.add_node("store_interaction", store_interaction)

    # Entry → memory retrieval → classification → biometric gate
    g.add_edge(START, "retrieve_memory")
    g.add_edge("retrieve_memory", "classify")
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
            "career":         "career",
            "tutor":          "tutor",
            "digital":        "digital",
            "access_denied":  "access_denied",
        },
    )

    # All specialists + access_denied → store → END
    for node in ["conversational", "researcher", "security", "website",
                 "creator", "executor", "career", "tutor", "digital", "access_denied"]:
        g.add_edge(node, "store_interaction")
    g.add_edge("store_interaction", END)

    return g


# Compiled graph — singleton, initialised at app startup via init_checkpointer()
_checkpointer = None
_compiled_graph = None
_pg_checkpointer_ctx = None


async def init_checkpointer(pg_conn_string: str) -> None:
    """
    Initialise the LangGraph checkpointer and compile the agent graph.

    Uses AsyncPostgresSaver (psycopg3) so conversation state survives
    container restarts. Falls back to in-memory MemorySaver if the
    langgraph-checkpoint-postgres package is not installed.

    Call this once from main.py lifespan startup, after the DB pool is ready.
    """
    global _checkpointer, _compiled_graph, _pg_checkpointer_ctx
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        _pg_checkpointer_ctx = AsyncPostgresSaver.from_conn_string(pg_conn_string)
        _checkpointer = await _pg_checkpointer_ctx.__aenter__()
        await _checkpointer.setup()   # Creates checkpoint tables if they don't exist
        _graph_logger.info("LangGraph checkpointer: AsyncPostgresSaver (persistent)")
    except Exception as exc:
        _graph_logger.warning(
            f"AsyncPostgresSaver unavailable ({exc}); falling back to in-memory MemorySaver. "
            "Install langgraph-checkpoint-postgres and psycopg[binary] for persistence."
        )
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer = MemorySaver()

    _compiled_graph = build_graph().compile(checkpointer=_checkpointer)


async def close_checkpointer() -> None:
    """Clean up the AsyncPostgresSaver connection pool on shutdown."""
    global _pg_checkpointer_ctx
    if _pg_checkpointer_ctx is not None:
        try:
            await _pg_checkpointer_ctx.__aexit__(None, None, None)
        except Exception:
            pass
        _pg_checkpointer_ctx = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        # Synchronous fallback: used only if init_checkpointer() was not called
        from langgraph.checkpoint.memory import MemorySaver
        _graph_logger.warning("get_graph() called before init_checkpointer(); using in-memory checkpointer")
        _compiled_graph = build_graph().compile(checkpointer=MemorySaver())
    return _compiled_graph


def make_initial_state(
    *,
    session_id: str,
    conversation_id: str,
    user_query: str,
    user_id: str,
    is_owner: bool = False,
    mode: str = "assistant",
    is_voice: bool = False,
    message_history: list | None = None,
) -> IRAState:
    # Fix P23: single factory so run_graph() and chat_stream() cannot drift out of sync
    return {
        "messages": [HumanMessage(content=user_query)] if not message_history else message_history,
        "session_id": session_id,
        "conversation_id": conversation_id,
        "user_query": user_query,
        "active_agent": "conversational",
        "use_deep_model": False,
        "mode": mode,
        "memory_context": "",
        "final_response": "",
        "stream_tokens": [],
        "latency_ms": 0,
        "model_used": "qwen3-fast",
        "is_owner": is_owner,
        "clearance_level": "admin" if is_owner else "public",
        "is_voice": is_voice,
        "user_id": user_id,
        "error": None,
    }


async def run_graph(
    session_id: str,
    conversation_id: str,
    user_query: str,
    message_history: list | None = None,
    is_owner: bool = False,
    mode: str = "assistant",
    is_voice: bool = False,
    user_id: str = "system",
) -> IRAState:
    """
    Execute the full agent graph for a single user turn.
    Returns the completed state with final_response populated.

    Args:
        is_owner:  True when the request comes from the authenticated admin user
                   (text) or has passed biometric voice verification (voice).
        mode:      "assistant" | "tutor" — persona override from the frontend.
        is_voice:  True when the request originates from the voice pipeline.
    """
    graph = get_graph()

    initial_state = make_initial_state(  # Fix P23: use shared factory
        session_id=session_id,
        conversation_id=conversation_id,
        user_query=user_query,
        user_id=user_id,
        is_owner=is_owner,
        mode=mode,
        is_voice=is_voice,
        message_history=message_history,
    )

    config = {"configurable": {"thread_id": session_id}}

    from utils.telemetry import trace_span
    with trace_span("run_graph", {
        "session_id": session_id,
        "user_query_len": len(user_query),
        "is_owner": is_owner,
        "mode": mode,
    }):
        final_state = await graph.ainvoke(initial_state, config=config)

    return final_state
