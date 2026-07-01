"""
ira/reasoning/answer_verifier.py — rule-based pre-output answer verification.

Runs cheap, deterministic checks against a drafted answer before it ships to
the user for tasks that matter. Deliberately rule-based — NOT another model
call — so it stays fast and free by default. A host app MAY choose to escalate
a verifier finding to a second model pass; this module never does that
itself, and never blocks or rewrites an answer on its own — it only reports.

This module does not decide consent. It only reports when a decision it was
told about used an external provider without recorded approval — the actual
consent gate lives in ``reasoning/api_consent.py`` and is unaffected by
anything here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from reasoning.answer_policy import AnswerPolicy, TASK_CODING, TASK_DEBUGGING, TASK_RESEARCH

# ── Findings ─────────────────────────────────────────────────────────────────

ISSUE_OFF_TOPIC = "off_topic"
ISSUE_UNSAFE_EXTERNAL = "unsafe_external_use"
ISSUE_MISSING_CITATION = "missing_citation"
ISSUE_MISSING_TEST_STEP = "missing_test_step"
ISSUE_TOO_VAGUE = "too_vague"
ISSUE_UNSTATED_ASSUMPTIONS = "unstated_assumptions"


@dataclass(frozen=True)
class VerificationResult:
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return not self.issues

    def has(self, issue: str) -> bool:
        return issue in self.issues


_HEDGE_PHRASES = (
    "it depends", "there are many factors", "it varies", "hard to say",
    "i'm not sure", "i cannot know", "could be many things",
)

_VAGUE_MIN_CHARS = 40
_TEST_WORDS = ("test", "pytest", "verify", "assert", "run the suite", "check that")
_CITATION_MARKERS = ("http://", "https://", "source:", "[source", "according to")
_ASSUMPTION_MARKERS = ("assum", "if you mean", "assuming")
_AMBIGUOUS_PROMPT_MARKERS = (
    "best", "should i", "which one", "what should", "recommend", "better option",
)

_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "of", "to", "for", "and", "or", "in",
    "on", "my", "me", "please", "can", "you", "i", "it", "this", "that",
    "with", "what", "how", "do", "does", "be", "at", "as", "your",
})


def _shares_vocabulary(prompt: str, answer: str, *, min_overlap: int = 1) -> bool:
    """Cheap 'did we actually answer this' check: keyword overlap with the ask.

    Not NLP — a coarse floor that catches a wholly off-topic answer (near-zero
    shared vocabulary) without false-flagging normal paraphrasing.
    """
    prompt_words = {
        w for w in re.findall(r"[a-z0-9]+", prompt.lower())
        if w not in _STOPWORDS and len(w) > 2
    }
    if not prompt_words:
        return True
    answer_words = set(re.findall(r"[a-z0-9]+", answer.lower()))
    return len(prompt_words & answer_words) >= min_overlap


def verify_answer(
    prompt: str,
    answer: str,
    *,
    task_type: str = "general",
    policy: Optional[AnswerPolicy] = None,
    provider: str = "local",
    consent_approved: Optional[bool] = None,
) -> VerificationResult:
    """Run rule-based checks against a drafted ``answer`` before it ships.

    ``provider``/``consent_approved`` describe how the answer was produced —
    pass them straight through from the routing decision / consent flow so
    the verifier can flag external use that slipped past consent. It never
    makes the consent decision itself.
    """
    issues: list[str] = []
    stripped = (answer or "").strip()
    prompt = prompt or ""

    if provider == "external" and consent_approved is not True:
        issues.append(ISSUE_UNSAFE_EXTERNAL)

    if stripped and not _shares_vocabulary(prompt, stripped):
        issues.append(ISSUE_OFF_TOPIC)

    if len(stripped) < _VAGUE_MIN_CHARS or any(h in stripped.lower() for h in _HEDGE_PHRASES):
        issues.append(ISSUE_TOO_VAGUE)

    wants_test_step = task_type in (TASK_CODING, TASK_DEBUGGING) or (policy is not None and policy.requires_test_step)
    if wants_test_step and _looks_like_code(stripped) and not any(w in stripped.lower() for w in _TEST_WORDS):
        issues.append(ISSUE_MISSING_TEST_STEP)

    wants_citation = task_type == TASK_RESEARCH or (policy is not None and policy.requires_citation)
    if wants_citation and not any(m in stripped.lower() for m in _CITATION_MARKERS):
        issues.append(ISSUE_MISSING_CITATION)

    if _looks_ambiguous(prompt) and not _states_assumption(stripped):
        issues.append(ISSUE_UNSTATED_ASSUMPTIONS)

    return VerificationResult(tuple(issues))


def _looks_like_code(answer: str) -> bool:
    return "```" in answer or bool(re.search(r"\bdef |\bfunction |\bclass \w", answer))


def _looks_ambiguous(prompt: str) -> bool:
    text = prompt.lower()
    return any(m in text for m in _AMBIGUOUS_PROMPT_MARKERS)


def _states_assumption(answer: str) -> bool:
    text = answer.lower()
    return any(m in text for m in _ASSUMPTION_MARKERS) or "?" in answer


__all__ = [
    "VerificationResult",
    "verify_answer",
    "ISSUE_OFF_TOPIC",
    "ISSUE_UNSAFE_EXTERNAL",
    "ISSUE_MISSING_CITATION",
    "ISSUE_MISSING_TEST_STEP",
    "ISSUE_TOO_VAGUE",
    "ISSUE_UNSTATED_ASSUMPTIONS",
]
