"""
Supervisor node — classifies each query and sets routing metadata.

Classification strategy:
  1. Keyword fast-path  — instant, zero LLM calls, handles ~80% of queries
  2. LLM fallback       — fast model (llama-fast), <2s, for queries longer than
                          15 words that match no keywords. Prevents misrouting
                          of ambiguous complex requests.

Biometric gate:
  `is_restricted_domain()` is a pure function exported for use by both the
  LangGraph biometric_gate node and the streaming SSE endpoint. It returns
  True when a query touches any domain gated behind owner authentication.
"""

from __future__ import annotations

from agents.state import IRAState
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

_VALID_AGENTS = {"conversational", "researcher", "security", "website", "creator", "executor"}

# ── Restricted domain classification ─────────────────────────────────────────
# ANY query containing one of these keywords is gated behind biometric auth.
# Non-owners receive a polite refusal; the underlying data is never exposed.
_RESTRICTED_KEYWORDS: frozenset[str] = frozenset({
    # Security & system internals
    "security log", "system log", "audit log", "error log", "health log",
    "nginx log", "access log", "event log",
    "admin password", "database password", "db password",
    "secret key", "api key", "env file", ".env",
    "credentials", "private key", "ssl cert",
    "system health", "server metrics", "cpu usage", "memory usage",
    "show logs", "show errors", "show config",
    # Personal / owner data
    "schedule", "my calendar", "my appointment", "my meeting",
    "personal", "private", "swetha", "owner",
    "my email", "my phone", "my address",
    # Financial
    "financial", "revenue", "invoice", "payment", "bank",
    "company finances", "profit", "loss",
    # Core architecture / source code
    "agent code", "source code", "internal architecture",
    "codebase", "internal code", "show me the code",
    "database schema", "db schema", "table structure",
    # Admin actions
    "create user", "delete user", "reset password", "change password",
    "grant access", "revoke access",
})


def is_restricted_domain(query: str) -> bool:
    """
    Return True if the query touches any owner-gated restricted domain.
    Pure function — no I/O, safe to call anywhere.
    """
    q = query.lower()
    return any(kw in q for kw in _RESTRICTED_KEYWORDS)


# ── LLM fallback router ───────────────────────────────────────────────────────
_LLM_ROUTER_SYSTEM = """\
Classify the user query into exactly one routing category. Reply with ONE word only.

Categories:
- conversational  greetings, simple questions, task creation, reminders, status
- researcher      research, deep analysis, explanations, comparisons, summaries
- security        security checks, threat analysis, logs, vulnerabilities, attacks
- website         leads, bookings, website analytics, business metrics, content drafts
- creator         create / build / generate a new AI agent or tool
- executor        run / execute / deploy a command, script, or shell operation

Reply with the single category word and nothing else.\
"""


async def classify(state: IRAState) -> IRAState:
    """
    Classify the query and set active_agent + use_deep_model.

    Fast keyword matching runs first (no LLM call). For queries longer than
    15 words that hit no keywords, the fast LLM model provides accurate semantic
    routing for complex, ambiguous inputs.
    """
    query = state["user_query"].lower()
    agent = "conversational"

    for keywords, agent_name in _AGENT_RULES:
        if any(kw in query for kw in keywords):
            agent = agent_name
            break

    # LLM fallback only for long queries that matched no keyword
    if agent == "conversational" and len(state["user_query"].split()) > 15:
        try:
            from utils.llm import chat_complete
            result = await chat_complete(
                [
                    {"role": "system", "content": _LLM_ROUTER_SYSTEM},
                    {"role": "user", "content": state["user_query"]},
                ],
                use_deep=False,
                max_tokens=10,
                temperature=0,
            )
            candidate = result.strip().lower().split()[0] if result.strip() else ""
            if candidate in _VALID_AGENTS:
                agent = candidate
        except Exception:
            pass  # Routing failure must never block a response

    return {
        **state,
        "active_agent": agent,
        "use_deep_model": should_use_deep(state["user_query"], agent),
    }


def route_after_classify(state: IRAState) -> str:
    """Conditional edge: returns the name of the next node to visit."""
    # Always route through the biometric gate after classification
    return "biometric_gate"
