"""
Phase 2: LangGraph agent graph — IRA's reasoning pipeline
"""
import json
from typing import AsyncGenerator

from langchain_core.messages import HumanMessage
from langgraph.graph import StateGraph, END

from agents.state import IRAState
from agents.nodes import (
    detect_language_node,
    load_memory_node,
    classify_intent_node,
    web_search_node,
    calendar_node,
    generate_response_node,
    route_after_classify,
)
from config import settings


def build_graph() -> StateGraph:
    g = StateGraph(IRAState)

    g.add_node("detect_language", detect_language_node)
    g.add_node("load_memory", load_memory_node)
    g.add_node("classify_intent", classify_intent_node)
    g.add_node("web_search", web_search_node)
    g.add_node("calendar", calendar_node)
    g.add_node("generate_response", generate_response_node)

    g.set_entry_point("detect_language")
    g.add_edge("detect_language", "load_memory")
    g.add_edge("load_memory", "classify_intent")

    g.add_conditional_edges(
        "classify_intent",
        route_after_classify,
        {
            "web_search": "web_search",
            "calendar": "calendar",
            "generate_response": "generate_response",
        },
    )

    g.add_edge("web_search", "generate_response")
    g.add_edge("calendar", "generate_response")
    g.add_edge("generate_response", END)

    return g.compile()


_compiled_graph = None


def get_graph():
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


class IRAGraph:
    def __init__(self):
        self.graph = get_graph()

    async def invoke(self, message: str, session_id: str, language: str = "en") -> dict:
        state = IRAState(
            messages=[HumanMessage(content=message)],
            session_id=session_id,
            language=language,
            detected_language=language,
            user_intent="",
            tool_results=[],
            output="",
            should_search=False,
            should_use_calendar=False,
            memory_context="",
        )
        result = await self.graph.ainvoke(state)
        return result

    async def stream(self, message: str, session_id: str, language: str = "en") -> AsyncGenerator[str, None]:
        result = await self.invoke(message=message, session_id=session_id, language=language)
        output = result.get("output", "")
        # Stream word by word for a natural feel
        words = output.split()
        for i, word in enumerate(words):
            chunk = word if i == 0 else f" {word}"
            yield json.dumps({"chunk": chunk, "session_id": session_id})
