"""Strategy calibration endpoints (Phase 6).

Record real outcomes for past strategy predictions so FUTURE strategy runs are
calibrated against the OWNER'S OWN track record — sovereign, learned only from local
Postgres. This is calibration of estimates against the owner's history; it is NOT
model retraining and NOT ground-truth simulation.

POST /api/v1/strategy/outcome      -> record what actually happened for a prediction
GET  /api/v1/strategy/predictions  -> recent predictions (find ids to resolve)

Owner-gated via require_auth (DEV_MODE bypasses locally).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from agents import strategy_calibration as cal
from api.middleware.auth import require_auth

router = APIRouter(prefix="/strategy", tags=["strategy"])


class OutcomeBody(BaseModel):
    prediction_id: str = Field(..., description="id returned when the prediction was stored")
    outcome: str = Field(..., description="success | partial | failure")
    notes: str = ""


@router.post("/outcome")
async def record_strategy_outcome(body: OutcomeBody, _user: str = Depends(require_auth)) -> dict:
    """Record an outcome and recompute that domain's stored calibration."""
    if body.outcome not in cal.VALID_OUTCOMES:
        raise HTTPException(status_code=400, detail=f"outcome must be one of {sorted(cal.VALID_OUTCOMES)}")
    try:
        row = await cal.record_outcome(body.prediction_id, body.outcome, body.notes)
    except LookupError:
        raise HTTPException(status_code=404, detail="prediction not found")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    calibration = await cal.recompute_calibration(row["domain"])
    return {"ok": True, "prediction_id": row["id"], "domain": row["domain"],
            "outcome": row["outcome"], "calibration": calibration}


@router.get("/predictions")
async def list_strategy_predictions(
    unresolved: bool = False,
    limit: int = 20,
    _user: str = Depends(require_auth),
) -> dict:
    """List recent predictions (newest first); `unresolved=true` filters to open ones."""
    rows = await cal.list_predictions(unresolved_only=unresolved, limit=min(max(limit, 1), 100))
    return {"predictions": rows, "count": len(rows)}
