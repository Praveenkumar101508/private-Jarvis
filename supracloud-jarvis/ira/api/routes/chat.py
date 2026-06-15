"""
Chat endpoints — the core Jarvis interface.

POST /chat          → standard JSON response (full reply in one shot)
POST /chat/stream   → Server-Sent Events (token-by-token streaming)
GET  /chat/history  → retrieve conversation history
"""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from agents.graph import run_graph
from memory.store import ensure_conversation, get_recent_messages
from utils.llm import stream_tokens, should_use_deep
from utils.redis_client import cache_get, cache_set

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Request / Response models ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=32_000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    stream: bool = False


class ChatResponse(BaseModel):
    response: str
    session_id: str
    conversation_id: str
    agent_used: str
    model_used: str
    latency_ms: int


class HistoryMessage(BaseModel):
    role: str
    content: str


class HistoryResponse(BaseModel):
    session_id: str
    conversation_id: str
    messages: list[HistoryMessage]


# ── Standard (non-streaming) chat ─────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    _user: str = Depends(require_auth),
):
    # Check response cache (keyed on session + message hash)
    cache_key = f"chat:{req.session_id}:{hash(req.message)}"
    cached = await cache_get(cache_key)
    if cached:
        return ChatResponse(**cached)

    conv_id = await ensure_conversation(req.session_id)

    state = await run_graph(
        session_id=req.session_id,
        conversation_id=conv_id,
        user_query=req.message,
    )

    result = ChatResponse(
        response=state["final_response"],
        session_id=req.session_id,
        conversation_id=conv_id,
        agent_used=state.get("active_agent", "conversational"),
        model_used=state.get("model_used", "llama-fast"),
        latency_ms=state.get("latency_ms", 0),
    )

    # Cache simple conversational responses for 60s (not security/exec responses)
    if state.get("active_agent") in ("conversational", "researcher"):
        await cache_set(cache_key, result.model_dump(), ttl=60)

    return result


# ── Streaming chat (SSE) ───────────────────────────────────────────────────────

@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    _user: str = Depends(require_auth),
):
    """
    Stream token-by-token via Server-Sent Events.
    Client receives: data: {"token": "..."} events, then data: {"done": true}.
    """
    conv_id = await ensure_conversation(req.session_id)
    use_deep = should_use_deep(req.message)

    # Build the system + user messages (simplified — no full graph for streaming path)
    from agents.conversational import IRA_SYSTEM
    from memory.store import retrieve

    memories = await retrieve(req.message)
    memory_ctx = "\n".join(m["content"] for m in memories) if memories else ""

    messages = [{"role": "system", "content": IRA_SYSTEM}]
    if memory_ctx:
        messages.append({"role": "system", "content": f"Relevant memory:\n{memory_ctx}"})

    recent = await get_recent_messages(conv_id, limit=10)
    messages.extend(recent)
    messages.append({"role": "user", "content": req.message})

    async def event_generator():
        full_response = []
        t0 = time.monotonic()

        try:
            async for token in stream_tokens(messages, use_deep=use_deep):
                full_response.append(token)
                yield {"data": f'{{"token": {repr(token)}}}'}

            # Signal completion with metadata
            latency = int((time.monotonic() - t0) * 1000)
            yield {
                "data": f'{{"done": true, "latency_ms": {latency}, "session_id": "{req.session_id}"}}'
            }

            # Store the complete interaction in the background
            from memory.store import save_message
            asyncio.create_task(save_message(conv_id, "user", req.message))
            asyncio.create_task(save_message(
                conv_id, "assistant", "".join(full_response),
                model_used="qwen-deep" if use_deep else "llama-fast",
                latency_ms=latency,
            ))

        except Exception as e:
            yield {"data": f'{{"error": "Stream interrupted: {str(e)[:100]}"}}'}

    return EventSourceResponse(event_generator())


# ── Conversation history ───────────────────────────────────────────────────────

@router.get("/history", response_model=HistoryResponse)
async def history(
    session_id: str = Query(...),
    limit: int = Query(default=50, le=200),
    _user: str = Depends(require_auth),
):
    conv_id = await ensure_conversation(session_id)
    messages = await get_recent_messages(conv_id, limit=limit)
    return HistoryResponse(
        session_id=session_id,
        conversation_id=conv_id,
        messages=[HistoryMessage(**m) for m in messages],
    )
