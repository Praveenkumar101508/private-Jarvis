"""
Chat endpoints — the core IRA interface.

POST /chat          → standard JSON response
POST /chat/stream   → Server-Sent Events (token-by-token)
GET  /chat/history  → conversation history

Biometric gate: every request carries an `is_owner` flag. The LangGraph
biometric_gate node uses this to allow or block restricted domain access.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
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
    is_voice_owner: bool = False   # Set True by voice agent after biometric verification
    is_voice: bool = False         # Set True by voice pipeline for concise reply routing
    mode: str = "assistant"        # "assistant" | "tutor"
    image_b64: str | None = Field(None, description="Base64-encoded image for vision queries")
    mime_type: str = Field("image/jpeg")
    grok_mode: bool = False        # Use Grok personality + auto search + image gen tools


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


def _is_voice_service(username: str) -> bool:
    """Return True only if the request comes from the trusted voice service."""
    cfg = get_settings()
    return username == cfg.ira_voice_service_username


def _stable_hash(text: str) -> str:
    """SHA-256-based stable hash for cache keys (not Python's randomised hash)."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ── Expert Mode rate limiting ─────────────────────────────────────────────────

_EXPERT_RATE_LIMIT = 3     # max Expert Mode calls per user per hour
_EXPERT_RATE_WINDOW = 3600  # sliding window in seconds


async def _check_expert_rate_limit(username: str) -> tuple[bool, int]:
    """
    Increment the per-user Expert Mode counter and check against the limit.
    Returns (allowed, calls_remaining). Fails open if Redis is unavailable.
    """
    key = f"expert_rate:{username}"
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        count = await redis.incr(key)
        if count == 1:
            # First call in this window — set the TTL
            await redis.expire(key, _EXPERT_RATE_WINDOW)
        remaining = max(0, _EXPERT_RATE_LIMIT - count)
        return count <= _EXPERT_RATE_LIMIT, remaining
    except Exception:
        return True, _EXPERT_RATE_LIMIT  # fail open if Redis is down


# ── Standard (non-streaming) chat ─────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    _user: str = Depends(require_auth),
):
    cache_key = f"chat:{_user}:{req.session_id}:{_stable_hash(req.message)}"
    cached = await cache_get(cache_key)
    if cached:
        return ChatResponse(**cached)

    conv_id = await ensure_conversation(req.session_id)
    # Only trust is_voice_owner when the request genuinely originates from the voice service
    owner = _is_owner(_user) or (_is_voice_service(_user) and req.is_voice_owner)

    state = await run_graph(
        session_id=req.session_id,
        conversation_id=conv_id,
        user_query=req.message,
        is_owner=owner,
        mode=req.mode,
        is_voice=req.is_voice,
    )

    result = ChatResponse(
        response=state["final_response"],
        session_id=req.session_id,
        conversation_id=conv_id,
        agent_used=state.get("active_agent", "conversational"),
        model_used=state.get("model_used", "llama-fast"),
        latency_ms=state.get("latency_ms", 0),
    )

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
    Token-by-token streaming via SSE, routed through supervisor + biometric gate.
    Client receives: data: {"token": "..."} events, then data: {"done": true, ...}.
    """
    conv_id = await ensure_conversation(req.session_id)
    # Only trust is_voice_owner when the request genuinely originates from the voice service
    owner = _is_owner(_user) or (_is_voice_service(_user) and req.is_voice_owner)

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
        "mode": req.mode,
        "memory_context": "",
        "final_response": "",
        "stream_tokens": [],
        "latency_ms": 0,
        "model_used": "llama-fast",
        "is_owner": owner,
        "clearance_level": "admin" if owner else "public",
        "is_voice": req.is_voice,
        "error": None,
    }
    classified = await classify(temp_state)
    active_agent = classified["active_agent"]
    use_deep = classified["use_deep_model"]

    # ── Biometric gate: block restricted domains for non-owners ───────────────
    cfg = get_settings()
    if not cfg.dev_mode and is_restricted_domain(req.message) and not owner:
        async def blocked_generator():
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

    # Career, digital, and tutor agents need full graph execution (tool calls).
    # Run the graph first, then word-stream the pre-computed response.
    if active_agent in ("career", "digital"):
        full_state = await run_graph(
            session_id=req.session_id,
            conversation_id=conv_id,
            user_query=req.message,
            is_owner=owner,
            mode=req.mode,
            is_voice=req.is_voice,
        )
        final_text = full_state.get("final_response", "I encountered an issue processing that request.")

        async def tool_result_streamer():
            t0 = time.monotonic()
            for word in final_text.split(" "):
                yield {"data": json.dumps({"token": word + " "})}
                await asyncio.sleep(0.018)
            latency = int((time.monotonic() - t0) * 1000)
            yield {"data": json.dumps({
                "done": True,
                "agent": full_state.get("active_agent", active_agent),
                "latency_ms": latency,
                "session_id": req.session_id,
            })}

        return EventSourceResponse(tool_result_streamer())

    from utils.search_tools import (
        get_search_context, is_image_gen_request, is_image_edit_request
    )
    from agents.grok_personality import build_grok_system_prompt

    # ── Grok mode: override personality and auto-enable search ────────────────
    used_live_x = False
    if req.grok_mode:
        memories_task = asyncio.create_task(retrieve(req.message))
        search_task = asyncio.create_task(get_search_context(req.message))
        memories_raw, (search_ctx, search_meta) = await asyncio.gather(memories_task, search_task)
        used_live_x = search_meta.get("used_live_x", False)
        system_prompt = build_grok_system_prompt(context=search_ctx)
    else:
        memories_raw = await retrieve(req.message)
        if not req.is_voice:
            search_ctx, search_meta = await get_search_context(req.message)
            used_live_x = search_meta.get("used_live_x", False)
        else:
            search_ctx = ""
        system_prompt = _get_agent_system_prompt(active_agent, is_voice=req.is_voice)

    memory_ctx = "\n".join(m["content"] for m in memories_raw) if memories_raw else ""

    # ── Image generation path ─────────────────────────────────────────────────
    if is_image_gen_request(req.message) and not req.is_voice:
        async def image_gen_stream():
            yield {"data": json.dumps({"token": "Generating your image… "})}
            try:
                from api.routes.image_gen import GenerateRequest, _IMAGE_GEN_URL, _REPLICATE_TOKEN
                if _IMAGE_GEN_URL or _REPLICATE_TOKEN:
                    from api.routes.image_gen import _generate_sd_webui, _generate_replicate
                    gen_req = GenerateRequest(
                        prompt=req.message,
                        width=1024, height=1024, steps=20,
                    )
                    image_b64 = (
                        await _generate_sd_webui(gen_req) if _IMAGE_GEN_URL
                        else await _generate_replicate(gen_req)
                    )
                    yield {"data": json.dumps({
                        "image_generated": True,
                        "image_b64": image_b64,
                        "mime_type": "image/png",
                        "prompt": req.message,
                    })}
                    final_text = f"Here is your generated image based on: *{req.message}*"
                else:
                    final_text = (
                        "Image generation is not configured yet.\n\n"
                        "To enable it, add one of these to your `.env`:\n"
                        "- `IMAGE_GEN_URL=http://your-sd-webui:7860` (Stable Diffusion)\n"
                        "- `REPLICATE_API_TOKEN=r8_...` (Flux via Replicate)\n\n"
                        "Once configured, just ask me to *generate* or *draw* something and I will."
                    )
            except Exception as e:
                final_text = f"Image generation failed: {e}"

            for word in final_text.split(" "):
                yield {"data": json.dumps({"token": word + " "})}
                await asyncio.sleep(0.01)

            yield {"data": json.dumps({
                "done": True, "agent": "image_gen",
                "latency_ms": 0, "session_id": req.session_id,
            })}

        return EventSourceResponse(image_gen_stream())

    # ── Image edit path (image attached + edit request) ───────────────────────
    if req.image_b64 and is_image_edit_request(req.message):
        async def image_edit_stream():
            yield {"data": json.dumps({"token": "Editing your image… "})}
            try:
                from api.routes.image_gen import EditRequest, _IMAGE_GEN_URL, _REPLICATE_TOKEN
                if _IMAGE_GEN_URL or _REPLICATE_TOKEN:
                    from api.routes.image_gen import _edit_sd_webui, _edit_replicate
                    edit_req = EditRequest(image_b64=req.image_b64, instruction=req.message)
                    image_b64 = (
                        await _edit_sd_webui(edit_req) if _IMAGE_GEN_URL
                        else await _edit_replicate(edit_req)
                    )
                    yield {"data": json.dumps({
                        "image_generated": True,
                        "image_b64": image_b64,
                        "mime_type": "image/png",
                        "prompt": req.message,
                    })}
                    final_text = "Here is the edited image."
                else:
                    final_text = (
                        "Image editing requires IMAGE_GEN_URL or REPLICATE_API_TOKEN in .env."
                    )
            except Exception as e:
                final_text = f"Image editing failed: {e}"

            for word in final_text.split(" "):
                yield {"data": json.dumps({"token": word + " "})}
                await asyncio.sleep(0.01)

            yield {"data": json.dumps({
                "done": True, "agent": "image_edit",
                "latency_ms": 0, "session_id": req.session_id,
            })}

        return EventSourceResponse(image_edit_stream())

    messages = [{"role": "system", "content": system_prompt}]
    if memory_ctx:
        messages.append({"role": "system", "content": f"Relevant context from memory:\n{memory_ctx}"})
    if search_ctx:
        messages.append({"role": "system", "content": f"Live information:\n{search_ctx}"})

    recent = await get_recent_messages(conv_id, limit=10)
    messages.extend(recent)
    messages.append({"role": "user", "content": req.message})

    async def event_generator():
        full_response: list[str] = []
        t0 = time.monotonic()
        try:
            async for token in stream_tokens(messages, use_deep=use_deep):
                full_response.append(token)
                yield {"data": json.dumps({"token": token})}

            latency = int((time.monotonic() - t0) * 1000)
            yield {
                "data": json.dumps({
                    "done": True,
                    "agent": active_agent,
                    "latency_ms": latency,
                    "session_id": req.session_id,
                    "used_live_x": used_live_x,
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


@router.post("/expert")
async def chat_expert(
    req: ChatRequest,
    _user: str = Depends(require_auth),
):
    """
    Grok-style Expert Mode: 5 specialist agents run in true parallel, debate,
    and stream their individual thoughts + supervisor synthesis via SSE.

    Rate limit: max 3 sessions per user per hour (tracked in Redis).
    Events: {"agent":"researcher","label":"Researcher","emoji":"🔬","chunk":"...","done":false}
            {"agent":"supervisor","done":true,"latency_ms":N}
    """
    # Server-side rate limit: 3 Expert Mode sessions per hour per user
    allowed, remaining = await _check_expert_rate_limit(_user)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Expert Mode rate limit reached ({_EXPERT_RATE_LIMIT} sessions/hour). "
                "Please wait before starting another Expert Mode session."
            ),
            headers={"X-Expert-Remaining": "0", "Retry-After": "3600"},
        )

    from agents.expert_mode import stream_expert_mode
    from memory.store import retrieve

    owner = _is_owner(_user) or (_is_voice_service(_user) and req.is_voice_owner)

    # Gather memory + live search in parallel for Expert Mode
    from utils.search_tools import get_search_context as _get_search_ctx
    memories_raw, (search_ctx, search_meta) = await asyncio.gather(
        retrieve(req.message),
        _get_search_ctx(req.message),
    )
    expert_used_live_x = search_meta.get("used_live_x", False)
    memory_ctx = "\n".join(m["content"] for m in memories_raw) if memories_raw else ""
    if search_ctx:
        memory_ctx = f"{memory_ctx}\n\n{search_ctx}".strip()

    async def expert_generator():
        async for event in stream_expert_mode(
            query=req.message,
            memory_context=memory_ctx,
            is_owner=owner,
            image_b64=req.image_b64,
            mime_type=req.mime_type,
        ):
            # Inject used_live_x into the final supervisor done event
            if event.get("done") and event.get("agent") == "supervisor":
                event["used_live_x"] = expert_used_live_x
            yield {"data": json.dumps(event)}

    return EventSourceResponse(
        expert_generator(),
        headers={"X-Expert-Remaining": str(remaining)},
    )


# ── Vision endpoint ───────────────────────────────────────────────────────────

class VisionRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=8_000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    image_b64: str = Field(..., description="Base64-encoded image")
    mime_type: str = Field("image/jpeg")


@router.post("/vision")
async def chat_vision(
    req: VisionRequest,
    _user: str = Depends(require_auth),
):
    """
    Vision-capable streaming chat.  Accepts a base64-encoded image alongside
    a text prompt.  Uses VLLM_VISION_URL if configured; falls back to the
    fast text model with a graceful degradation note.
    """
    conv_id = await ensure_conversation(req.session_id)
    vision_url = os.getenv("VLLM_VISION_URL", "")
    data_url = f"data:{req.mime_type};base64,{req.image_b64}"

    if vision_url:
        user_content: list | str = [
            {"type": "text", "text": req.message},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    else:
        user_content = (
            f"{req.message}\n\n[Note: an image was attached but no vision model is configured. "
            "Set VLLM_VISION_URL in .env to enable image analysis.]"
        )

    messages = [
        {"role": "system", "content": _get_agent_system_prompt("conversational")},
        {"role": "user", "content": user_content},
    ]

    async def vision_generator():
        t0 = time.monotonic()
        full_response: list[str] = []
        try:
            if vision_url:
                cfg = get_settings()
                from openai import AsyncOpenAI
                vision_client = AsyncOpenAI(api_key=cfg.vllm_api_key, base_url=vision_url)
                stream = await vision_client.chat.completions.create(
                    model="vision",
                    messages=messages,  # type: ignore[arg-type]
                    stream=True,
                    max_tokens=2048,
                    temperature=0.3,
                )
                async for chunk in stream:
                    token = chunk.choices[0].delta.content or ""
                    if token:
                        full_response.append(token)
                        yield {"data": json.dumps({"token": token})}
            else:
                async for token in stream_tokens(messages, use_deep=False):
                    full_response.append(token)
                    yield {"data": json.dumps({"token": token})}

            latency = int((time.monotonic() - t0) * 1000)
            yield {"data": json.dumps({"done": True, "agent": "vision", "latency_ms": latency})}

            from memory.store import save_message
            final_text = "".join(full_response)
            asyncio.create_task(save_message(conv_id, "user", req.message))
            asyncio.create_task(save_message(
                conv_id, "assistant", final_text,
                model_used="vision" if vision_url else "llama-fast",
                latency_ms=latency,
            ))
        except Exception as e:
            yield {"data": json.dumps({"error": f"Vision error: {str(e)[:100]}"})}

    return EventSourceResponse(vision_generator())


def _get_agent_system_prompt(agent: str, is_voice: bool = False) -> str:
    """
    Return the correct system prompt for the classified agent type.
    Voice requests get a concise-reply suffix appended.
    """
    from agents.conversational import IRA_SYSTEM
    from agents.researcher import _SYSTEM as RESEARCHER_SYSTEM
    from agents.security import _SYSTEM as SECURITY_SYSTEM
    from agents.executor import _SYSTEM as EXECUTOR_SYSTEM
    from agents.creator import _SYSTEM as CREATOR_SYSTEM
    from agents.website import _SYSTEM as WEBSITE_SYSTEM
    from agents.tutor import _SYSTEM as TUTOR_SYSTEM
    from agents.career import _SYSTEM as CAREER_SYSTEM
    from agents.digital import _SYSTEM as DIGITAL_SYSTEM

    prompt = {
        "conversational": IRA_SYSTEM,
        "researcher":     RESEARCHER_SYSTEM,
        "security":       SECURITY_SYSTEM,
        "executor":       EXECUTOR_SYSTEM,
        "creator":        CREATOR_SYSTEM,
        "website":        WEBSITE_SYSTEM,
        "tutor":          TUTOR_SYSTEM,
        "career":         CAREER_SYSTEM,
        "digital":        DIGITAL_SYSTEM,
    }.get(agent, IRA_SYSTEM)

    if is_voice:
        # Voice responses must be short — TTS reads every word aloud
        voice_suffix = (
            "\n\nVOICE MODE: You are speaking aloud. "
            "Keep every response to 1-2 short sentences maximum. "
            "Be warm, direct, and conversational. "
            "Never use bullet points, headers, or markdown — speak naturally."
        )
        prompt = prompt + voice_suffix

    return prompt


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
