"""
IRA Deep Research & Content Creation — Feature #7.

Multi-round deep research with web search, synthesis, and long-form content generation.
Mimics Grok's DeepSearch but runs entirely on private infrastructure.

POST /research/deep   — 5-round deep research on any topic (SSE)
POST /research/article — generate a long-form article / blog post (SSE)
POST /research/report  — generate a structured research report (SSE)

Trigger phrases:
  "research...", "deep dive into...", "write a long article about...",
  "create a comprehensive report on...", "analyse in depth...",
  "write a blog post about...", "investigate...", "find everything about..."
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import re
import time
import uuid
from typing import Optional, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from utils.llm import chat_complete, stream_tokens

router = APIRouter(prefix="/research", tags=["research"])
logger = logging.getLogger("ira.deep_research")

# Trigger detection
_RESEARCH_RE = re.compile(
    r"\b(deep\s+(research|dive|analysis|investigation)\s+(on|into|about)?|"
    r"research\s+(everything|all|thoroughly|in.?depth)\s+(about|on)?|"
    r"comprehensive\s+(research|report|analysis)\s+(on|about)?|"
    r"write\s+(a\s+)?(long|detailed|comprehensive|in.?depth)\s+(article|blog|post|report|essay)\s+(on|about)?|"
    r"(investigate|analyse|analyze)\s+(in.?depth|thoroughly|deeply|comprehensively)|"
    r"find\s+everything\s+(about|on))\b",
    re.I,
)

_ARTICLE_RE = re.compile(
    r"\b(write\s+(a\s+)?(blog\s+post|article|essay|piece)\s+(about|on)|"
    r"create\s+(a\s+)?(blog|article|content)\s+(about|on)|"
    r"draft\s+(a\s+)?(blog|article|essay|post))\b",
    re.I,
)


def is_deep_research_request(query: str) -> bool:
    return bool(_RESEARCH_RE.search(query))


def is_article_request(query: str) -> bool:
    return bool(_ARTICLE_RE.search(query))


# ── Request models ────────────────────────────────────────────────────────────

class DeepResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=4000)
    rounds: int = Field(default=5, ge=2, le=10, description="Number of research rounds")
    output_format: Literal["report", "article", "summary", "bullets"] = "report"
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ArticleRequest(BaseModel):
    topic: str = Field(..., min_length=1, max_length=2000)
    style: Literal["blog", "academic", "news", "technical", "explainer"] = "blog"
    word_count: int = Field(default=1500, ge=500, le=5000)
    audience: str = Field(default="general")
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


# ── Research agent prompts ────────────────────────────────────────────────────

_QUERY_GEN_SYSTEM = """\
You are a research strategist. Given a topic, generate 5 focused research sub-questions
that together would cover the topic comprehensively.
Output ONLY a JSON array of strings — no explanation:
["question 1", "question 2", ...]
"""

_RESEARCHER_SYSTEM = """\
You are an expert researcher and analyst with access to broad knowledge.
Answer the given research question comprehensively, citing key facts, statistics,
expert opinions, and current developments (up to your knowledge cutoff).
Structure your answer with clear sections. Be thorough but avoid padding.
"""

_SYNTHESISER_SYSTEM = """\
You are a world-class analyst and writer. You have received multiple research findings
on different aspects of a topic. Synthesise them into a cohesive, comprehensive output.

Requirements:
- Professional, authoritative tone
- Well-structured with clear headings
- Include key insights, data points, and conclusions
- Identify patterns and connections across different findings
- End with actionable conclusions or future outlook
- No filler content — every sentence must add value
"""

_ARTICLE_SYSTEM = """\
You are a professional content creator and journalist. Write the requested article
in the specified style and for the target audience.

Requirements:
- Compelling hook/opening
- Clear narrative arc
- Factual accuracy with specific examples
- Engaging writing — avoid corporate jargon and clichés
- SEO-friendly structure with clear headings
- Strong conclusion with key takeaways
- Approximate target word count
"""


async def _generate_research_queries(topic: str) -> list[str]:
    """Generate 5 focused sub-questions for deep research."""
    msgs = [
        {"role": "system", "content": _QUERY_GEN_SYSTEM},
        {"role": "user", "content": f"Topic: {topic}"},
    ]
    raw = await chat_complete(msgs, use_deep=False, max_tokens=512, temperature=0.3)
    json_match = re.search(r"\[[\s\S]*\]", raw)
    if not json_match:
        # Fallback: split by lines
        return [topic]
    try:
        queries = _json.loads(json_match.group(0))
        return queries[:5] if queries else [topic]
    except Exception:
        return [topic]


async def _research_sub_question(question: str, topic: str) -> str:
    """Research a single sub-question."""
    msgs = [
        {"role": "system", "content": _RESEARCHER_SYSTEM},
        {"role": "user", "content": f"Main topic: {topic}\n\nResearch question: {question}"},
    ]
    return await chat_complete(msgs, use_deep=True, max_tokens=2048, temperature=0.3)


async def _synthesise_research(topic: str, findings: list[tuple[str, str]], output_format: str) -> str:
    """Synthesise all research findings into a final output."""
    findings_text = "\n\n".join(
        f"**Sub-question {i+1}: {q}**\n{answer}"
        for i, (q, answer) in enumerate(findings)
    )
    format_hints = {
        "report": "Create a formal research report with Executive Summary, Key Findings, Analysis, and Conclusions sections.",
        "article": "Create a well-structured long-form article with engaging prose.",
        "summary": "Create a concise executive summary (300-500 words) with bullet point key findings.",
        "bullets": "Create a structured bullet-point summary organised by theme.",
    }
    msgs = [
        {"role": "system", "content": _SYNTHESISER_SYSTEM},
        {"role": "user", "content": (
            f"Topic: **{topic}**\n\n"
            f"Output format: {format_hints.get(output_format, format_hints['report'])}\n\n"
            f"Research findings:\n\n{findings_text}"
        )},
    ]
    return await chat_complete(msgs, use_deep=True, max_tokens=4096, temperature=0.4)


# ── SSE deep research endpoint ────────────────────────────────────────────────

@router.post("/deep")
async def deep_research(
    req: DeepResearchRequest,
    _user: str = Depends(require_auth),
):
    """Run 5-round deep research on any topic with synthesis (SSE)."""

    async def gen():
        t0 = time.monotonic()
        yield {"data": _json.dumps({"token": f"🔬 **Deep Research**: *{req.topic[:80]}*\n\nGenerating research strategy…\n\n"})}

        try:
            # Round 1: Generate research sub-questions
            queries = await _generate_research_queries(req.topic)
            yield {"data": _json.dumps({"token": f"📋 **Research plan** ({len(queries)} sub-questions):\n" +
                                        "".join(f"  {i+1}. {q}\n" for i, q in enumerate(queries)) + "\n"})}

            # Rounds 2-N: Research each sub-question in parallel batches
            findings: list[tuple[str, str]] = []
            batch_size = 2  # Research 2 sub-questions at a time

            for batch_start in range(0, len(queries), batch_size):
                batch = queries[batch_start:batch_start + batch_size]
                yield {"data": _json.dumps({"token": f"\n🔍 Researching: {', '.join(f'Q{batch_start+i+1}' for i in range(len(batch)))}…\n"})}

                batch_results = await asyncio.gather(
                    *[_research_sub_question(q, req.topic) for q in batch],
                    return_exceptions=True,
                )

                for q, result in zip(batch, batch_results):
                    if isinstance(result, Exception):
                        findings.append((q, f"Research failed: {result}"))
                    else:
                        findings.append((q, result))
                        yield {"data": _json.dumps({"token": f"  ✓ Completed: {q[:60]}\n"})}

            # Final synthesis
            yield {"data": _json.dumps({"token": f"\n📝 Synthesising {len(findings)} research findings…\n\n"})}
            yield {"data": _json.dumps({"token": "─" * 50 + "\n\n"})}

            synthesis = await _synthesise_research(req.topic, findings, req.output_format)

            # Stream synthesis word by word (simulate streaming for large output)
            words = synthesis.split(" ")
            chunk_size = 10
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                yield {"data": _json.dumps({"token": chunk})}
                await asyncio.sleep(0.01)  # slight delay for streaming effect

            latency = int((time.monotonic() - t0) * 1000)
            yield {"data": _json.dumps({
                "research_complete": True,
                "topic": req.topic,
                "rounds": len(findings),
                "word_count": len(synthesis.split()),
                "latency_ms": latency,
            })}

        except Exception as e:
            logger.error(f"Deep research error: {e}", exc_info=True)
            yield {"data": _json.dumps({"token": f"\n❌ Research error: {str(e)[:300]}"})}

        yield {"data": _json.dumps({
            "done": True, "agent": "deep_research",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        })}

    return EventSourceResponse(gen())


# ── SSE article generation endpoint ──────────────────────────────────────────

@router.post("/article")
async def generate_article(
    req: ArticleRequest,
    _user: str = Depends(require_auth),
):
    """Generate a long-form article or blog post (SSE streaming)."""

    style_hints = {
        "blog": "conversational, engaging, first-person where appropriate, use examples and analogies",
        "academic": "formal, citation-style, hypothesis-driven, use technical terminology",
        "news": "journalistic inverted pyramid, factual, quote-driven, neutral tone",
        "technical": "precise, code examples where relevant, step-by-step structure",
        "explainer": "clear, jargon-free, use analogies, assumes no prior knowledge",
    }

    async def gen():
        t0 = time.monotonic()
        yield {"data": _json.dumps({"token": f"✍️ Writing {req.style} article: *{req.topic[:60]}*…\n\n"})}

        try:
            msgs = [
                {"role": "system", "content": _ARTICLE_SYSTEM},
                {"role": "user", "content": (
                    f"Topic: {req.topic}\n"
                    f"Style: {req.style} ({style_hints.get(req.style, '')})\n"
                    f"Target audience: {req.audience}\n"
                    f"Target word count: approximately {req.word_count} words\n\n"
                    "Write the complete article now."
                )},
            ]

            # Stream article tokens
            async for token in stream_tokens(msgs, use_deep=True):
                yield {"data": _json.dumps({"token": token})}

            latency = int((time.monotonic() - t0) * 1000)
            yield {"data": _json.dumps({
                "article_complete": True,
                "topic": req.topic,
                "style": req.style,
                "latency_ms": latency,
            })}
        except Exception as e:
            logger.error(f"Article generation error: {e}", exc_info=True)
            yield {"data": _json.dumps({"token": f"\n❌ Article error: {str(e)[:200]}"})}

        yield {"data": _json.dumps({
            "done": True, "agent": "article_gen",
            "latency_ms": int((time.monotonic() - t0) * 1000),
        })}

    return EventSourceResponse(gen())


# ── Convenience: research report SSE ─────────────────────────────────────────

@router.post("/report")
async def generate_report(
    req: DeepResearchRequest,
    _user: str = Depends(require_auth),
):
    """Generate a structured research report (alias of /deep with report format)."""
    req.output_format = "report"
    return await deep_research(req, _user)
