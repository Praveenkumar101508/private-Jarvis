-- =============================================================================
-- Migration 006 — TOTP two-factor authentication secrets
-- Feat P26: stores per-user TOTP secrets; NULL row = TOTP not enrolled
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS totp_secrets (
    username     TEXT PRIMARY KEY,
    secret       TEXT NOT NULL,          -- base32-encoded TOTP secret (RFC 6238)
    enrolled_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
