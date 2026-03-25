-- Stronghold 005: Marketplace delist tracking
-- Persists fix failure counts so delisted URLs survive restarts.

CREATE TABLE IF NOT EXISTS marketplace_delisted (
    url             TEXT PRIMARY KEY,
    failure_count   INTEGER NOT NULL DEFAULT 1,
    delisted_at     TIMESTAMPTZ DEFAULT NOW()
);
