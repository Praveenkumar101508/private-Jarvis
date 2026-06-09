"""
Web-research endpoints — route a query/URL to a local research channel, feed the
clean text into the reasoning context, and stream the answer (Prompt 3B.2).

POST /api/v1/research        — "search the web for X" or "read <url>"
GET  /api/v1/research/doctor — per-channel health (the `research doctor`)

Everything runs on the local channels (SearXNG / Crawl4AI / yt-dlp / GitHub / RSS);
channels fail soft, so an unavailable backend yields a clear message and the
conversation continues.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

import channels
from api.middleware.auth import require_auth
from memory.store import ensure_conversation
from utils.llm import stream_tokens

router = APIRouter(prefix="/research", tags=["research"])

_URL_RE = re.compile(r"https?://[^\s)>\]}]+")

_SYSTEM = (
    "You are IRA. Answer the user's question using ONLY the web research provided "
    "below. Cite source URLs when present. If the research does not contain the "
    "answer, say so plainly — do not invent facts."
)


class ResearchRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8_000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    url: str | None = Field(None, description="Explicit URL to read; else inferred from message")
    query: str | None = Field(None, description="Explicit search query; else the message")


@router.get("/doctor")
async def research_doctor(_user: str = Depends(require_auth)):
    """Report each research channel's status (the `research doctor`)."""
    return {"channels": await channels.doctor()}


@router.post("")
async def research(req: ResearchRequest, _user: str = Depends(require_auth)):
    """Search the web or read a URL via a local channel, then stream a grounded answer."""
    conv_id = await ensure_conversation(req.session_id)
    m = _URL_RE.search(req.message)
    url = req.url or (m.group(0) if m else None)

    async def gen():
        t0 = time.monotonic()
        try:
            if url:
                context = await channels.read(url)
                source = f"read {url}"
            else:
                query = req.query or req.message
                context = await channels.search(query)
                source = f"web search: {query}"

            messages = [
                {"role": "system", "content": _SYSTEM},
                {"role": "system", "content": f"Web research ({source}):\n{context}"},
                {"role": "user", "content": req.message},
            ]
            async for token in stream_tokens(messages, use_deep=False):
                yield {"data": json.dumps({"token": token})}

            yield {"data": json.dumps({
                "done": True, "agent": "research", "source": source,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "session_id": req.session_id,
            })}
        except Exception as e:  # noqa: BLE001 — never break the stream
            yield {"data": json.dumps({"error": f"Research error: {str(e)[:120]}"})}

    return EventSourceResponse(gen())
