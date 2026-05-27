"""
Supervisor node — classifies each query and sets routing metadata.

Classification strategy:
  1. Mode override     — if state.mode == "tutor", force tutor agent
  2. Keyword fast-path — instant, zero LLM calls, handles ~80% of queries
  3. LLM fallback      — fast model (llama-fast), <2s, for queries longer than
                         15 words that match no keywords

Biometric gate:
  `is_restricted_domain()` is a pure function exported for use by both the
  LangGraph biometric_gate node and the streaming SSE endpoint. It returns
  True when a query touches any domain gated behind owner authentication.
"""

from __future__ import annotations

import re

from agents.state import IRAState
from utils.llm import should_use_deep

_URL_RE = re.compile(r"https?://\S+")

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
    # Career & automation — checked before researcher to avoid misrouting
    (frozenset({
        "resume", "cv", "job posting", "linkedin job", "indeed job",
        "tailor my resume", "job application", "apply for", "job description",
        "career", "interview prep", "my github", "my codebase", "my repositories",
        "my portfolio", "job scrape", "scrape linkedin", "scrape indeed",
    }), "career"),
    # Tutor mode (Phase 5)
    (frozenset({
        "tutor mode", "teach me", "i am learning", "i'm learning", "explain step by step",
        "supracloud trainer", "student", "homework", "tutor", "socratic",
        "help me understand", "i don't understand", "guide me through",
    }), "tutor"),
    # Digital brain — OS/browser control (Phase 6)
    (frozenset({
        "open vscode", "open vs code", "open terminal", "open chrome", "open firefox",
        "open application", "launch app", "start application",
        "browse website", "browse this url", "summarize website", "scan this website",
        "what does this website say", "go to url", "check this link",
    }), "digital"),
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

_VALID_AGENTS = {
    "conversational", "researcher", "security", "website", "creator", "executor",
    "career", "tutor", "digital",
}

# ── Restricted domain classification ─────────────────────────────────────────
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
    "my calendar", "my appointment", "my meeting",
    "personal", "private",
    # Fix #76: owner's first name removed from the static set — it is added
    # dynamically in is_restricted_domain() via cfg.owner_name so it works
    # for any owner without a code change.
    "my email", "my phone", "my address",
    # System control commands (specific phrases only — 'owner' removed: too generic)
    "lockdown system", "shutdown ira", "delete backups", "disable security",
    # Financial
    "financial", "revenue", "invoice", "payment", "bank",
    "company finances", "profit", "loss",
    # Core architecture / source code
    "internal code", "show me the code",
    "database schema", "db schema", "table structure",
    # Admin actions
    "create user", "delete user", "reset password", "change password",
    "grant access", "revoke access",
})


def is_restricted_domain(query: str) -> bool:
    """
    Return True if the query touches any owner-gated restricted domain.

    Fix #76: the owner's first name is checked dynamically (read from
    cfg.owner_name at call time) rather than being hardcoded in the static
    keyword set — works for any deployment without a code change.
    """
    from config import get_settings
    q = query.lower()
    if any(kw in q for kw in _RESTRICTED_KEYWORDS):
        return True
    # Owner's first name (e.g. "Praveen") should gate personal data queries
    owner_first = get_settings().owner_name.split()[0].lower()
    return bool(owner_first and owner_first in q)


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
- career          resume, job application, GitHub analysis, interview prep, job scraping
- tutor           teaching, explaining step by step, student learning, Socratic guidance
- digital         open app, browse website, run terminal command, OS control

Reply with the single category word and nothing else.\
"""


async def classify(state: IRAState) -> IRAState:
    """
    Classify the query and set active_agent + use_deep_model.

    Priority order:
      1. mode="tutor" in state → force tutor (unless security/executor)
      2. URL-dominant message → digital agent
      3. Keyword fast-path
      4. LLM fallback for long ambiguous queries
    """
    raw_query = state["user_query"]
    query = raw_query.lower()
    agent = "conversational"

    # 1. Mode override — frontend tutor toggle forces tutor persona
    if state.get("mode") == "tutor":
        # Tutor mode overrides everything except security and executor
        agent = "tutor"
    # 2. URL-dominant messages → digital agent (cache match to avoid double regex call)
    elif (url_match := _URL_RE.search(raw_query)) and len(raw_query.split()) < 30:
        url = url_match.group(0)
        if not any(site in url for site in ("linkedin.com/jobs", "indeed.com")):
            agent = "digital"

    # 3. Keyword fast-path (only if not already overridden)
    if agent == "conversational":
        for keywords, agent_name in _AGENT_RULES:
            if any(kw in query for kw in keywords):
                agent = agent_name
                break

    # 4. LLM fallback for long queries that matched no keyword
    if agent == "conversational" and len(raw_query.split()) > 15:
        try:
            from utils.llm import chat_complete
            result = await chat_complete(
                [
                    {"role": "system", "content": _LLM_ROUTER_SYSTEM},
                    {"role": "user", "content": raw_query},
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

    # Tutor mode: re-apply override in case keyword routing won over it
    # (only when the frontend explicitly set mode=tutor)
    if state.get("mode") == "tutor" and agent not in ("security", "executor"):
        agent = "tutor"

    return {
        **state,
        "active_agent": agent,
        "use_deep_model": should_use_deep(raw_query, agent),
    }
