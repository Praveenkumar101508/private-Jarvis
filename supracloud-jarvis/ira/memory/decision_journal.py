"""
memory/decision_journal.py — IRA's Decision Journal (Feature 2).

Log a decision, its reasoning, and the outcome you EXPECT; schedule a review; later
record what actually happened. No prediction is made — the owner supplies the real
outcome, and the journal lets IRA calibrate expectation vs. reality over time.

Reuses the Memory SQL layer (``utils.db.acquire``, parameterized SQL). Gated by
IRA_DECISION_JOURNAL (default ON, read via the IRA_USE_CORTEX mechanism). When a
decision concerns a Life-Graph entity AND IRA_LIFE_GRAPH is ON, the decision is
optionally linked into the graph with a ``decision_about`` edge — but the graph is a
soft dependency: if that flag is OFF (or the link fails) the decision still logs.

No scheduler is wired here. ``list_pending_reviews`` is the read surface the Heartbeat
feature (Feature 3) will later poll.
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime
from typing import Optional

from utils.db import acquire

logger = logging.getLogger("ira.memory.decision_journal")

_TRUTHY = ("1", "true", "yes", "on")


def journal_enabled() -> bool:
    """Whether the Decision Journal is active. Defaults ON; set
    IRA_DECISION_JOURNAL=false to disable."""
    return os.getenv("IRA_DECISION_JOURNAL", "true").strip().lower() in _TRUTHY


async def log_decision(
    summary: str,
    *,
    reasoning: str | None = None,
    expected_outcome: str | None = None,
    review_at: datetime,
    about_entity_id: str | None = None,
) -> Optional[str]:
    """Record a decision and schedule its review. Returns the decision id, or None.

    ``review_at`` is required — a decision with no scheduled review can never be
    calibrated. If ``about_entity_id`` is given and IRA_LIFE_GRAPH is ON, the decision
    is linked into the Life Graph with a ``decision_about`` edge (best-effort; a link
    failure never fails the log).
    """
    if not journal_enabled():
        return None
    if not (summary or "").strip():
        logger.debug("decision_journal.log_decision: summary is required")
        return None
    try:
        async with acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO decisions
                       (summary, reasoning, expected_outcome, review_at)
                   VALUES ($1, $2, $3, $4)
                   RETURNING id""",
                summary, reasoning, expected_outcome, review_at,
            )
        decision_id = str(row["id"]) if row else None
    except Exception as e:
        logger.warning(f"decision_journal.log_decision failed (fail-closed): {e}")
        return None

    if decision_id and about_entity_id:
        await _link_to_graph(decision_id, summary, about_entity_id)
    return decision_id


async def list_pending_reviews(now: datetime) -> list[dict]:
    """Decisions whose review_at <= now and that have not yet been reviewed.

    This is the surface the Heartbeat polls. Returns [] on any error or when the
    flag is OFF.
    """
    if not journal_enabled():
        return []
    try:
        async with acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, summary, reasoning, expected_outcome,
                          decided_at, review_at
                   FROM decisions
                   WHERE review_at <= $1 AND reviewed_at IS NULL
                   ORDER BY review_at ASC""",
                now,
            )
        return [
            {
                "id": str(r["id"]),
                "summary": r["summary"],
                "reasoning": r["reasoning"],
                "expected_outcome": r["expected_outcome"],
                "decided_at": r["decided_at"].isoformat() if r["decided_at"] else None,
                "review_at": r["review_at"].isoformat() if r["review_at"] else None,
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning(f"decision_journal.list_pending_reviews failed (fail-closed): {e}")
        return []


async def record_outcome(
    decision_id: str,
    actual_outcome: str,
    calibration_note: str | None = None,
) -> bool:
    """Record what actually happened, clearing the decision from pending reviews.

    Returns True on success, False on any error or when the flag is OFF. Only updates
    rows not already reviewed (idempotent — a second call is a no-op).
    """
    if not journal_enabled():
        return False
    try:
        async with acquire() as conn:
            result = await conn.execute(
                """UPDATE decisions
                   SET actual_outcome = $2,
                       calibration_note = $3,
                       reviewed_at = NOW()
                   WHERE id = $1 AND reviewed_at IS NULL""",
                uuid.UUID(decision_id), actual_outcome, calibration_note,
            )
        # asyncpg returns "UPDATE N"
        updated = int(result.split()[-1]) if result and result.startswith("UPDATE") else 0
        return updated > 0
    except Exception as e:
        logger.warning(f"decision_journal.record_outcome failed (fail-closed): {e}")
        return False


# ── optional Life-Graph linkage (soft dependency) ─────────────────────────────

async def _link_to_graph(decision_id: str, summary: str, about_entity_id: str) -> None:
    """Best-effort: link this decision to a graph entity via a decision_about edge.

    No-op (silent) if IRA_LIFE_GRAPH is OFF. Any failure is swallowed — the decision
    is already persisted; the graph link is a bonus, never a hard requirement.
    """
    try:
        from memory import life_graph
        if not life_graph.graph_enabled():
            return
        decision_entity_id = await life_graph.upsert_entity(
            "decision", f"decision:{decision_id}", description=summary,
        )
        if decision_entity_id:
            await life_graph.add_edge(decision_entity_id, about_entity_id, "decision_about")
    except Exception as e:
        logger.debug(f"decision_journal: graph link skipped (non-fatal): {e}")
