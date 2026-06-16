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
from research.deep_research_engine import run_deep_research
from utils.llm import stream_tokens

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


# ── SSE deep research endpoint ────────────────────────────────────────────────

@router.post("/deep")
async def deep_research(
    req: DeepResearchRequest,
    _user: str = Depends(require_auth),
):
    """Run web-grounded multi-step deep research on any topic with synthesis (SSE).

    Sources are searched, guarded, fetched, and sanitised by the research channels;
    the engine handles dead/contradictory sources and bounds the fetch loop. We
    stream the engine's progress events in real time, then stream the synthesised
    report, and finish with a citation list.
    """

    async def gen():
        t0 = time.monotonic()
        yield {"data": _json.dumps({"token": f"🔬 **Deep Research**: *{req.topic[:80]}*\n\nPlanning & gathering sources…\n\n"})}

        # Bridge the engine's synchronous progress callback into the SSE stream
        # via a queue, so we can yield events while the engine runs.
        events: asyncio.Queue[str] = asyncio.Queue()
        task = asyncio.create_task(
            run_deep_research(
                req.topic,
                num_subquestions=req.rounds,
                on_event=lambda m: events.put_nowait(m),
            )
        )

        try:
            while True:
                drain = asyncio.ensure_future(events.get())
                done, _ = await asyncio.wait({task, drain}, return_when=asyncio.FIRST_COMPLETED)
                if drain in done:
                    yield {"data": _json.dumps({"token": f"  · {drain.result()}\n"})}
                    continue
                drain.cancel()  # task finished first
                # Flush any progress events queued before completion.
                while not events.empty():
                    yield {"data": _json.dumps({"token": f"  · {events.get_nowait()}\n"})}
                break

            result = await task  # re-raises engine errors here

            yield {"data": _json.dumps({"token": "\n" + "─" * 50 + "\n\n"})}
            if not result.grounded:
                yield {"data": _json.dumps({"token": "⚠️ No live sources retrieved — answering from model knowledge only.\n\n"})}

            # Stream the synthesised report word by word.
            words = result.report.split(" ")
            chunk_size = 10
            for i in range(0, len(words), chunk_size):
                chunk = " ".join(words[i:i + chunk_size])
                if i + chunk_size < len(words):
                    chunk += " "
                yield {"data": _json.dumps({"token": chunk})}
                await asyncio.sleep(0.01)

            if result.citations:
                cites = "\n".join(f"  {i+1}. {u}" for i, u in enumerate(result.citations))
                yield {"data": _json.dumps({"token": f"\n\n**Sources ({len(result.citations)}):**\n{cites}\n"})}

            yield {"data": _json.dumps({
                "research_complete": True,
                "topic": req.topic,
                "subquestions": result.subquestions,
                "citations": result.citations,
                "dead_sources": result.dead_sources,
                "fetches_used": result.fetches_used,
                "grounded": result.grounded,
                "word_count": len(result.report.split()),
                "latency_ms": int((time.monotonic() - t0) * 1000),
            })}

        except Exception as e:
            logger.error(f"Deep research error: {e}", exc_info=True)
            if not task.done():
                task.cancel()
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
