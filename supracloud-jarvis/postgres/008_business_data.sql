-- =============================================================================
-- 008_business_data.sql — Phase 5: multi-tenant business data
-- Postgres = BUSINESS DATA ONLY (memory/recall belongs to Cortex).
-- Tenant isolation: every business table carries tenant_id; the access layer
-- (ira/data/) scopes EVERY query by tenant_id (primary guard). Row-Level Security
-- below is defense-in-depth — it fails SAFE (no app.tenant_id set -> zero rows).
-- =============================================================================

CREATE TABLE IF NOT EXISTS tenants (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Investor outreach records (SupraCloud fundraising pipeline)
CREATE TABLE IF NOT EXISTS investors (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id   UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    firm        TEXT,
    stage       TEXT NOT NULL DEFAULT 'prospect'
                    CHECK (stage IN ('prospect','contacted','meeting','committed','passed')),
    notes       TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_investors_tenant ON investors (tenant_id, created_at DESC);

-- Client -> agent generation specs (the SupraCloud product: per-client agents)
CREATE TABLE IF NOT EXISTS client_agents (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id    UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    client_name  TEXT NOT NULL,
    spec         JSONB NOT NULL DEFAULT '{}',
    status       TEXT NOT NULL DEFAULT 'draft'
                     CHECK (status IN ('draft','building','delivered','archived')),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_client_agents_tenant ON client_agents (tenant_id, created_at DESC);

-- updated_at triggers (reuse update_updated_at() from init.sql)
DROP TRIGGER IF EXISTS trg_investors_updated_at ON investors;
CREATE TRIGGER trg_investors_updated_at BEFORE UPDATE ON investors
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
DROP TRIGGER IF EXISTS trg_client_agents_updated_at ON client_agents;
CREATE TRIGGER trg_client_agents_updated_at BEFORE UPDATE ON client_agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- =============================================================================
-- Defense-in-depth: Row-Level Security on the per-connection app.tenant_id GUC.
-- The access layer SETs app.tenant_id per transaction; with current_setting(...,true)
-- an unset GUC yields NULL -> the policy matches no rows (fail-closed).
-- The explicit WHERE tenant_id in ira/data/ is the PRIMARY guard; this is the backstop.
-- =============================================================================
ALTER TABLE investors      ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_agents  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_investors ON investors;
CREATE POLICY tenant_isolation_investors ON investors
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);

DROP POLICY IF EXISTS tenant_isolation_client_agents ON client_agents;
CREATE POLICY tenant_isolation_client_agents ON client_agents
    USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
