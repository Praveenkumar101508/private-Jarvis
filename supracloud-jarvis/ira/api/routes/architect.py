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

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from api.middleware.auth import require_auth
from memory.store import retrieve

router = APIRouter(prefix="/architect", tags=["architect"])

# ── In-memory proposal store (single-user system — no persistence needed) ────
# Stores the latest proposal + implementation so the user can approve/apply
_state: dict = {
    "proposal": None,          # Latest supervisor output text
    "implementation": None,    # Latest auto-implement output text
    "feature_name": None,      # Feature being implemented
    "pending_apply": False,    # True when implementation is ready to apply
}


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
                _state["proposal"] = event.get("proposal", "")
                _state["implementation"] = None
                _state["pending_apply"] = False
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
    context = req.proposal_context or (_state.get("proposal") or "")

    async def impl_generator():
        async for event in stream_auto_implement(
            feature_name=req.feature_name,
            proposal_context=context,
        ):
            # Cache the implementation for the apply step
            if event.get("implement_done"):
                _state["implementation"] = event.get("implementation", "")
                _state["feature_name"] = req.feature_name
                _state["pending_apply"] = True
            yield {"data": json.dumps(event)}
        yield {"data": json.dumps({"stream_end": True})}

    return EventSourceResponse(impl_generator())


# ── Apply endpoint ────────────────────────────────────────────────────────────

@router.post("/apply")
async def architect_apply(
    req: ApplyRequest,
    _user: str = Depends(require_auth),
):
    """
    Apply the cached implementation diffs + commit + restart services.
    Returns a JSON result (not SSE — this is a synchronous operation).
    """
    from utils.auto_implement import apply_implementation

    impl = _state.get("implementation")
    if not impl:
        return {
            "success": False,
            "message": "No pending implementation found. Run /architect/implement first.",
        }

    result = await apply_implementation(impl, dry_run=req.dry_run)

    if result.success and not req.dry_run:
        _state["pending_apply"] = False
        _state["implementation"] = None

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
    return {
        "has_proposal": _state["proposal"] is not None,
        "has_implementation": _state["implementation"] is not None,
        "feature_name": _state["feature_name"],
        "pending_apply": _state["pending_apply"],
        "proposal_preview": (_state["proposal"] or "")[:500] + "…"
        if _state.get("proposal") and len(_state["proposal"]) > 500
        else _state.get("proposal"),
    }
