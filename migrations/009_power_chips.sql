-- Stronghold 009: Poker-chip quota wallets and ledger
-- Budgets are enforced in normalized chip units, not raw tokens.

CREATE TABLE IF NOT EXISTS chip_wallets (
    id                  SERIAL PRIMARY KEY,
    owner_type          TEXT NOT NULL
                        CHECK (owner_type IN ('user', 'team', 'org')),
    owner_id            TEXT NOT NULL,
    org_id              TEXT NOT NULL DEFAULT '',
    team_id             TEXT NOT NULL DEFAULT '',
    label               TEXT NOT NULL DEFAULT '',
    billing_cycle       TEXT NOT NULL DEFAULT 'monthly'
                        CHECK (billing_cycle IN ('daily', 'monthly')),
    budget_microchips   BIGINT NOT NULL DEFAULT 0,
    hard_limit_microchips BIGINT NOT NULL DEFAULT 0,
    soft_limit_ratio    NUMERIC(5,4) NOT NULL DEFAULT 0.8000,
    overage_allowed     BOOLEAN NOT NULL DEFAULT FALSE,
    active              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_type, owner_id)
);

CREATE INDEX IF NOT EXISTS idx_chip_wallets_org ON chip_wallets (org_id, team_id, owner_type);
CREATE INDEX IF NOT EXISTS idx_chip_wallets_active ON chip_wallets (active, owner_type);

CREATE TABLE IF NOT EXISTS chip_ledger_entries (
    id                      SERIAL PRIMARY KEY,
    wallet_id               INTEGER NOT NULL REFERENCES chip_wallets(id) ON DELETE CASCADE,
    cycle_key               TEXT NOT NULL,
    entry_kind              TEXT NOT NULL DEFAULT 'debit'
                            CHECK (entry_kind IN ('debit', 'credit', 'adjustment')),
    delta_microchips        BIGINT NOT NULL,
    request_id              TEXT NOT NULL DEFAULT '',
    org_id                  TEXT NOT NULL DEFAULT '',
    team_id                 TEXT NOT NULL DEFAULT '',
    user_id                 TEXT NOT NULL DEFAULT '',
    model_used              TEXT NOT NULL DEFAULT '',
    provider                TEXT NOT NULL DEFAULT '',
    input_tokens            BIGINT NOT NULL DEFAULT 0,
    output_tokens           BIGINT NOT NULL DEFAULT 0,
    pricing_version         TEXT NOT NULL DEFAULT 'default-v1',
    base_rate_microchips    BIGINT NOT NULL DEFAULT 0,
    input_rate_microchips   BIGINT NOT NULL DEFAULT 0,
    output_rate_microchips  BIGINT NOT NULL DEFAULT 0,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chip_ledger_wallet_cycle
    ON chip_ledger_entries (wallet_id, cycle_key, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chip_ledger_request
    ON chip_ledger_entries (request_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_chip_ledger_user
    ON chip_ledger_entries (user_id, created_at DESC);

ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS charged_microchips BIGINT NOT NULL DEFAULT 0;
ALTER TABLE outcomes ADD COLUMN IF NOT EXISTS pricing_version TEXT NOT NULL DEFAULT 'default-v1';

CREATE INDEX IF NOT EXISTS idx_outcomes_pricing ON outcomes (pricing_version, created_at DESC);
