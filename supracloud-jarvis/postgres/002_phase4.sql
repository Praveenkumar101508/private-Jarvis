-- =============================================================================
-- IRA Phase 4 Migration — Proactive Intelligence Schema
-- Run: docker exec ira-postgres psql -U ira -d ira_db -f /migrations/002_phase4.sql
-- =============================================================================

-- =============================================================================
-- TASKS & TO-DO LIST
-- IRA manages tasks on behalf of the user, tracks progress, sends reminders
-- =============================================================================

CREATE TABLE IF NOT EXISTS tasks (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    title        TEXT NOT NULL,
    description  TEXT,
    priority     TEXT NOT NULL DEFAULT 'medium'
                     CHECK (priority IN ('low', 'medium', 'high', 'urgent')),
    status       TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'in_progress', 'done', 'cancelled')),
    due_at       TIMESTAMPTZ,
    tags         TEXT[] DEFAULT '{}',
    source       TEXT DEFAULT 'manual',   -- 'manual' | 'ira' | 'calendar' | 'lead'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    metadata     JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status, due_at ASC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks (priority, status)
    WHERE status NOT IN ('done', 'cancelled');

-- =============================================================================
-- REMINDERS
-- Linked to tasks or standalone; delivered via one or more channels
-- =============================================================================

CREATE TABLE IF NOT EXISTS reminders (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id     UUID REFERENCES tasks(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    body        TEXT,
    remind_at   TIMESTAMPTZ NOT NULL,
    -- APScheduler cron expression for repeating reminders (NULL = one-shot)
    repeat_cron TEXT,
    channels    TEXT[] DEFAULT ARRAY['websocket'],  -- 'websocket','telegram','email'
    sent        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (remind_at ASC)
    WHERE sent = FALSE;

-- =============================================================================
-- CALENDAR EVENTS
-- Synced from Cal.com / Google Calendar; IRA monitors and alerts on these
-- =============================================================================

CREATE TABLE IF NOT EXISTS calendar_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    external_id     TEXT UNIQUE,              -- ID from Cal.com or Google
    source          TEXT NOT NULL DEFAULT 'calcom',  -- 'calcom' | 'google'
    title           TEXT NOT NULL,
    description     TEXT,
    attendees       JSONB DEFAULT '[]',
    start_at        TIMESTAMPTZ NOT NULL,
    end_at          TIMESTAMPTZ NOT NULL,
    location        TEXT,
    status          TEXT DEFAULT 'confirmed',
    reminded        BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata        JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_calendar_upcoming ON calendar_events (start_at ASC);

-- =============================================================================
-- NOTIFICATIONS
-- Full history of all proactive alerts IRA has sent
-- =============================================================================

CREATE TABLE IF NOT EXISTS notifications (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    category      TEXT NOT NULL,
        -- 'briefing' | 'security' | 'business' | 'reminder' | 'task' | 'system'
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    priority      TEXT NOT NULL DEFAULT 'info'
                      CHECK (priority IN ('info', 'warning', 'critical')),
    channels_sent TEXT[] DEFAULT '{}',
    read          BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata      JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_notifications_unread ON notifications (created_at DESC)
    WHERE read = FALSE;
CREATE INDEX IF NOT EXISTS idx_notifications_category ON notifications (category, created_at DESC);

-- =============================================================================
-- BRIEFINGS
-- Full text of each IRA briefing for retrieval and reference
-- =============================================================================

CREATE TABLE IF NOT EXISTS briefings (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    briefing_type TEXT NOT NULL DEFAULT 'morning',   -- 'morning' | 'evening' | 'security' | 'business'
    content     TEXT NOT NULL,                       -- Full briefing text (Markdown)
    summary     TEXT,                                -- One-line summary
    data        JSONB DEFAULT '{}',                  -- Raw data used to generate briefing
    delivered   BOOLEAN DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_briefings_recent ON briefings (briefing_type, created_at DESC);

-- =============================================================================
-- MONITOR STATE
-- Tracks the last-seen position in log files for incremental analysis
-- =============================================================================

CREATE TABLE IF NOT EXISTS monitor_state (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Insert defaults
INSERT INTO monitor_state (key, value)
VALUES
    ('nginx_log_offset', '0'),
    ('ssh_log_offset', '0'),
    ('lockdown_active', '0'),
    ('last_security_scan', NOW()::TEXT),
    ('last_briefing_sent', '1970-01-01T00:00:00Z'),
    ('last_business_check', '1970-01-01T00:00:00Z')
ON CONFLICT (key) DO NOTHING;

-- =============================================================================
-- Triggers: auto-update updated_at
-- =============================================================================

DROP TRIGGER IF EXISTS trg_tasks_updated_at ON tasks;  -- Fix P28
CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
