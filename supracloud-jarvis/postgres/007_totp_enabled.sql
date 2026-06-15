-- =============================================================================
-- Migration 007 — add enabled flag to TOTP secrets (Fix P29)
-- Existing installs have 006 applied; this adds the column idempotently.
-- Fresh installs already have the column from 006_totp.sql; ADD COLUMN IF NOT
-- EXISTS makes running both files harmless.
-- =============================================================================

BEGIN;

ALTER TABLE totp_secrets
    ADD COLUMN IF NOT EXISTS enabled BOOLEAN NOT NULL DEFAULT FALSE;

COMMIT;
