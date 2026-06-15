"""
IRA Architect Agent API — Self-Evolving Engineering Team endpoints.

POST /architect/propose    → 5-agent debate + feature proposal (SSE)
POST /architect/implement  → Auto-generate code for an approved feature (SSE)
POST /architect/apply      → Apply generated diffs + commit + restart services
GET  /architect/status     → Current state (pending proposal / implementation)
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from config import get_settings
from memory.store import retrieve


def _require_admin(username: str = Depends(require_auth)) -> str:
    """Restrict access to the configured admin user."""
    if username != get_settings().ira_admin_username:
        raise HTTPException(status_code=403, detail="Admin access required for architect apply")
    return username

router = APIRouter(prefix="/architect", tags=["architect"])

_STATE_TTL = 86400  # 24 h — state is per-user, expires after a day of inactivity

_DEFAULT_STATE: dict = {
    "proposal": None,
    "implementation": None,
    "feature_name": None,
    "pending_apply": False,
}


async def _get_state(user_id: str) -> dict:
    """Load architect state for this user from Redis (falls back to defaults)."""
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        raw = await redis.get(f"architect:state:{user_id}")
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return dict(_DEFAULT_STATE)


async def _set_state(user_id: str, state: dict) -> None:
    """Persist architect state for this user in Redis with 24 h TTL."""
    try:
        from utils.redis_client import get_redis
        redis = get_redis()
        await redis.setex(f"architect:state:{user_id}", _STATE_TTL, json.dumps(state))
    except Exception:
        pass  # Redis failure must not crash the apply flow


# ── Request models ────────────────────────────────────────────────────────────

class ProposeRequest(BaseModel):
    query: str = Field(default="Propose new features for IRA", max_length=2000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ImplementRequest(BaseModel):
    feature_name: str = Field(..., max_length=200)
    proposal_context: str = Field(default="", max_length=8000)
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class ApplyRequest(BaseModel):
    dry_run: bool = False


# ── Proposal endpoint ─────────────────────────────────────────────────────────

@router.post("/propose")
async def architect_propose(
    req: ProposeRequest,
    _user: str = Depends(require_auth),
):
    """
    Stream the 5-agent architectural debate + feature proposal via SSE.

    Events:
      {"architect_start": true, "message": "..."}
      {"architect_agent": "researcher", "chunk": "...", "done": false}
      {"architect_agent": "supervisor",  "chunk": "...", "done": true}
      {"architect_done": true, "proposal": "...", "latency_ms": N}
    """
    from agents.architect_agent import stream_architect_proposal

    # Retrieve memory context for personalisation
    try:
        memories_raw = await retrieve(req.query)
        memory_ctx = "\n".join(m["content"] for m in memories_raw) if memories_raw else ""
    except Exception:
        memory_ctx = ""

    async def proposal_generator():
        async for event in stream_architect_proposal(req.query, memory_context=memory_ctx):
            # Cache the final proposal for the apply pipeline
            if event.get("architect_done"):
                state = await _get_state(_user)
                state["proposal"] = event.get("proposal", "")
                state["implementation"] = None
                state["pending_apply"] = False
                await _set_state(_user, state)
            yield {"data": json.dumps(event)}
        yield {"data": json.dumps({"stream_end": True})}

    return EventSourceResponse(proposal_generator())


# ── Implementation endpoint ───────────────────────────────────────────────────

@router.post("/implement")
async def architect_implement(
    req: ImplementRequest,
    _user: str = Depends(require_auth),
):
    """
    Auto-generate implementation code for an approved feature (SSE).

    Events:
      {"implement_start": true, "message": "..."}
      {"implement_chunk": "..."}
      {"implement_done": true, "implementation": "...", "feature_name": "..."}
    """
    from agents.architect_agent import stream_auto_implement

    # Use provided context or fall back to cached proposal
    cached = await _get_state(_user)
    context = req.proposal_context or (cached.get("proposal") or "")

    async def impl_generator():
        async for event in stream_auto_implement(
            feature_name=req.feature_name,
            proposal_context=context,
        ):
            # Cache the implementation for the apply step
            if event.get("implement_done"):
                state = await _get_state(_user)
                state["implementation"] = event.get("implementation", "")
                state["feature_name"] = req.feature_name
                state["pending_apply"] = True
                await _set_state(_user, state)
            yield {"data": json.dumps(event)}
        yield {"data": json.dumps({"stream_end": True})}

    return EventSourceResponse(impl_generator())


# ── Apply endpoint ────────────────────────────────────────────────────────────

@router.post("/apply")
async def architect_apply(
    req: ApplyRequest,
    _user: str = Depends(_require_admin),   # Admin-only: this mutates the working tree
):
    """
    Apply the cached implementation diffs + commit + restart services.
    Returns a JSON result (not SSE — this is a synchronous operation).
    """
    from utils.auto_implement import apply_implementation

    state = await _get_state(_user)
    impl = state.get("implementation")
    if not impl:
        return {
            "success": False,
            "message": "No pending implementation found. Run /architect/implement first.",
        }

    result = await apply_implementation(impl, dry_run=req.dry_run)

    if result.success and not req.dry_run:
        state["pending_apply"] = False
        state["implementation"] = None
        await _set_state(_user, state)

    return {
        "success": result.success,
        "message": result.message,
        "files_changed": result.files_changed,
        "commit_hash": result.commit_hash,
        "services_restarted": result.services_restarted,
        "error": result.error,
        "dry_run": req.dry_run,
    }


# ── Status endpoint ───────────────────────────────────────────────────────────

@router.get("/status")
async def architect_status(_user: str = Depends(require_auth)):
    """Return the current Architect Agent state."""
    state = await _get_state(_user)
    return {
        "has_proposal": state["proposal"] is not None,
        "has_implementation": state["implementation"] is not None,
        "feature_name": state["feature_name"],
        "pending_apply": state["pending_apply"],
        "proposal_preview": (state["proposal"] or "")[:500] + "…"
        if state.get("proposal") and len(state["proposal"]) > 500
        else state.get("proposal"),
    }
