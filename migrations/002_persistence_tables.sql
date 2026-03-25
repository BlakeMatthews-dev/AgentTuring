-- Stronghold 002: Multi-tenant columns + outcomes table
-- Adds org_id/team_id to learnings and audit_log,
-- converts learnings.trigger_keys to TEXT[],
-- and creates the outcomes table.

-- ============================================================================
-- Learnings: add multi-tenant columns + fix trigger_keys type
-- ============================================================================

ALTER TABLE learnings ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT '';
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS team_id TEXT NOT NULL DEFAULT '';

-- Convert trigger_keys from TEXT to TEXT[]
-- Step: rename old, add new, migrate data, drop old
ALTER TABLE learnings RENAME COLUMN trigger_keys TO trigger_keys_old;
ALTER TABLE learnings ADD COLUMN trigger_keys TEXT[] NOT NULL DEFAULT '{}';
UPDATE learnings SET trigger_keys = CASE
    WHEN trigger_keys_old = '' THEN '{}'
    ELSE string_to_array(trigger_keys_old, ',')
END;
ALTER TABLE learnings DROP COLUMN trigger_keys_old;

CREATE INDEX IF NOT EXISTS idx_learnings_org ON learnings (org_id, status);

-- ============================================================================
-- Audit Log: add multi-tenant columns
-- ============================================================================

ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT '';
ALTER TABLE audit_log ADD COLUMN IF NOT EXISTS team_id TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_audit_org ON audit_log (org_id, timestamp DESC);

-- ============================================================================
-- Outcomes (Task Completion Tracking)
-- ============================================================================

CREATE TABLE IF NOT EXISTS outcomes (
    id              SERIAL PRIMARY KEY,
    request_id      TEXT NOT NULL DEFAULT '',
    task_type       TEXT NOT NULL DEFAULT '',
    model_used      TEXT NOT NULL DEFAULT '',
    provider        TEXT NOT NULL DEFAULT '',
    tool_calls      TEXT NOT NULL DEFAULT '[]',
    success         BOOLEAN NOT NULL DEFAULT TRUE,
    error_type      TEXT NOT NULL DEFAULT '',
    response_time_ms INTEGER NOT NULL DEFAULT 0,
    org_id          TEXT NOT NULL DEFAULT '',
    team_id         TEXT NOT NULL DEFAULT '',
    user_id         TEXT NOT NULL DEFAULT '',
    agent_id        TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_outcomes_org ON outcomes (org_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_task ON outcomes (org_id, task_type, created_at DESC);
