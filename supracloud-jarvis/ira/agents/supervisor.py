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
from utils.yaml_config import get_agent_rules

_URL_RE = re.compile(r"https?://\S+")

_VALID_AGENTS = {
    "conversational", "researcher", "security", "website", "creator", "executor",
    "career", "tutor", "digital",
}


def is_restricted_domain(query: str) -> bool:
    """
    Return True if the query touches any owner-gated restricted domain.

    V1·Phase 3: delegated to the unified ``ira.security.owner_gate`` so the graph
    (biometric) gate and the router gate share ONE classifier and can no longer
    drift. The owner-only signal is the fail-closed union of regex intent, the
    config/routing.yaml ``restricted_keywords`` list, and the owner's first name
    (still read dynamically from Settings at call time, per Fix #76).
    """
    from security.owner_gate import is_owner_only

    return is_owner_only(query)


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
    # Rules loaded from config/routing.yaml (cached after first call)
    if agent == "conversational":
        for keywords, agent_name in get_agent_rules():
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
