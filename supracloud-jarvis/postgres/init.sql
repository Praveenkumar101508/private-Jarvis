-- =============================================================================
-- SupraCloud Jarvis — PostgreSQL Schema
-- Runs once on first container start (via docker-entrypoint-initdb.d)
-- =============================================================================

-- Enable pgvector for semantic memory and RAG
CREATE EXTENSION IF NOT EXISTS vector;
-- Enable pg_trgm for fast fuzzy text search
CREATE EXTENSION IF NOT EXISTS pg_trgm;
-- Enable uuid-ossp for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- CONVERSATIONS & MESSAGES
-- Long-term memory with full conversation history
-- =============================================================================

CREATE TABLE IF NOT EXISTS conversations (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id    TEXT NOT NULL,
    title         TEXT,
    summary       TEXT,                   -- Compressed summary for long convos
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata      JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content         TEXT NOT NULL,
    model_used      TEXT,                 -- Which model served this response
    latency_ms      INTEGER,              -- Response time for performance tracking
    tokens_in       INTEGER,
    tokens_out      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}'
);

-- =============================================================================
-- MEMORY EMBEDDINGS (RAG / Semantic Search)
-- Stores vector embeddings for long-term memory retrieval
-- =============================================================================

CREATE TABLE IF NOT EXISTS memory_embeddings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id   UUID,                     -- FK to messages.id or documents.id
    source_type TEXT NOT NULL,            -- 'message' | 'document' | 'fact'
    content     TEXT NOT NULL,            -- Raw text that was embedded
    embedding   vector(1024),            -- BGE-large-en-v1.5 = 1024 dimensions
    user_id     TEXT NOT NULL DEFAULT 'system',  -- per-user memory isolation (Fix #34)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB DEFAULT '{}'
);

-- Fix P14: fresh installs already have user_id column + HNSW index so migration 004
-- is a no-op (all its DDL uses IF NOT EXISTS / DROP IF EXISTS). Older installs
-- still need 004 — do not remove it.

-- Per-user isolation index (migration 004 also creates this idempotently)
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_user_id
    ON memory_embeddings (user_id);

-- Date-range purge index (migration 004 also creates this idempotently)
CREATE INDEX IF NOT EXISTS idx_memory_embeddings_created_at
    ON memory_embeddings (created_at);

-- HNSW index for fast approximate nearest-neighbour search.
--
-- Parameters chosen for a personal-scale deployment (~100k–1M rows):
--
--   m = 16  (max bidirectional links per node)
--     Controls graph density and memory usage.
--     Higher m → better recall + lower query latency, but more index RAM.
--     Range: 2–100.  Default: 16.  Typical choices: 8 (low RAM) / 16 (balanced) / 32 (high recall).
--     For a single-user assistant 16 is the sweet spot.
--
--   ef_construction = 64  (search width during index build)
--     Controls build quality — how many candidates are evaluated when inserting each node.
--     Higher → better recall and slower index build time (not query time).
--     Range: ≥ 2*m.  Default: 64.  64 at m=16 gives >95% recall on typical embeddings.
--
--   vector_cosine_ops (distance metric)
--     BGE-large-en-v1.5 embeddings are L2-normalised, so cosine similarity is the
--     correct metric.  Using inner-product (vector_ip_ops) would give identical
--     results on normalised vectors but cosine_ops is clearer and safer.
--
-- Tuning guidance:
--   If recall drops below 90% at scale, increase m to 32 and ef_construction to 128,
--   then rebuild: DROP INDEX idx_memory_embedding_hnsw; followed by this CREATE.
--   At query time, SET hnsw.ef_search = 100 (session or per-query) to trade
--   a few ms of latency for higher recall without touching the index.
CREATE INDEX IF NOT EXISTS idx_memory_embedding_hnsw
    ON memory_embeddings USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- =============================================================================
-- REGISTERED AGENTS
-- Meta Agent Creator outputs stored here for persistence + re-deployment
-- =============================================================================

CREATE TABLE IF NOT EXISTS agents (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         TEXT NOT NULL UNIQUE,
    description  TEXT,
    code         TEXT,                    -- Generated LangGraph Python code
    docker_config TEXT,                  -- Generated docker-compose snippet
    status       TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft', 'active', 'disabled')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata     JSONB DEFAULT '{}'
);

-- =============================================================================
-- SECURITY EVENTS
-- Security Guardian writes here; Jarvis reads for alerting
-- =============================================================================

CREATE TABLE IF NOT EXISTS security_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    severity    TEXT NOT NULL CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
    event_type  TEXT NOT NULL,           -- 'login_failure' | 'port_scan' | 'anomaly' | etc.
    source_ip   INET,
    description TEXT NOT NULL,
    raw_log     TEXT,
    resolved    BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_security_events_severity
    ON security_events (severity, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_security_events_unresolved
    ON security_events (resolved, created_at DESC)
    WHERE resolved = FALSE;

-- =============================================================================
-- BUSINESS EVENTS (SupraCloud Website Manager)
-- Leads, bookings, site updates, reports
-- =============================================================================

CREATE TABLE IF NOT EXISTS business_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type  TEXT NOT NULL,           -- 'lead' | 'booking' | 'site_update' | 'report'
    title       TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'new',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata    JSONB DEFAULT '{}'
);

-- =============================================================================
-- MODEL PERFORMANCE LOG
-- Tracks latency per model to drive routing decisions
-- =============================================================================

CREATE TABLE IF NOT EXISTS model_performance (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    model_name   TEXT NOT NULL,
    request_type TEXT,                   -- 'fast_path' | 'deep_path'
    latency_ms   INTEGER NOT NULL,
    tokens_in    INTEGER,
    tokens_out   INTEGER,
    success      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index on model performance for dashboard queries (filter in queries, not index)
CREATE INDEX IF NOT EXISTS idx_model_perf_recent
    ON model_performance (model_name, created_at DESC);

-- =============================================================================
-- UTILITY: auto-update updated_at timestamps
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_conversations_updated_at
    BEFORE UPDATE ON conversations
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_agents_updated_at
    BEFORE UPDATE ON agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- Seed: system conversation for Jarvis bootstrap messages
--
-- The UUID '00000000-0000-0000-0000-000000000001' is a fixed sentinel value.
-- Hard-coding it (rather than uuid_generate_v4()) lets application code and
-- other seed files reference it as a stable foreign key without requiring a
-- prior SELECT.  It is intentionally not a real v4 UUID — the nil-prefix
-- makes it visually distinct from auto-generated rows in queries and logs.
-- Do NOT change this value; doing so will break any rows that reference it.
-- =============================================================================
INSERT INTO conversations (id, session_id, title)
VALUES (
    '00000000-0000-0000-0000-000000000001',
    'system',
    'Jarvis System Bootstrap'
) ON CONFLICT (id) DO NOTHING;
