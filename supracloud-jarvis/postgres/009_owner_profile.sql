-- 009_owner_profile.sql — the owner's "who I am" profile (business data).
--
-- A single, overwrite-in-place record holding the owner's name, goals, current
-- projects, and free-form preferences. A compact summary of this row is injected
-- into the brain's context on every chat turn (both the Cortex and legacy paths)
-- so IRA stays grounded in who it's working for — distinct from conversational
-- recall, which Cortex owns.
--
-- Singleton enforced via a BOOLEAN primary key fixed to TRUE.

CREATE TABLE IF NOT EXISTS owner_profile (
    id          BOOLEAN PRIMARY KEY DEFAULT TRUE,
    name        TEXT NOT NULL DEFAULT '',
    goals       TEXT NOT NULL DEFAULT '',
    projects    TEXT NOT NULL DEFAULT '',
    preferences TEXT NOT NULL DEFAULT '',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT owner_profile_singleton CHECK (id IS TRUE)
);

-- Seed the single row so UPDATE-in-place always has a target.
INSERT INTO owner_profile (id) VALUES (TRUE) ON CONFLICT (id) DO NOTHING;
