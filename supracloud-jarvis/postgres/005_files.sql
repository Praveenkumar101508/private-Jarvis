-- =============================================================================
-- Migration 005 — Persistent user-uploaded file storage
-- Feat P25: files table for durable file storage across sessions
-- =============================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS files (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      TEXT NOT NULL,
    filename     TEXT NOT NULL,
    mime_type    TEXT NOT NULL DEFAULT 'application/octet-stream',
    size_bytes   BIGINT NOT NULL DEFAULT 0,
    storage_path TEXT NOT NULL,  -- absolute path inside the files_data volume
    sha256       TEXT NOT NULL,  -- hex digest for deduplication / integrity checks
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata     JSONB NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_files_user_created
    ON files (user_id, created_at DESC);

COMMIT;
