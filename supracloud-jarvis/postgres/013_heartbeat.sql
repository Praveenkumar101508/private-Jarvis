-- =============================================================================
-- IRA Feature 3 Migration — Heartbeat de-dupe ledger
-- The Heartbeat is a scheduled, read-only pass that surfaces items unprompted via
-- the voice path. This table records what has already been surfaced so the same
-- item is never repeated. Gated at the app layer by IRA_HEARTBEAT.
-- =============================================================================

CREATE TABLE IF NOT EXISTS heartbeat_surfaced (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_key     TEXT NOT NULL UNIQUE,     -- stable per-item identity (the de-dupe key)
    kind         TEXT NOT NULL,            -- 'decision_review' | 'stale_commitment' | ...
    message      TEXT,                     -- what was spoken (for audit)
    surfaced_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_heartbeat_surfaced_kind ON heartbeat_surfaced (kind);
