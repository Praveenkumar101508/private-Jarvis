"""Web-grounded multi-step deep-research engine.

IRA's original /research/deep endpoint was *closed-book*: it asked the model to
answer sub-questions from its own training knowledge and never read a single
live source. This engine makes deep research actually grounded, reusing IRA's
existing sovereign-web layer so every byte of fetched content is sanitised and
every fetch is egress-guarded.

Design adapted (NOT copied) from the multi-step deep-research pattern popularised
by Odysseus (MIT, github.com/pewdiepie-archdaemon/odysseus) and Alibaba's Tongyi
DeepResearch (Apache-2.0): plan → search → read sources → synthesise, with
explicit handling of the failure modes those pipelines hit in the wild —
dead/unreachable sources, contradictory sources, and runaway fetch loops. No
upstream source code is vendored; only the orchestration shape is borrowed.

Trust model (this is the whole point):
  * Search/read go through ``channels.*`` which wrap every result via
    ``utils.prompt_safety.wrap_external_content`` — so fetched text arrives
    already delimited as UNTRUSTED DATA. We only treat WRAPPED content as usable
    evidence; an unwrapped string means the channel failed soft (a dead source).
  * Every candidate URL is run through the egress guard before fetching, so a
    page that says "now fetch http://169.254.169.254/…" cannot make us reach an
    internal target.
  * Synthesis uses ``build_grounded_prompt`` which keeps each source inside its
    delimiters and tells the model to report — never obey — embedded instructions.

The orchestrator takes injectable ``search_fn`` / ``read_fn`` / ``guard_fn`` /
``llm_fn`` callables (defaulting to the real channels) so it is fully testable
without network, LLM, or the Cortex bridge.
"""
from __future__ import annotations

import json as _json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from utils.prompt_safety import (
    _DELIM_OPEN,
    build_grounded_prompt,
    check_adversarial_content,
)

logger = logging.getLogger("ira.deep_research_engine")

# Type aliases for the injectable dependencies.
SearchFn = Callable[[str], Awaitable[str]]
ReadFn = Callable[[str], Awaitable[str]]
GuardFn = Callable[[str], Optional[str]]
LLMFn = Callable[..., Awaitable[str]]
EventFn = Callable[[str], None]

_URL_RE = re.compile(r"https?://[^\s\)\]\}>\"'`]+")

_QUERY_GEN_SYSTEM = (
    "You are a research strategist. Given a topic, generate focused research "
    "sub-questions that together cover the topic comprehensively.\n"
    "Output ONLY a JSON array of strings — no explanation:\n"
    '["question 1", "question 2", ...]'
)

_SYNTH_SYSTEM = (
    "You are a rigorous research analyst. You synthesise findings from retrieved "
    "sources into a clear, well-structured, comprehensive answer. You cite sources, "
    "never fabricate, and you surface disagreements between sources explicitly."
)


@dataclass
class Evidence:
    """A single usable (wrapped, sanitised) source."""

    url: str
    content: str  # already wrapped as untrusted data by the channel


@dataclass
class DeepResearchResult:
    topic: str
    report: str
    subquestions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    dead_sources: list[str] = field(default_factory=list)
    fetches_used: int = 0
    grounded: bool = False
    # Audit: injection patterns seen in fetched content (logged, never obeyed).
    injection_flags: list[str] = field(default_factory=list)


def _extract_urls(text: str) -> list[str]:
    """Pull de-duplicated http(s) URLs out of a (wrapped) search result blob."""
    out: list[str] = []
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(".,;)")
        if url not in out:
            out.append(url)
    return out


def _is_usable(content: str) -> bool:
    """A successful channel fetch is wrapped in the untrusted-data delimiters.

    Fail-soft channel responses ("Web read failed…", "…unavailable", "No web
    results…") are plain strings with no delimiter, so this both detects dead
    sources AND enforces that only sanitised content ever becomes evidence.
    """
    return bool(content) and _DELIM_OPEN in content


# ── default dependencies (lazy imports keep this module import-light) ─────────

async def _default_search(query: str) -> str:
    from channels import search as _search
    return await _search(query)


async def _default_read(url: str) -> str:
    from channels import read as _read
    return await _read(url)


def _default_guard(url: str) -> Optional[str]:
    from utils.net_safety import guard_outbound
    return guard_outbound(url=url)


async def _default_llm(messages, **kwargs) -> str:
    from utils.llm import chat_complete
    return await chat_complete(messages, **kwargs)


def _noop_event(_msg: str) -> None:  # pragma: no cover - trivial
    pass


async def plan_subquestions(topic: str, llm_fn: LLMFn, n: int = 5) -> list[str]:
    """Decompose a topic into <=n focused sub-questions (falls back to the topic)."""
    msgs = [
        {"role": "system", "content": _QUERY_GEN_SYSTEM},
        {"role": "user", "content": f"Topic: {topic}\nGenerate {n} sub-questions."},
    ]
    try:
        raw = await llm_fn(msgs, use_deep=False, max_tokens=512, temperature=0.3)
    except Exception as exc:  # noqa: BLE001 — planning must not abort research
        logger.warning("sub-question planning failed: %s", exc)
        return [topic]
    match = re.search(r"\[[\s\S]*\]", raw or "")
    if not match:
        return [topic]
    try:
        items = _json.loads(match.group(0))
        cleaned = [str(q).strip() for q in items if str(q).strip()]
        return cleaned[:n] or [topic]
    except Exception:  # noqa: BLE001
        return [topic]


async def gather_evidence(
    subquestions: list[str],
    *,
    search_fn: SearchFn,
    read_fn: ReadFn,
    guard_fn: GuardFn,
    max_sources_per_subq: int,
    max_total_fetches: int,
    deadline: float,
    on_event: EventFn,
    injection_flags: list[str],
) -> tuple[list[Evidence], list[str], int]:
    """Search each sub-question and read a bounded set of guarded sources.

    Returns (usable_evidence, dead_source_urls, fetches_used). Robust to the three
    classic failure modes: dead sources are recorded and skipped, the global URL
    set is de-duplicated (no fetch loops), and the deadline / fetch caps bound the
    total work.
    """
    seen: set[str] = set()
    evidence: list[Evidence] = []
    dead: list[str] = []
    fetches = 0

    for sq in subquestions:
        if fetches >= max_total_fetches or time.monotonic() > deadline:
            break
        blob = await search_fn(sq)
        injection_flags.extend(check_adversarial_content(blob))
        taken = 0
        for url in _extract_urls(blob):
            if fetches >= max_total_fetches or time.monotonic() > deadline:
                break
            if taken >= max_sources_per_subq:
                break
            if url in seen:
                continue  # fetch-loop / duplicate protection
            seen.add(url)

            refusal = guard_fn(url)
            if refusal:
                # Egress guard blocks internal/private/non-http targets even if a
                # page or search result tried to point us at one.
                logger.info("egress-guard blocked source %s: %s", url, refusal)
                on_event(f"skipped (guarded): {url}")
                continue

            content = await read_fn(url)
            fetches += 1
            flags = check_adversarial_content(content)
            if flags:
                injection_flags.extend(flags)
                logger.warning("prompt-injection patterns in %s: %s", url, flags)

            if _is_usable(content):
                evidence.append(Evidence(url=url, content=content))
                taken += 1
                on_event(f"read source: {url}")
            else:
                dead.append(url)  # fail-soft / unwrapped → dead source
                on_event(f"dead source: {url}")

    return evidence, dead, fetches


async def synthesize(topic: str, evidence: list[Evidence], llm_fn: LLMFn) -> str:
    """Synthesise a grounded answer; sources stay inside untrusted delimiters."""
    blocks = [e.content for e in evidence]
    msgs = [
        {"role": "system", "content": _SYNTH_SYSTEM},
        {"role": "user", "content": build_grounded_prompt(topic, blocks)},
    ]
    return await llm_fn(msgs, use_deep=True, max_tokens=4096, temperature=0.4)


async def run_deep_research(
    topic: str,
    *,
    num_subquestions: int = 5,
    max_sources_per_subq: int = 3,
    max_total_fetches: int = 12,
    timeout_s: float = 90.0,
    search_fn: Optional[SearchFn] = None,
    read_fn: Optional[ReadFn] = None,
    guard_fn: Optional[GuardFn] = None,
    llm_fn: Optional[LLMFn] = None,
    on_event: Optional[EventFn] = None,
) -> DeepResearchResult:
    """Run a grounded multi-step deep-research pass over ``topic``.

    Plans sub-questions, searches + reads bounded guarded sources for each, then
    synthesises a cited answer. Always returns a result: if no sources can be
    retrieved it falls back to an explicitly-ungrounded answer.
    """
    search_fn = search_fn or _default_search
    read_fn = read_fn or _default_read
    guard_fn = guard_fn or _default_guard
    llm_fn = llm_fn or _default_llm
    on_event = on_event or _noop_event

    deadline = time.monotonic() + timeout_s
    injection_flags: list[str] = []

    subquestions = await plan_subquestions(topic, llm_fn, n=num_subquestions)
    on_event(f"planned {len(subquestions)} sub-questions")

    evidence, dead, fetches = await gather_evidence(
        subquestions,
        search_fn=search_fn,
        read_fn=read_fn,
        guard_fn=guard_fn,
        max_sources_per_subq=max_sources_per_subq,
        max_total_fetches=max_total_fetches,
        deadline=deadline,
        on_event=on_event,
        injection_flags=injection_flags,
    )

    on_event(f"synthesising from {len(evidence)} sources ({len(dead)} dead)")
    report = await synthesize(topic, evidence, llm_fn)

    return DeepResearchResult(
        topic=topic,
        report=report,
        subquestions=subquestions,
        citations=[e.url for e in evidence],
        dead_sources=dead,
        fetches_used=fetches,
        grounded=bool(evidence),
        injection_flags=sorted(set(injection_flags)),
    )


__all__ = [
    "DeepResearchResult",
    "Evidence",
    "plan_subquestions",
    "gather_evidence",
    "synthesize",
    "run_deep_research",
]
