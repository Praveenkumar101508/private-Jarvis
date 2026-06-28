-- =============================================================================
-- IRA Feature 1 Migration — Life Context Graph
-- A structured entity + edge layer beside the pgvector store. The vector store is
-- fuzzy recall; this graph is structured traversal ("everything connected to the
-- Luxembourg application"). Gated at the application layer by IRA_LIFE_GRAPH.
-- =============================================================================

-- Entities: people, projects, applications, documents, places — anything the owner
-- refers to repeatedly. `description` is embedded (BGE-large, 1024-dim) so entities
-- can be matched semantically, reusing the same vector machinery as memory_embeddings.
CREATE TABLE IF NOT EXISTS entities (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    type         TEXT NOT NULL,                 -- 'person' | 'project' | 'application' | ...
    name         TEXT NOT NULL,
    description  TEXT,
    embedding    vector(1024),                  -- BGE-large-en-v1.5 of description (nullable)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- An entity is uniquely identified by (type, name) — this is the upsert key.
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_type_name ON entities (type, name);

-- Edges: directed, typed relationships between entities. `weight` lets callers
-- record relationship strength (default 1.0). (src, dst, relation) is the upsert key
-- so re-asserting an edge updates its weight instead of duplicating it.
CREATE TABLE IF NOT EXISTS edges (
    id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    src_entity_id  UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    dst_entity_id  UUID NOT NULL REFERENCES entities (id) ON DELETE CASCADE,
    relation       TEXT NOT NULL,
    weight         DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_edges_src_dst_relation
    ON edges (src_entity_id, dst_entity_id, relation);

-- Traversal indexes — neighbors() walks edges in both directions.
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges (src_entity_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges (dst_entity_id);
