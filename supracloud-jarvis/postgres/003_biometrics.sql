-- =============================================================================
-- IRA Phase 5 Migration — Biometric Voice Profiles
-- Stores the owner's ECAPA-TDNN speaker embedding for voice authentication.
-- =============================================================================

-- =============================================================================
-- VOICE PROFILES
-- One row per registered owner. The embedding is the averaged ECAPA-TDNN
-- vector (192 dimensions, L2-normalised) used for cosine similarity matching.
-- =============================================================================

CREATE TABLE IF NOT EXISTS voice_profiles (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    owner_name  TEXT NOT NULL UNIQUE,   -- e.g. 'Your Name Here'
    embedding   TEXT NOT NULL,          -- JSON array of 192 floats (L2-normalised)
    segments    INTEGER DEFAULT 1,      -- How many reference segments were averaged
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DROP TRIGGER IF EXISTS trg_voice_profiles_updated_at ON voice_profiles;  -- Fix P28
CREATE TRIGGER trg_voice_profiles_updated_at
    BEFORE UPDATE ON voice_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- BIOMETRIC AUDIT LOG
-- Records every biometric check result for security auditing.
-- =============================================================================

CREATE TABLE IF NOT EXISTS biometric_audit (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id  TEXT NOT NULL,
    similarity  FLOAT NOT NULL,
    threshold   FLOAT NOT NULL,
    result      BOOLEAN NOT NULL,       -- TRUE = authenticated, FALSE = rejected
    source      TEXT DEFAULT 'voice',   -- 'voice' | 'replay_check'
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_biometric_audit_recent
    ON biometric_audit (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_biometric_audit_failures
    ON biometric_audit (result, created_at DESC)
    WHERE result = FALSE;
