-- Stronghold 004: Agent trust tier & review tracking
-- Adds provenance, review gates, and T4 tier support.

-- Add new columns for trust/review tracking
ALTER TABLE agents ADD COLUMN IF NOT EXISTS provenance TEXT NOT NULL DEFAULT 'user';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS ai_reviewed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS ai_review_clean BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS ai_review_flags TEXT NOT NULL DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS admin_reviewed BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS admin_reviewed_by TEXT NOT NULL DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS user_reviewed BOOLEAN NOT NULL DEFAULT FALSE;

-- Update default trust_tier from t1 to t4 (new agents start untrusted)
ALTER TABLE agents ALTER COLUMN trust_tier SET DEFAULT 't4';

-- Update existing built-in agents to t0 with builtin provenance
UPDATE agents SET trust_tier = 't0', provenance = 'builtin',
    ai_reviewed = TRUE, ai_review_clean = TRUE,
    admin_reviewed = TRUE, admin_reviewed_by = 'system'
WHERE name IN ('conduit', 'artificer', 'ranger', 'default', 'scribe', 'warden_at_arms', 'forge');

-- Audit table for trust tier changes
CREATE TABLE IF NOT EXISTS agent_trust_audit (
    id              SERIAL PRIMARY KEY,
    agent_name      TEXT NOT NULL,
    old_tier        TEXT NOT NULL,
    new_tier        TEXT NOT NULL,
    action          TEXT NOT NULL,  -- 'ai_review', 'admin_review', 'promote', 'demote', 'import'
    performed_by    TEXT NOT NULL,
    details         TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_trust_audit_agent ON agent_trust_audit (agent_name, created_at DESC);
