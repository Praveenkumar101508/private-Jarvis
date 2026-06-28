-- =============================================================================
-- IRA Feature 2 Migration — Decision Journal
-- Log a decision + its reasoning + the expected outcome, schedule a review, and
-- later record what ACTUALLY happened. This is calibration, not prediction: the
-- owner supplies the real outcome. Gated at the app layer by IRA_DECISION_JOURNAL.
-- =============================================================================

CREATE TABLE IF NOT EXISTS decisions (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    summary           TEXT NOT NULL,            -- what was decided
    reasoning         TEXT,                     -- why
    expected_outcome  TEXT,                     -- what the owner expected to happen
    decided_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    review_at         TIMESTAMPTZ NOT NULL,     -- when to revisit and check
    actual_outcome    TEXT,                     -- filled in at review time (NULL until then)
    reviewed_at       TIMESTAMPTZ,              -- set when the outcome is recorded
    calibration_note  TEXT                      -- expected-vs-actual reflection
);

-- list_pending_reviews() looks up rows due for review and not yet reviewed.
CREATE INDEX IF NOT EXISTS idx_decisions_pending_review
    ON decisions (review_at)
    WHERE reviewed_at IS NULL;
