"""
agents/strategy_calibration.py — Phase 6: sovereign strategy calibration.

Strategy mode (agents/strategy_mode.py) is ESTIMATION, not ground truth. This module
closes the loop using the owner's OWN recorded outcomes:

  1. persist_predictions(...)   — every strategy run stores its (raw) option estimates.
  2. record_outcome(...)        — the owner later records what actually happened.
  3. recompute_calibration(...) — measure the gap (Brier score / mean realised vs mean
                                  predicted) and store a per-domain adjustment.
  4. load_calibration(...)      — future runs read the stored adjustment and nudge their
                                  success estimates toward the owner's track record.

HONEST FRAMING (matters): this calibrates ESTIMATES against the client's own history.
It is NOT model retraining, NOT ground-truth simulation, NOT "optimal". The adjustment
is a transparent, bounded `clamp01(raw * multiplier + offset)`, shrunk toward
no-correction when data is sparse so a couple of outcomes can't swing it wildly.

Sovereign: learns only from local Postgres; nothing leaves the box.

DB access mirrors ira/data — utils.db is imported LAZILY inside the DB paths and every
function accepts `conn=` so the unit tests inject a fake connection (no live Postgres).
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("ira.strategy.calibration")

# Map a recorded outcome to a realised success value in [0, 1].
OUTCOME_SCORES: dict[str, float] = {"success": 1.0, "partial": 0.5, "failure": 0.0}
VALID_OUTCOMES = frozenset(OUTCOME_SCORES)

# Shrinkage: with few resolved decisions, trust the raw estimate more (don't overfit
# the owner's first one or two outcomes). offset is scaled by n / (n + _SHRINK_K).
_SHRINK_K = 3.0

# Coarse domain buckets so calibration is per-kind-of-decision without fragmenting the
# (sparse) data. First keyword match wins; everything else is "general".
_DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "hiring":  ("hire", "hiring", "recruit", "headcount", "fire", "layoff", "staff", "employee"),
    "finance": ("price", "pricing", "budget", "invest", "funding", "fundrais", "raise capital",
                "cost", "revenue", "salary", "money", "spend"),
    "tech":    ("build", "buy", "stack", "database", "infra", "architecture", "framework",
                "migrate", "refactor", "self-host", "vendor"),
    "growth":  ("market", "growth", "grow", "launch", "customer", "acquire", "expand",
                "go to market", "scale", "sales", "channel"),
    "product": ("feature", "product", "roadmap", "ux", "mvp", "prototype"),
}


# ── Pure helpers (no DB — unit-tested directly) ────────────────────────────────

def _clamp01(x: Any) -> float:
    try:
        return max(0.0, min(1.0, float(x)))
    except (TypeError, ValueError):
        return 0.5


def infer_domain(question: str) -> str:
    """Bucket a strategic question into a coarse domain for per-domain calibration."""
    q = (question or "").lower()
    for domain, kws in _DOMAIN_KEYWORDS.items():
        if any(k in q for k in kws):
            return domain
    return "general"


def brier_score(pairs) -> Optional[float]:
    """Mean squared error of predicted vs realised in [0,1] (lower = better calibrated).

    pairs: iterable of (predicted_probability, realised_value). Returns None if empty.
    """
    pairs = [(float(p), float(r)) for p, r in pairs]
    if not pairs:
        return None
    return round(sum((p - r) ** 2 for p, r in pairs) / len(pairs), 4)


def compute_adjustment(pairs) -> dict:
    """Derive the stored per-domain adjustment from resolved predictions.

    pairs: iterable of (success_probability, outcome_str). Returns
    {"multiplier", "offset", "n", "brier"}. Offset corrects systematic over/under-
    confidence (mean realised − mean predicted), shrunk toward 0 when data is sparse.
    """
    clean = [
        (_clamp01(p), OUTCOME_SCORES[o])
        for (p, o) in pairs
        if p is not None and o in OUTCOME_SCORES
    ]
    n = len(clean)
    if n == 0:
        return {"multiplier": 1.0, "offset": 0.0, "n": 0, "brier": None}
    pred_mean = sum(p for p, _ in clean) / n
    real_mean = sum(r for _, r in clean) / n
    shrink = n / (n + _SHRINK_K)
    offset = round((real_mean - pred_mean) * shrink, 4)
    return {"multiplier": 1.0, "offset": offset, "n": n, "brier": brier_score(clean)}


def apply_adjustment(p: float, adj: Optional[dict]) -> float:
    """Apply a stored adjustment to a raw success estimate, clamped to [0, 1]."""
    if not adj:
        return _clamp01(p)
    return _clamp01(_clamp01(p) * float(adj.get("multiplier", 1.0)) + float(adj.get("offset", 0.0)))


# ── DB access (lazy utils.db; conn= injected by tests) ─────────────────────────

async def _with_conn(fn: Callable[[Any], Awaitable[Any]], conn: Optional[Any]) -> Any:
    """Run fn(conn) against an injected conn (tests) or a pooled conn (prod)."""
    if conn is not None:
        return await fn(conn)
    from utils.db import acquire  # lazy: this module imports without the asyncpg driver
    async with acquire() as c:
        return await fn(c)


async def persist_predictions(question: str, domain: str, options, *, conn: Optional[Any] = None) -> list[str]:
    """Store each scored option as a RAW prediction (pre-calibration). Returns the new ids."""
    async def _do(c):
        ids: list[str] = []
        for o in options:
            row = await c.fetchrow(
                """
                INSERT INTO strategy_predictions
                    (question, domain, option_name, success_probability, risk, effort, utility)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                question, domain, o.name,
                float(o.success_probability), float(o.risk), float(o.effort), float(o.utility),
            )
            ids.append(str(row["id"]))
        return ids
    return await _with_conn(_do, conn)


async def record_outcome(prediction_id: str, outcome: str, notes: str = "", *, conn: Optional[Any] = None) -> dict:
    """Record what actually happened for a past prediction.

    Raises ValueError on an invalid outcome and LookupError if the id is unknown.
    Returns {"id", "domain", "option_name", "outcome"}.
    """
    if outcome not in OUTCOME_SCORES:
        raise ValueError(f"outcome must be one of {sorted(OUTCOME_SCORES)}")

    async def _do(c):
        row = await c.fetchrow(
            """
            UPDATE strategy_predictions
               SET outcome = $2, outcome_notes = $3, resolved_at = NOW()
             WHERE id = $1::uuid
            RETURNING id, domain, option_name, outcome
            """,
            prediction_id, outcome, notes or "",
        )
        if row is None:
            raise LookupError(prediction_id)
        return {"id": str(row["id"]), "domain": row["domain"],
                "option_name": row["option_name"], "outcome": row["outcome"]}
    return await _with_conn(_do, conn)


async def recompute_calibration(domain: str, *, conn: Optional[Any] = None) -> dict:
    """Recompute and store the per-domain adjustment from its resolved predictions."""
    async def _do(c):
        rows = await c.fetch(
            "SELECT success_probability, outcome FROM strategy_predictions "
            "WHERE domain = $1 AND outcome IS NOT NULL",
            domain,
        )
        adj = compute_adjustment([(r["success_probability"], r["outcome"]) for r in rows])
        await c.execute(
            """
            INSERT INTO strategy_calibration (domain, multiplier, offset_adj, n_samples, brier, updated_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            ON CONFLICT (domain) DO UPDATE SET
                multiplier = EXCLUDED.multiplier,
                offset_adj = EXCLUDED.offset_adj,
                n_samples  = EXCLUDED.n_samples,
                brier      = EXCLUDED.brier,
                updated_at = NOW()
            """,
            domain, adj["multiplier"], adj["offset"], adj["n"], adj["brier"],
        )
        return {"domain": domain, **adj}
    return await _with_conn(_do, conn)


async def load_calibration(domain: str, *, conn: Optional[Any] = None) -> tuple[dict, int]:
    """Return ({multiplier, offset}, n_samples) for a domain. ({}, 0) if none/unavailable.

    Fail-soft: a missing table or down DB must never break a strategy run.
    """
    try:
        async def _do(c):
            row = await c.fetchrow(
                "SELECT multiplier, offset_adj, n_samples FROM strategy_calibration WHERE domain = $1",
                domain,
            )
            if not row or not row["n_samples"]:
                return ({}, 0)
            return ({"multiplier": row["multiplier"], "offset": row["offset_adj"]}, int(row["n_samples"]))
        return await _with_conn(_do, conn)
    except Exception as e:  # noqa: BLE001
        logger.debug("strategy: calibration load unavailable (%s)", e)
        return ({}, 0)


async def list_predictions(*, unresolved_only: bool = False, limit: int = 20,
                           conn: Optional[Any] = None) -> list[dict]:
    """Recent predictions (newest first) so the owner can find ids to resolve. Fail-soft."""
    try:
        async def _do(c):
            where = "WHERE outcome IS NULL" if unresolved_only else ""
            rows = await c.fetch(
                f"""
                SELECT id, question, domain, option_name, success_probability, risk, effort,
                       utility, outcome, created_at
                  FROM strategy_predictions
                  {where}
                 ORDER BY created_at DESC
                 LIMIT $1
                """,
                int(limit),
            )
            out: list[dict] = []
            for r in rows:
                created = r["created_at"]
                out.append({
                    "id": str(r["id"]),
                    "question": r["question"],
                    "domain": r["domain"],
                    "option_name": r["option_name"],
                    "success_probability": r["success_probability"],
                    "risk": r["risk"],
                    "effort": r["effort"],
                    "utility": r["utility"],
                    "outcome": r["outcome"],
                    "created_at": created.isoformat() if hasattr(created, "isoformat") else created,
                })
            return out
        return await _with_conn(_do, conn)
    except Exception as e:  # noqa: BLE001
        logger.debug("strategy: list predictions unavailable (%s)", e)
        return []


__all__ = [
    "OUTCOME_SCORES", "VALID_OUTCOMES", "infer_domain", "brier_score",
    "compute_adjustment", "apply_adjustment", "persist_predictions",
    "record_outcome", "recompute_calibration", "load_calibration", "list_predictions",
]
