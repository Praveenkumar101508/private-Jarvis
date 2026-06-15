-- 010_strategy_calibration.sql — Phase 6: sovereign strategy calibration.
--
-- Strategy mode (agents/strategy_mode.py) records each option it scored as a
-- PREDICTION. When the owner later records what actually happened, we measure the
-- gap between the predicted success probability and the realised outcome and store
-- a per-domain calibration adjustment (multiplier/offset) that nudges FUTURE
-- estimates toward the owner's own track record.
--
-- HONEST FRAMING: this is calibration of estimates against the client's OWN history
-- — NOT model retraining, NOT ground-truth simulation, NOT "optimal". It learns only
-- from the owner's recorded decisions (sovereign; nothing leaves the box).
--
-- This is the owner's own decision data (business data, project rule 5) — distinct
-- from conversational recall, which Cortex owns.

CREATE TABLE IF NOT EXISTS strategy_predictions (
    id                   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    question             TEXT NOT NULL,
    domain               TEXT NOT NULL DEFAULT 'general',
    option_name          TEXT NOT NULL,
    success_probability  DOUBLE PRECISION NOT NULL,   -- the RAW model estimate (pre-calibration)
    risk                 DOUBLE PRECISION NOT NULL,
    effort               DOUBLE PRECISION NOT NULL,
    utility              DOUBLE PRECISION NOT NULL,
    outcome              TEXT,            -- NULL until resolved, then success | partial | failure
    outcome_notes        TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at          TIMESTAMPTZ,
    CONSTRAINT strategy_outcome_valid
        CHECK (outcome IS NULL OR outcome IN ('success', 'partial', 'failure'))
);

-- Fast lookup of the resolved rows that feed a domain's calibration.
CREATE INDEX IF NOT EXISTS idx_strategy_predictions_domain_resolved
    ON strategy_predictions (domain)
    WHERE outcome IS NOT NULL;

-- One stored calibration adjustment per domain, recomputed whenever an outcome lands.
-- adjusted_success = clamp01(raw * multiplier + offset_adj).  ("offset" is reserved.)
CREATE TABLE IF NOT EXISTS strategy_calibration (
    domain      TEXT PRIMARY KEY,
    multiplier  DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    offset_adj  DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    n_samples   INTEGER NOT NULL DEFAULT 0,   -- resolved decisions this is calibrated on
    brier       DOUBLE PRECISION,             -- reliability of the raw estimates (lower = better)
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
