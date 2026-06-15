"""
Supervisor node — classifies each query and sets routing metadata.
Uses pure heuristics (zero LLM calls) for <5ms classification latency.
"""

from __future__ import annotations

import time

from agents.state import JarvisState
from utils.llm import should_use_deep

# ── Keyword maps for agent selection ─────────────────────────────────────────
_AGENT_RULES: list[tuple[frozenset[str], str]] = [
    (frozenset({
        "hack", "attack", "vulnerability", "exploit", "breach", "malware",
        "threat", "intrusion", "anomaly", "firewall", "scan port", "port scan",
        "security log", "security alert", "unauthorized", "suspicious", "ddos",
    }), "security"),
    (frozenset({
        "create agent", "build agent", "new agent", "make agent", "generate agent",
        "langgraph agent", "agent code", "agent creator", "design agent",
    }), "creator"),
    (frozenset({
        "website", "supracloud site", "booking", "lead", "customer inquiry",
        "site traffic", "seo", "update content", "business report", "revenue",
        "analytics", "conversion",
    }), "website"),
    (frozenset({
        "research", "find out", "investigate", "search for", "what is",
        "tell me about", "explain", "compare", "analyse", "analyze",
        "summarise", "summarize", "report on",
    }), "researcher"),
    (frozenset({
        "run", "execute", "deploy", "install package", "run command",
        "bash", "shell", "script",
    }), "executor"),
]


def classify(state: JarvisState) -> JarvisState:
    """
    Classify the query and set active_agent + use_deep_model.
    This is the first node in every graph traversal.
    """
    query = state["user_query"].lower()
    agent = "conversational"

    for keywords, agent_name in _AGENT_RULES:
        if any(kw in query for kw in keywords):
            agent = agent_name
            break

    return {
        **state,
        "active_agent": agent,
        "use_deep_model": should_use_deep(state["user_query"], agent),
    }


def route_after_classify(state: JarvisState) -> str:
    """Conditional edge: returns the name of the next node to visit."""
    return state["active_agent"]
