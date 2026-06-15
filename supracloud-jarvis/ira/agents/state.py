"""
LangGraph state definition for the IRA agent graph.
All nodes read from and write to this shared state dict.
"""

from __future__ import annotations

from typing import Annotated
from typing_extensions import TypedDict, NotRequired
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class IRAState(TypedDict):
    # Full message history (LangGraph manages appending via add_messages)
    messages: Annotated[list[BaseMessage], add_messages]

    # Routing & context
    session_id: str
    conversation_id: str
    user_query: str           # The raw current query
    active_agent: str         # Which specialist is handling this turn
    use_deep_model: bool      # Fast (False) or deep (True) vLLM endpoint
    mode: str                 # "assistant" | "tutor" — persona override from frontend

    # Memory
    memory_context: str       # Formatted retrieved memories injected into prompt

    # Response
    final_response: str       # The assembled response text
    stream_tokens: list[str]  # Accumulated streaming chunks (for SSE)

    # Metadata
    latency_ms: int
    model_used: str
    is_voice: bool            # True when request originates from voice pipeline
    user_id: str              # Authenticated username — scopes memory storage and retrieval
    error: str | None

    # ── Biometric / Access control ─────────────────────────────────────────────
    # True when request originates from the authenticated system owner.
    # Set by: chat.py (admin JWT check) or voice/agent.py (biometric match).
    # Read by: biometric_gate node in graph.py.
    is_owner: bool
    # "admin" → full access, "public" → restricted domains blocked
    clearance_level: str

    # ── Expert Mode metadata ─────────────────────────────────────────────────
    # Fix #93: declare expert_agents so it is recognised by the LangGraph
    # state schema and the checkpointer — avoids "unknown field" warnings and
    # the mypy type:ignore suppression in expert_mode.py.
    # NotRequired: only present when run_expert_mode() populates the state.
    expert_agents: NotRequired[list[dict]]
