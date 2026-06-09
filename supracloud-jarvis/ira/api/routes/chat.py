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
from pydantic import BaseModel, ConfigDict, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from agents.graph import run_graph
from memory.store import ensure_conversation, get_recent_messages, retrieve
from owner_profile import get_profile_summary
from utils.llm import stream_tokens, should_use_deep, should_use_reasoning
from utils.redis_client import cache_get, cache_set, get_redis
from config import get_settings

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Engine selection (cutover — Phase 7.2) ─────────────────────────────────────
# IRA_USE_HERMES routes chat — and voice, which calls /chat/stream over HTTP — through
# the Hermes bridge skills instead of the legacy LangGraph agents. DEFAULT OFF: when off,
# behaviour is byte-identical to before. Read once at startup. The legacy path
# (agents/graph.py, supervisor.py, state.py) stays in place as the instant rollback.
_USE_HERMES = os.getenv("IRA_USE_HERMES", "false").strip().lower() in ("1", "true", "yes", "on")

# Classifier outputs that have a matching ira/skills/<name>/ persona (others → conversational).
_VALID_SKILLS = frozenset({
    "conversational", "researcher", "security", "executor",
    "creator", "website", "tutor", "career", "digital",
})


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
    engineer_mode: bool = False    # Claude-style 4-step engineering workflow (analysis→plan→diffs→verify)
    think_mode: bool = False       # Show step-by-step reasoning in collapsible panel before answer
    deep_search: bool = False      # Multi-step iterative web search (3 rounds) like Grok DeepSearch


class ChatResponse(BaseModel):
    # `model_used` collides with pydantic's protected "model_" namespace; opting out
    # of the namespace check silences the UserWarning without renaming the field.
    model_config = ConfigDict(protected_namespaces=())

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

_EXPERT_RATE_LIMIT = 20    # max Expert Mode calls per user per hour (personal AI — raised from 3)
_EXPERT_RATE_WINDOW = 3600  # sliding window in seconds


async def _check_expert_rate_limit(username: str) -> tuple[bool, int]:
    """
    Increment the per-user Expert Mode counter and check against the limit.
    Returns (allowed, calls_remaining). Fails open if Redis is unavailable.

    Fix #46: INCR and EXPIRE are sent in a single pipeline so the TTL is
    always set, even if two concurrent first-calls race or the process
    crashes between the two commands. Without the pipeline the key could
    become immortal, permanently locking a user after _EXPERT_RATE_LIMIT sessions.
    """
    key = f"expert_rate:{username}"
    try:
        pipe = get_redis().pipeline(transaction=False)
        pipe.incr(key)
        pipe.expire(key, _EXPERT_RATE_WINDOW)
        count, _ = await pipe.execute()
        remaining = max(0, _EXPERT_RATE_LIMIT - count)
        return count <= _EXPERT_RATE_LIMIT, remaining
    except Exception:
        return True, _EXPERT_RATE_LIMIT  # fail open if Redis is down


# ── Hermes engine path (Phase 7.2) ─────────────────────────────────────────────

async def _hermes_route(
    message: str,
    *,
    conv_id: str,
    owner: bool,
    user: str,
    mode: str = "assistant",
    is_voice: bool = False,
) -> tuple[str, str]:
    """New engine path: router owner-gate → classify → skill via the Hermes bridge.

    Returns (response_text, agent_name). All real tools/DB stay in IRA; only the
    reasoning runs on the gateway. enforce_owner_gate stays fail-closed. The bridge
    call is synchronous, so it runs in a worker thread to keep the event loop free.
    """
    from router import enforce_owner_gate

    refusal = enforce_owner_gate(message, owner)
    if refusal:
        return refusal, "security_gate"

    # Reuse the existing classifier (read-only) to pick the skill; ira/skills/<name>/
    # mirrors the classifier's agent names. Fall back to conversational if unmatched.
    from agents.graph import make_initial_state
    from agents.supervisor import classify
    from skills._common import run_skill

    temp_state = make_initial_state(
        session_id="hermes-route", conversation_id=conv_id, user_query=message,
        user_id=user, is_owner=owner, mode=mode, is_voice=is_voice,
    )
    classified = await classify(temp_state)
    skill = classified.get("active_agent", "conversational")
    if skill not in _VALID_SKILLS:
        skill = "conversational"

    # Memory is owned by Hermes in this path (project rule 5): the gateway loads the
    # thread's own history via X-Hermes-Session-Id and the user's long-term memory via
    # X-Hermes-Session-Key. IRA's own pgvector retrieve() is intentionally NOT read here
    # so memory has a single owner (no dual read).
    #   session_id = conv_id -> thread continuity (per conversation)
    #   user_key   = user    -> stable per-user memory scope (same id the owner gate uses)
    # The owner profile (who-I-am / goals / projects / prefs) is IRA-owned business data,
    # so it IS injected every turn as context (distinct from Hermes recall).
    profile_summary = await get_profile_summary()
    blocks = [profile_summary] if profile_summary else None
    text = await asyncio.to_thread(
        run_skill, skill, message, context_blocks=blocks, session_id=conv_id, user_key=user,
    )
    return text, skill


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

    if _USE_HERMES:                                  # NEW engine path (default OFF)
        t0 = time.monotonic()
        text, agent = await _hermes_route(
            req.message, conv_id=conv_id, owner=owner, user=_user,
            mode=req.mode, is_voice=req.is_voice,
        )
        return ChatResponse(
            response=text,
            session_id=req.session_id,
            conversation_id=conv_id,
            agent_used=agent,
            model_used="hermes",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    state = await run_graph(
        session_id=req.session_id,
        conversation_id=conv_id,
        user_query=req.message,
        is_owner=owner,
        mode=req.mode,
        is_voice=req.is_voice,
        user_id=_user,
    )

    result = ChatResponse(
        response=state["final_response"],
        session_id=req.session_id,
        conversation_id=conv_id,
        agent_used=state.get("active_agent", "conversational"),
        model_used=state.get("model_used", "qwen3-fast"),  # Fix L12: was "llama-fast" fallback default
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

    if _USE_HERMES:                                  # NEW engine path (default OFF) — also serves voice (HTTP → here)
        text, agent = await _hermes_route(
            req.message, conv_id=conv_id, owner=owner, user=_user,
            mode=req.mode, is_voice=req.is_voice,
        )

        async def _hermes_stream_gen():
            t0 = time.monotonic()
            for word in text.split(" "):
                yield {"data": json.dumps({"token": word + " "})}
                await asyncio.sleep(0.01)
            yield {"data": json.dumps({
                "done": True,
                "agent": agent,
                "latency_ms": int((time.monotonic() - t0) * 1000),
                "session_id": req.session_id,
            })}

        return EventSourceResponse(_hermes_stream_gen())

    from agents.state import IRAState
    from agents.supervisor import classify, is_restricted_domain
    from agents.graph import make_initial_state  # Fix P23: shared factory prevents drift

    # Fix P23: use shared factory so temp_state and run_graph() initial_state
    # can never have different required fields or wrong defaults.
    temp_state = make_initial_state(
        session_id=req.session_id,
        conversation_id=conv_id,
        user_query=req.message,
        user_id=_user,
        is_owner=owner,
        mode=req.mode,
        is_voice=req.is_voice,
    )
    classified = await classify(temp_state)
    active_agent = classified["active_agent"]
    use_deep = classified["use_deep_model"]
    # Reasoning tier: Think Mode + DeepSearch + explicit reasoning queries route here
    use_reasoning = should_use_reasoning(
        req.message,
        think_mode=req.think_mode,
        deep_search=req.deep_search,
    )

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
            user_id=_user,
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
        get_search_context, deep_search_context,
    )
    from agents.grok_personality import build_grok_system_prompt
    from agents.engineer_agent import build_engineer_prompt
    from agents.architect_agent import (
        is_architect_trigger, is_implement_trigger, is_apply_trigger,
        extract_feature_name, stream_architect_proposal, stream_auto_implement,
    )
    # Fix P24: feature routing moved to ordered handler registry in _dispatch.py
    from api.routes._dispatch import dispatch as _feature_dispatch
    from api.routes.video_gen import is_video_understand_request

    # ── Architect Agent: intercept before all other routing ───────────────────
    if is_architect_trigger(req.message):
        memories_raw = await retrieve(req.message, user_id=_user)
        memory_ctx = "\n".join(m["content"] for m in memories_raw) if memories_raw else ""

        async def architect_proposal_stream():
            async for event in stream_architect_proposal(req.message, memory_context=memory_ctx):
                # Re-map architect events to the standard SSE token format for the frontend
                if event.get("architect_start"):
                    yield {"data": json.dumps({"token": event["message"] + "\n\n"})}
                elif event.get("architect_agent") and event.get("chunk"):
                    yield {"data": json.dumps({"token": event["chunk"]})}
                elif event.get("architect_done"):
                    yield {"data": json.dumps({
                        "done": True,
                        "agent": "architect",
                        "latency_ms": event.get("latency_ms", 0),
                        "session_id": req.session_id,
                        "is_architect": True,
                    })}
        return EventSourceResponse(architect_proposal_stream())

    if is_implement_trigger(req.message):
        feature = extract_feature_name(req.message)
        from api.routes.architect import _get_state as _arch_get, _set_state as _arch_set
        cached = await _arch_get(_user)
        proposal_ctx = cached.get("proposal") or ""

        async def architect_impl_stream():
            async for event in stream_auto_implement(feature, proposal_context=proposal_ctx):
                if event.get("implement_start"):
                    yield {"data": json.dumps({"token": event["message"] + "\n\n"})}
                elif event.get("implement_chunk"):
                    yield {"data": json.dumps({"token": event["implement_chunk"]})}
                elif event.get("implement_done"):
                    st = await _arch_get(_user)
                    st["implementation"] = event.get("implementation", "")
                    st["feature_name"] = feature
                    st["pending_apply"] = True
                    await _arch_set(_user, st)
                    yield {"data": json.dumps({
                        "done": True,
                        "agent": "architect",
                        "latency_ms": 0,
                        "session_id": req.session_id,
                        "is_architect": True,
                        "pending_apply": True,
                    })}
        return EventSourceResponse(architect_impl_stream())

    if is_apply_trigger(req.message):
        from api.routes.architect import _get_state as _arch_get, _set_state as _arch_set
        from utils.auto_implement import apply_implementation

        async def apply_stream():
            yield {"data": json.dumps({"token": "⚙️ Applying implementation — running `git apply`…\n\n"})}
            st = await _arch_get(_user)
            impl = st.get("implementation")
            if not impl:
                yield {"data": json.dumps({"token": "❌ No pending implementation. Run `architect implement [feature]` first.\n"})}
            else:
                result = await apply_implementation(impl)
                if result.success:
                    st["pending_apply"] = False
                    st["implementation"] = None
                    await _arch_set(_user, st)
                msg = result.message + ("\n\n" + result.error if result.error else "")
                yield {"data": json.dumps({"token": msg})}
            yield {"data": json.dumps({
                "done": True, "agent": "architect", "latency_ms": 0,
                "session_id": req.session_id, "is_architect": True,
            })}
        return EventSourceResponse(apply_stream())

    _THINK_ADDON = (
        "\n\nTHINK MODE ACTIVE: Before answering, reason through the problem thoroughly "
        "inside <think>...</think> tags. Be explicit and detailed in your reasoning. "
        "After </think>, give your final clean answer without repeating the reasoning."
    )

    # ── Search context (DeepSearch or standard) ───────────────────────────────
    used_live_x = False
    deep_search_rounds = 0

    async def _get_ctx():
        if req.deep_search:
            return await deep_search_context(req.message)
        elif not req.is_voice:
            return await get_search_context(req.message)
        return "", {}

    # ── Mode selection: Engineer > Grok > Normal ───────────────────────────────
    if req.engineer_mode:
        memories_raw = await retrieve(req.message, user_id=_user)
        search_ctx = ""
        system_prompt = build_engineer_prompt()
        use_deep = True

    elif req.grok_mode:
        memories_task = asyncio.create_task(retrieve(req.message, user_id=_user))
        search_task = asyncio.create_task(_get_ctx())
        memories_raw, (search_ctx, search_meta) = await asyncio.gather(memories_task, search_task)
        used_live_x = search_meta.get("used_live_x", False)
        deep_search_rounds = search_meta.get("deep_search_rounds", 0)
        system_prompt = build_grok_system_prompt(context=search_ctx)

    else:
        memories_raw = await retrieve(req.message, user_id=_user)
        search_ctx, search_meta = await _get_ctx()
        used_live_x = search_meta.get("used_live_x", False)
        deep_search_rounds = search_meta.get("deep_search_rounds", 0)
        system_prompt = _get_agent_system_prompt(active_agent, is_voice=req.is_voice)

    # Append Think Mode instructions to whichever system prompt was selected
    if req.think_mode and not req.is_voice:
        system_prompt += _THINK_ADDON

    memory_ctx = "\n".join(m["content"] for m in memories_raw) if memories_raw else ""

    # Fix P24: feature handler registry replaces the 8-block if-ladder.
    # Handlers are in _dispatch.py; first match wins; None means fall through.
    _dispatched = await _feature_dispatch(req, _user)
    if _dispatched is not None:
        return _dispatched

    messages = [{"role": "system", "content": system_prompt}]
    # v1 1.4: inject the owner profile every turn so the brain stays grounded.
    profile_summary = await get_profile_summary()
    if profile_summary:
        messages.append({"role": "system", "content": profile_summary})
    if memory_ctx:
        messages.append({"role": "system", "content": f"Relevant context from memory:\n{memory_ctx}"})
    if search_ctx:
        messages.append({"role": "system", "content": f"Live information:\n{search_ctx}"})

    recent = await get_recent_messages(conv_id, limit=10)
    messages.extend(recent)
    messages.append({"role": "user", "content": req.message})

    async def event_generator():
        full_response: list[str] = []
        full_thinking: list[str] = []
        t0 = time.monotonic()
        try:
            if req.think_mode:
                # ── Think Mode: parse <think>…</think> tags from stream ────────
                buf = ""
                in_think = False
                OPEN, CLOSE = "<think>", "</think>"

                async for raw_tok in stream_tokens(messages, use_deep=use_deep, use_reasoning=use_reasoning):
                    buf += raw_tok
                    # Keep draining buf until we can't make progress
                    while True:
                        if in_think:
                            ci = buf.find(CLOSE)
                            if ci >= 0:
                                chunk = buf[:ci]
                                if chunk:
                                    full_thinking.append(chunk)
                                    yield {"data": json.dumps({"thinking_token": chunk})}
                                yield {"data": json.dumps({"thinking_done": True})}
                                buf = buf[ci + len(CLOSE):]
                                in_think = False
                            else:
                                safe = max(0, len(buf) - len(CLOSE))
                                if safe:
                                    chunk = buf[:safe]
                                    full_thinking.append(chunk)
                                    yield {"data": json.dumps({"thinking_token": chunk})}
                                    buf = buf[safe:]
                                break
                        else:
                            oi = buf.find(OPEN)
                            if oi >= 0:
                                pre = buf[:oi]
                                if pre:
                                    full_response.append(pre)
                                    yield {"data": json.dumps({"token": pre})}
                                yield {"data": json.dumps({"thinking_start": True})}
                                buf = buf[oi + len(OPEN):]
                                in_think = True
                            else:
                                safe = max(0, len(buf) - len(OPEN))
                                if safe:
                                    chunk = buf[:safe]
                                    full_response.append(chunk)
                                    yield {"data": json.dumps({"token": chunk})}
                                    buf = buf[safe:]
                                break

                # Flush remaining buffer
                if buf:
                    if in_think:
                        full_thinking.append(buf)
                        yield {"data": json.dumps({"thinking_token": buf})}
                        yield {"data": json.dumps({"thinking_done": True})}
                    else:
                        full_response.append(buf)
                        yield {"data": json.dumps({"token": buf})}
            else:
                # ── Normal streaming ───────────────────────────────────────────
                async for token in stream_tokens(messages, use_deep=use_deep, use_reasoning=use_reasoning):
                    full_response.append(token)
                    yield {"data": json.dumps({"token": token})}

            latency = int((time.monotonic() - t0) * 1000)
            yield {
                "data": json.dumps({
                    "done": True,
                    "agent": "engineer" if req.engineer_mode else active_agent,
                    "latency_ms": latency,
                    "session_id": req.session_id,
                    "used_live_x": used_live_x,
                    "is_engineer": req.engineer_mode,
                    "is_think": req.think_mode,
                    "deep_search_rounds": deep_search_rounds,
                })
            }

            from memory.store import save_message
            import logging as _log
            _tu = asyncio.create_task(save_message(conv_id, "user", req.message, user_id=_user))
            _tu.add_done_callback(lambda t: t.exception() and _log.getLogger("ira.chat").warning(f"save_message failed: {t.exception()}"))
            _ta = asyncio.create_task(save_message(
                conv_id, "assistant", "".join(full_response),
                model_used="qwen3-reasoning" if use_reasoning else ("qwen3-deep" if use_deep else "qwen3-fast"),
                latency_ms=latency,
                user_id=_user,
            ))
            _ta.add_done_callback(lambda t: t.exception() and _log.getLogger("ira.chat").warning(f"save_message failed: {t.exception()}"))

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

    Rate limit: max _EXPERT_RATE_LIMIT sessions per user per hour (tracked in Redis).  # Fix P18
    Events: {"agent":"researcher","label":"Researcher","emoji":"🔬","chunk":"...","done":false}
            {"agent":"supervisor","done":true,"latency_ms":N}
    """
    # Fix P18: rate limit is _EXPERT_RATE_LIMIT (currently 20/hour), not the old 3/hour
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

    if _USE_HERMES:                                  # NEW engine path (default OFF): deliberation via subagents
        from router import enforce_owner_gate
        from subagents import deliberate

        refusal = enforce_owner_gate(req.message, owner)
        owner_name = get_settings().owner_name
        memories_raw = await retrieve(req.message, user_id=_user)
        memory_ctx = "\n".join(m["content"] for m in memories_raw) if memories_raw else ""

        async def _hermes_expert_gen():
            t0 = time.monotonic()
            if refusal:
                text = refusal
            else:
                text = await asyncio.to_thread(
                    deliberate, req.message,
                    owner_name=owner_name, memory_context=memory_ctx,
                )
            for word in text.split(" "):
                yield {"data": json.dumps({"agent": "supervisor", "chunk": word + " ", "done": False})}
                await asyncio.sleep(0.005)
            yield {"data": json.dumps({
                "agent": "supervisor", "done": True,
                "latency_ms": int((time.monotonic() - t0) * 1000),
            })}

        return EventSourceResponse(
            _hermes_expert_gen(),
            headers={"X-Expert-Remaining": str(remaining)},
        )

    # Gather memory + live search in parallel for Expert Mode
    from utils.search_tools import get_search_context as _get_search_ctx
    memories_raw, (search_ctx, search_meta) = await asyncio.gather(
        retrieve(req.message, user_id=_user),
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
    vision_url = get_settings().vllm_vision_url
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
            import logging as _log
            final_text = "".join(full_response)
            # Fix P3: scope vision saves to the authenticated user (not "system")
            _tu = asyncio.create_task(save_message(conv_id, "user", req.message, user_id=_user))
            _tu.add_done_callback(lambda t: t.exception() and _log.getLogger("ira.chat").warning(f"save_message failed: {t.exception()}"))
            _ta = asyncio.create_task(save_message(
                conv_id, "assistant", final_text,
                model_used="vision" if vision_url else "qwen3-fast",
                latency_ms=latency,
                user_id=_user,
            ))
            _ta.add_done_callback(lambda t: t.exception() and _log.getLogger("ira.chat").warning(f"save_message failed: {t.exception()}"))
        except Exception as e:
            yield {"data": json.dumps({"error": f"Vision error: {str(e)[:100]}"})}

    return EventSourceResponse(vision_generator())


# ── Document analysis endpoint (PDF / DOCX / TXT) ────────────────────────────

def _extract_document_text(content: bytes, filename: str, content_type: str) -> str:
    """Extract plain text from PDF, DOCX, or TXT file bytes."""
    fname = (filename or "").lower()
    ctype = (content_type or "").lower()

    # PDF
    if fname.endswith(".pdf") or "pdf" in ctype:
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(content))
            pages = [page.extract_text() or "" for page in reader.pages]
            return "\n\n".join(p for p in pages if p.strip())
        except ImportError:
            return "[pypdf not installed — cannot extract PDF text]"
        except Exception as e:
            return f"[PDF extraction error: {e}]"

    # DOCX
    if fname.endswith(".docx") or "wordprocessingml" in ctype or "officedocument" in ctype:
        try:
            import io
            from docx import Document
            doc = Document(io.BytesIO(content))
            return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
        except ImportError:
            return "[python-docx not installed — cannot extract DOCX text]"
        except Exception as e:
            return f"[DOCX extraction error: {e}]"

    # Plain text / markdown / CSV / anything else
    try:
        return content.decode("utf-8", errors="replace")
    except Exception:
        return "[Could not decode document as text]"


@router.post("/document", include_in_schema=False)
async def chat_document(
    message: str = None,
    session_id: str = None,
    _user: str = Depends(require_auth),
):
    """Hidden stub — document upload is handled by /document/upload."""
    raise HTTPException(status_code=501, detail="Use /api/v1/chat/document/upload for document analysis.")


# Register the real multipart handler manually to avoid FastAPI's form conflicts
from fastapi import Form, File, UploadFile


@router.post("/document/upload")
async def chat_document_upload(
    message: str = Form(...),
    session_id: str = Form(default=None),
    file: UploadFile = File(...),
    _user: str = Depends(require_auth),
):
    """
    Analyse an uploaded document (PDF, DOCX, TXT) alongside a user message.

    Extracts text from the file, injects it as context, and streams the LLM
    response token-by-token via SSE.  Capped at 12 000 chars to fit context.

    Returns SSE stream: {"token": "..."} … {"done": true, "agent": "document"}
    """
    session_id = session_id or str(uuid.uuid4())
    conv_id = await ensure_conversation(session_id)

    from utils.file_utils import read_with_size_cap
    raw = await read_with_size_cap(file, max_bytes=50 * 1024 * 1024)
    doc_text = _extract_document_text(raw, file.filename or "", file.content_type or "")

    # Truncate to fit context window
    LIMIT = 12_000
    if len(doc_text) > LIMIT:
        doc_text = doc_text[:LIMIT] + f"\n\n[… document truncated at {LIMIT} chars …]"

    system = _get_agent_system_prompt("conversational")
    doc_system = (
        f"The user has uploaded a document: **{file.filename}**\n\n"
        f"Document contents:\n\n{doc_text}\n\n"
        "Answer the user's question using the document as your primary source. "
        "If the document does not contain the answer, say so clearly."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "system", "content": doc_system},
        {"role": "user", "content": message},
    ]

    async def doc_generator():
        full_response: list[str] = []
        t0 = time.monotonic()
        try:
            async for token in stream_tokens(messages, use_deep=True):
                full_response.append(token)
                yield {"data": json.dumps({"token": token})}

            latency = int((time.monotonic() - t0) * 1000)
            yield {"data": json.dumps({
                "done": True,
                "agent": "document",
                "latency_ms": latency,
                "session_id": session_id,
                "filename": file.filename,
            })}

            from memory.store import save_message
            import logging as _log
            # Fix P3: scope document saves to the authenticated user (not "system")
            _tu = asyncio.create_task(save_message(conv_id, "user", f"[Document: {file.filename}] {message}", user_id=_user))
            _tu.add_done_callback(lambda t: t.exception() and _log.getLogger("ira.chat").warning(f"save_message failed: {t.exception()}"))
            _ta = asyncio.create_task(save_message(
                conv_id, "assistant", "".join(full_response),
                model_used="qwen3-deep",
                latency_ms=latency,
                user_id=_user,
            ))
            _ta.add_done_callback(lambda t: t.exception() and _log.getLogger("ira.chat").warning(f"save_message failed: {t.exception()}"))
        except Exception as e:
            yield {"data": json.dumps({"error": f"Document analysis error: {str(e)[:100]}"})}

    return EventSourceResponse(doc_generator())


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
