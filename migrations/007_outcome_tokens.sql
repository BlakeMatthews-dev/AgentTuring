-- Stronghold 007: Add token usage columns to outcomes
-- Enables per-user/per-team/per-org token usage tracking in the Ledger.

ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS input_tokens BIGINT NOT NULL DEFAULT 0;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS output_tokens BIGINT NOT NULL DEFAULT 0;

-- Indexes for aggregation queries (by user, by team, by model)
CREATE INDEX IF NOT EXISTS idx_outcomes_user ON outcomes (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_team ON outcomes (team_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_outcomes_model ON outcomes (model_used, created_at DESC);
