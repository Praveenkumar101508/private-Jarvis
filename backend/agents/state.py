"""
LangGraph agent state definition
"""
from typing import Annotated, TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class IRAState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    session_id: str
    language: str
    detected_language: str
    user_intent: str
    tool_results: list[dict]
    output: str
    should_search: bool
    should_use_calendar: bool
    memory_context: str
