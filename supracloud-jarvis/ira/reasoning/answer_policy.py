"""
ira/reasoning/answer_policy.py — task-specific answer/output-style policy.

Given a user's request, picks *how the final answer should be shaped* —
independent of which model tier answers it (see
``reasoning/model_system_prompts.py`` for tier voice, and
``reasoning/model_router.py`` for tier selection). Rule-based only: no model
call is used to pick a policy, so this stays free and instant.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from reasoning.model_profiles import ModelMode
from reasoning.model_router import ModelRouteDecision

# ── Task types ───────────────────────────────────────────────────────────────

TASK_REWRITE = "rewrite"
TASK_CODING = "coding"
TASK_ARCHITECTURE = "architecture"
TASK_JOB_APPLICATION = "job_application"
TASK_RESEARCH = "research"
TASK_DEBUGGING = "debugging"
TASK_PLANNING = "planning"
TASK_SIMPLE_QUESTION = "simple_question"
TASK_GENERAL = "general"

ALL_TASK_TYPES = (
    TASK_REWRITE, TASK_CODING, TASK_ARCHITECTURE, TASK_JOB_APPLICATION,
    TASK_RESEARCH, TASK_DEBUGGING, TASK_PLANNING, TASK_SIMPLE_QUESTION, TASK_GENERAL,
)


@dataclass(frozen=True)
class AnswerPolicy:
    """The output shape a task type should get."""

    task_type: str
    instructions: str            # appended to the system prompt
    requires_citation: bool = False
    requires_test_step: bool = False


# Checked in this order — more specific task types win over generic "coding".
_ORDERED_TASKS = (
    TASK_DEBUGGING, TASK_ARCHITECTURE, TASK_JOB_APPLICATION,
    TASK_REWRITE, TASK_RESEARCH, TASK_PLANNING, TASK_CODING,
)

_KEYWORDS: dict[str, tuple[str, ...]] = {
    TASK_DEBUGGING: (
        "debug", "bug", "traceback", "stack trace", "error", "exception",
        "crash", "not working", "doesn't work", "broken", "fails",
    ),
    TASK_ARCHITECTURE: (
        "architecture", "architect", "design a system", "design the system",
        "system design", "scalab", "microservice", "infrastructure design",
        "high-level design",
    ),
    TASK_JOB_APPLICATION: (
        "cover letter", "resume", "cv ", "job application", "job posting",
        "linkedin message", "interview", "job offer", "apply for the role",
        "applying for the",
    ),
    TASK_REWRITE: (
        "rewrite", "reword", "polish", "proofread", "draft an email",
        "write an email", "edit this", "improve this", "make this sound",
    ),
    TASK_RESEARCH: (
        "research", "sources", "cite", "citation", "compare", "what is the latest",
        "find out", "look up", "survey of",
    ),
    TASK_PLANNING: (
        "plan", "roadmap", "phases", "milestones", "timeline", "prioritize",
        "next steps", "strategy for",
    ),
    TASK_CODING: (
        "code", "coding", "implement", "refactor", "function", "class ",
        "endpoint", "script", "unit test", "pytest", "pull request", "repo",
        "write a program", "regex",
    ),
}

_SIMPLE_MAX_WORDS = 8


def classify_task_type(prompt: str) -> str:
    """Rule-based task-type classification.

    Checks task types in :data:`_ORDERED_TASKS` order (most specific first),
    so e.g. "debug this function" is TASK_DEBUGGING, not the more generic
    TASK_CODING. Falls back to TASK_SIMPLE_QUESTION for short prompts and
    TASK_GENERAL otherwise.
    """
    text = (prompt or "").lower()
    words = text.split()

    for task in _ORDERED_TASKS:
        if any(kw in text for kw in _KEYWORDS[task]):
            return task

    if len(words) <= _SIMPLE_MAX_WORDS:
        return TASK_SIMPLE_QUESTION

    return TASK_GENERAL


_POLICIES: dict[str, AnswerPolicy] = {
    TASK_REWRITE: AnswerPolicy(
        task_type=TASK_REWRITE,
        instructions=(
            "Task type: rewrite/polish. Return the final, ready-to-send text "
            "as the primary output. Keep meta-commentary minimal — a one-line "
            "note on what changed is enough; do not re-explain the whole text."
        ),
    ),
    TASK_CODING: AnswerPolicy(
        task_type=TASK_CODING,
        instructions=(
            "Task type: coding. Give the code, a short explanation of what it "
            "does and why, and a concrete test or verification step (how to "
            "confirm it works). Call out anything that could break existing "
            "behaviour."
        ),
        requires_test_step=True,
    ),
    TASK_ARCHITECTURE: AnswerPolicy(
        task_type=TASK_ARCHITECTURE,
        instructions=(
            "Task type: architecture. Structure the answer as: a "
            "components/diagram-like breakdown, key trade-offs, risks, and "
            "concrete next steps. Prefer a labelled list of parts over a "
            "wall of prose."
        ),
    ),
    TASK_JOB_APPLICATION: AnswerPolicy(
        task_type=TASK_JOB_APPLICATION,
        instructions=(
            "Task type: job/application. Be concise and professional — no "
            "filler, no generic praise, specific and confident. Match the "
            "register of a strong candidate, not a template."
        ),
    ),
    TASK_RESEARCH: AnswerPolicy(
        task_type=TASK_RESEARCH,
        instructions=(
            "Task type: research. Cite sources when you have them (inline, "
            "by name or URL). If a claim isn't grounded in a source you were "
            "given or clearly know to be true, say so rather than presenting "
            "it as fact."
        ),
        requires_citation=True,
    ),
    TASK_DEBUGGING: AnswerPolicy(
        task_type=TASK_DEBUGGING,
        instructions=(
            "Task type: debugging. Structure the answer as: root cause, "
            "fix, and how to verify the fix worked. Don't just paste a "
            "patch — say why it was broken."
        ),
        requires_test_step=True,
    ),
    TASK_PLANNING: AnswerPolicy(
        task_type=TASK_PLANNING,
        instructions=(
            "Task type: planning. Structure the answer as phases or steps, "
            "each with a priority or rough ordering. Be concrete about what "
            "happens first and why."
        ),
    ),
    TASK_SIMPLE_QUESTION: AnswerPolicy(
        task_type=TASK_SIMPLE_QUESTION,
        instructions=(
            "Task type: simple question. Give a short, direct answer. Do "
            "not add structure, caveats, or sections the question didn't "
            "ask for."
        ),
    ),
    TASK_GENERAL: AnswerPolicy(
        task_type=TASK_GENERAL,
        instructions=(
            "Give a clear, well-organised answer sized to the question — no "
            "more structure than the content actually needs."
        ),
    ),
}


def get_policy(task_type: str) -> AnswerPolicy:
    """Return the :class:`AnswerPolicy` for ``task_type`` (never raises)."""
    return _POLICIES.get(task_type, _POLICIES[TASK_GENERAL])


def policy_for_prompt(prompt: str) -> AnswerPolicy:
    """Classify ``prompt`` and return its :class:`AnswerPolicy` in one call."""
    return get_policy(classify_task_type(prompt))


# ── Local-first fallback framing ────────────────────────────────────────────

_LOCAL_MODE_NOTICE = "Continuing in Local Mode."


def local_fallback_notice(decision: ModelRouteDecision) -> Optional[str]:
    """A short, honest framing note for a degraded (fallback) local answer.

    Returns ``None`` when the router used something other than the terminal
    fallback tier (no meaningful degradation happened) — callers should only
    surface this note when it's non-None, and should never fabricate a
    "weak model" apology on their own. Only offers Deep Intelligence Mode
    when the routing decision itself flagged the task as needing it
    (``requires_api_consent``); this function never grants or requests
    consent itself — see ``reasoning/api_consent.py`` for that gate.
    """
    if decision.selected_mode != ModelMode.FALLBACK_TINY:
        return None
    note = _LOCAL_MODE_NOTICE
    if decision.requires_api_consent:
        note += (
            " This task may benefit from Deep Intelligence Mode — ask if "
            "you'd like to enable it."
        )
    return note


__all__ = [
    "AnswerPolicy",
    "classify_task_type",
    "get_policy",
    "policy_for_prompt",
    "local_fallback_notice",
    "TASK_REWRITE",
    "TASK_CODING",
    "TASK_ARCHITECTURE",
    "TASK_JOB_APPLICATION",
    "TASK_RESEARCH",
    "TASK_DEBUGGING",
    "TASK_PLANNING",
    "TASK_SIMPLE_QUESTION",
    "TASK_GENERAL",
    "ALL_TASK_TYPES",
]
