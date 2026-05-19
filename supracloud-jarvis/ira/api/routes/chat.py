"""
Chat endpoints — the core Jarvis interface.

POST /chat          → standard JSON response (full reply in one shot)
POST /chat/stream   → Server-Sent Events (token-by-token streaming)
GET  /chat/history  → retrieve conversation history

Biometric gate: every request carries an `is_owner` flag derived from the
authenticated admin username. The LangGraph biometric_gate node uses this flag
to allow or block access to restricted domains (security logs, personal data, etc.).
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from agents.graph import run_graph
from memory.store import ensure_conversation, get_recent_messages, retrieve
from utils.llm import stream_tokens, should_use_deep
from utils.redis_client import cache_get, cache_set
from config import get_settings

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


def _is_owner(username: str) -> bool:
    """Return True if the authenticated user is the system owner (admin)."""
    cfg = get_settings()
    return username == cfg.ira_admin_username


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
        is_owner=_is_owner(_user),
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
    Token-by-token streaming via SSE, correctly routed through the supervisor
    and biometric gate.

    Flow: supervisor classify → biometric gate → agent system prompt → vLLM stream → SSE tokens.
    Client receives: data: {"token": "..."} events, then data: {"done": true, "agent": "..."}.
    """
    conv_id = await ensure_conversation(req.session_id)
    owner = _is_owner(_user)

    # Classify the query through the supervisor (keyword fast-path + LLM fallback)
    from agents.state import IRAState
    from agents.supervisor import classify, is_restricted_domain
    from langchain_core.messages import HumanMessage

    temp_state: IRAState = {
        "messages": [HumanMessage(content=req.message)],
        "session_id": req.session_id,
        "conversation_id": conv_id,
        "user_query": req.message,
        "active_agent": "conversational",
        "use_deep_model": False,
        "memory_context": "",
        "final_response": "",
        "stream_tokens": [],
        "latency_ms": 0,
        "model_used": "llama-fast",
        "is_owner": owner,
        "clearance_level": "admin" if owner else "public",
        "error": None,
    }
    classified = await classify(temp_state)
    active_agent = classified["active_agent"]
    use_deep = classified["use_deep_model"]

    # ── Biometric gate: block restricted domains for non-owners ───────────────
    if is_restricted_domain(req.message) and not owner:
        async def blocked_generator():
            cfg = get_settings()
            owner_name = cfg.owner_name
            blocked_msg = (
                f"I'm sorry, I'm an automated assistant for SupraCloud. "
                f"That administrative information is strictly restricted to "
                f"{owner_name}, the company founder. "
                f"I cannot share security logs, personal data, or system credentials "
                f"with anyone else. Is there something else I can help you with?"
            )
            for word in blocked_msg.split(" "):
                yield {"data": json.dumps({"token": word + " "})}
                await asyncio.sleep(0.02)
            yield {"data": json.dumps({
                "done": True, "agent": "security_gate",
                "latency_ms": 0, "session_id": req.session_id,
            })}
        return EventSourceResponse(blocked_generator())

    system_prompt = _get_agent_system_prompt(active_agent)

    memories = await retrieve(req.message)
    memory_ctx = "\n".join(m["content"] for m in memories) if memories else ""

    messages = [{"role": "system", "content": system_prompt}]
    if memory_ctx:
        messages.append({"role": "system", "content": f"Relevant context from memory:\n{memory_ctx}"})

    recent = await get_recent_messages(conv_id, limit=10)
    messages.extend(recent)
    messages.append({"role": "user", "content": req.message})

    async def event_generator():
        full_response: list[str] = []
        t0 = time.monotonic()
        try:
            async for token in stream_tokens(messages, use_deep=use_deep):
                full_response.append(token)
                # Use json.dumps to safely encode any token content
                yield {"data": json.dumps({"token": token})}

            latency = int((time.monotonic() - t0) * 1000)
            yield {
                "data": json.dumps({
                    "done": True,
                    "agent": active_agent,
                    "latency_ms": latency,
                    "session_id": req.session_id,
                })
            }

            from memory.store import save_message
            asyncio.create_task(save_message(conv_id, "user", req.message))
            asyncio.create_task(save_message(
                conv_id, "assistant", "".join(full_response),
                model_used="qwen-deep" if use_deep else "llama-fast",
                latency_ms=latency,
            ))

        except Exception as e:
            yield {"data": json.dumps({"error": f"Stream interrupted: {str(e)[:100]}"})}

    return EventSourceResponse(event_generator())


def _get_agent_system_prompt(agent: str) -> str:
    """Return the correct system prompt for the classified agent type."""
    from agents.conversational import IRA_SYSTEM
    from agents.researcher import _SYSTEM as RESEARCHER_SYSTEM
    from agents.security import _SYSTEM as SECURITY_SYSTEM
    from agents.executor import _SYSTEM as EXECUTOR_SYSTEM
    from agents.creator import _SYSTEM as CREATOR_SYSTEM
    from agents.website import _SYSTEM as WEBSITE_SYSTEM

    return {
        "conversational": IRA_SYSTEM,
        "researcher":     RESEARCHER_SYSTEM,
        "security":       SECURITY_SYSTEM,
        "executor":       EXECUTOR_SYSTEM,
        "creator":        CREATOR_SYSTEM,
        "website":        WEBSITE_SYSTEM,
    }.get(agent, IRA_SYSTEM)


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
