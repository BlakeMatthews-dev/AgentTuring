-- Stronghold 010: Denomination-locked coin wallets + coin config.
--
-- Renames chip_* tables to coin_* (chips → coins rebrand).
--
-- Core design: wallet denomination = access control.
--   - Copper: free daily faucet (expires at EOD)
--   - Silver: persistent, exchanged from copper at reduced rate — can only buy cheap models
--   - Gold/Platinum/Diamond: purchased — unlocks frontier models
-- Higher denominations can spend on anything at their tier or below.
-- Lower denominations CANNOT access higher-tier models.

-- 1. Rename tables: chip_* → coin_*
ALTER TABLE IF EXISTS chip_wallets RENAME TO coin_wallets;
ALTER TABLE IF EXISTS chip_ledger_entries RENAME TO coin_ledger_entries;

-- 2. Add denomination column (what tier of coins this wallet holds).
ALTER TABLE coin_wallets ADD COLUMN IF NOT EXISTS
    denomination TEXT NOT NULL DEFAULT 'copper';

-- 3. Replace the original unique constraint with denomination-based one.
--    Each user gets one wallet per denomination (copper, silver, gold, etc.).
ALTER TABLE coin_wallets DROP CONSTRAINT IF EXISTS chip_wallets_owner_type_owner_id_key;
ALTER TABLE coin_wallets DROP CONSTRAINT IF EXISTS chip_wallets_owner_cycle_key;
ALTER TABLE coin_wallets ADD CONSTRAINT coin_wallets_owner_denomination_key
    UNIQUE (owner_type, owner_id, denomination);

-- Rename indexes to match new table names.
ALTER INDEX IF EXISTS idx_chip_wallets_org RENAME TO idx_coin_wallets_org;
ALTER INDEX IF EXISTS idx_chip_wallets_active RENAME TO idx_coin_wallets_active;
ALTER INDEX IF EXISTS idx_chip_ledger_wallet_cycle RENAME TO idx_coin_ledger_wallet_cycle;
ALTER INDEX IF EXISTS idx_chip_ledger_request RENAME TO idx_coin_ledger_request;
ALTER INDEX IF EXISTS idx_chip_ledger_user RENAME TO idx_coin_ledger_user;

-- 4. Key-value config for coin system settings (super-admin adjustable).
CREATE TABLE IF NOT EXISTS coin_config (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Default exchange rate: free copper converts to silver at 40% face value.
-- Purchased coins bypass copper entirely and go straight to silver or higher.
INSERT INTO coin_config (key, value) VALUES ('banking_rate_pct', '40')
ON CONFLICT (key) DO NOTHING;
