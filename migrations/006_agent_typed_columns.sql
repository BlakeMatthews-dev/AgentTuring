-- Stronghold 005: Add typed columns to agents table
-- Replaces the generic JSONB `config` blob with explicit typed columns.
-- The `config` column is kept for backwards compatibility but should not
-- be used for new data.

-- Soul prompt and rules (previously stored in separate prompts table)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS soul TEXT NOT NULL DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS rules TEXT NOT NULL DEFAULT '';

-- Agent behavior (previously buried in config JSONB)
ALTER TABLE agents ADD COLUMN IF NOT EXISTS reasoning_strategy TEXT NOT NULL DEFAULT 'direct';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS model TEXT NOT NULL DEFAULT 'auto';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS model_fallbacks TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS model_constraints JSONB NOT NULL DEFAULT '{}';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS tools TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS skills TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS max_tool_rounds INTEGER NOT NULL DEFAULT 3;
ALTER TABLE agents ADD COLUMN IF NOT EXISTS memory_config JSONB NOT NULL DEFAULT '{}';

-- Multi-tenant + preamble opt-out
ALTER TABLE agents ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT '';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS preamble BOOLEAN NOT NULL DEFAULT TRUE;

-- Indexes for multi-tenant queries
CREATE INDEX IF NOT EXISTS idx_agents_org ON agents (org_id, active);
CREATE INDEX IF NOT EXISTS idx_agents_trust ON agents (trust_tier, active);
