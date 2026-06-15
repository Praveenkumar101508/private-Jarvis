"""
LangGraph state definition for the Jarvis agent graph.
All nodes read from and write to this shared state dict.
"""

from __future__ import annotations

from typing import Annotated, Any
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage


class JarvisState(TypedDict):
    # Full message history (LangGraph manages appending via add_messages)
    messages: Annotated[list[BaseMessage], add_messages]

    # Routing & context
    session_id: str
    conversation_id: str
    user_query: str           # The raw current query
    active_agent: str         # Which specialist is handling this turn
    use_deep_model: bool      # Fast (False) or deep (True) vLLM endpoint

    # Memory
    memory_context: str       # Formatted retrieved memories injected into prompt

    # Response
    final_response: str       # The assembled response text
    stream_tokens: list[str]  # Accumulated streaming chunks (for SSE)

    # Metadata
    latency_ms: int
    model_used: str
    error: str | None         # Set if any node encounters a recoverable error
