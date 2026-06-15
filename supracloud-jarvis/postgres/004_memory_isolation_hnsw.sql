-- =============================================================================
-- Migration 004 — Memory per-user isolation + HNSW index upgrade
-- =============================================================================
-- Fix #34: Add user_id column to memory_embeddings so each user's memories
--          are stored and retrieved in isolation (no cross-user leakage).
-- Fix #42: Replace the IVFFlat index with HNSW. IVFFlat requires the lists
--          parameter to be tuned at index-build time; HNSW is parameter-free,
--          consistently faster at recall, and supports CONCURRENTLY rebuilds.
-- Fix #75: Add created_at index to support the fast O(log n) retention purge.
-- =============================================================================

BEGIN;

-- Fix #34: per-user isolation ─────────────────────────────────────────────────
-- Default 'system' preserves backwards-compatibility for embeddings stored
-- before this migration (legacy rows are treated as owner-wide system memories).
ALTER TABLE memory_embeddings
    ADD COLUMN IF NOT EXISTS user_id TEXT NOT NULL DEFAULT 'system';

CREATE INDEX IF NOT EXISTS idx_memory_embeddings_user_id
    ON memory_embeddings (user_id);

-- Fix #42: HNSW upgrade ────────────────────────────────────────────────────────
-- IVFFlat (lists=100) trades recall for build speed and requires nlist/nprobe
-- tuning. HNSW (m=16, ef_construction=64) achieves higher recall with no
-- pre-training and supports concurrent inserts without index degradation.
DROP INDEX IF EXISTS idx_memory_embedding_cosine;

CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Fix #75: index for efficient date-range purge ───────────────────────────────
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_created_at
    ON memory_embeddings (created_at);

COMMIT;
