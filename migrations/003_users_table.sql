-- Stronghold 003: Users table with approval workflow
-- Users must be approved before they can log in.
-- Approval can be granted per-user, per-team, or per-org.

CREATE TABLE IF NOT EXISTS users (
    id              SERIAL PRIMARY KEY,
    email           TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL DEFAULT '',
    org_id          TEXT NOT NULL DEFAULT '',
    team_id         TEXT NOT NULL DEFAULT '',
    roles           JSONB NOT NULL DEFAULT '["user"]',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'approved', 'rejected', 'disabled')),
    approved_by     TEXT NOT NULL DEFAULT '',
    approved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_status ON users (status);
CREATE INDEX IF NOT EXISTS idx_users_org ON users (org_id, team_id);
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);

-- Seed admin user (pre-approved, org_admin + team_admin)
INSERT INTO users (email, display_name, org_id, team_id, roles, status, approved_by, approved_at)
VALUES (
    'blakematthews@agentstronghold.com',
    'Blake Matthews',
    'agent-stronghold',
    'engineering',
    '["admin", "org_admin", "team_admin", "user"]',
    'approved',
    'system',
    NOW()
) ON CONFLICT (email) DO UPDATE SET
    roles = '["admin", "org_admin", "team_admin", "user"]'::jsonb,
    updated_at = NOW();

-- Seed team admin user (pre-approved, team_admin only)
INSERT INTO users (email, display_name, org_id, team_id, roles, status, approved_by, approved_at)
VALUES (
    'anthony@agentstronghold.com',
    'Anthony',
    'agent-stronghold',
    'engineering',
    '["team_admin", "user"]',
    'approved',
    'system',
    NOW()
) ON CONFLICT (email) DO UPDATE SET
    roles = '["team_admin", "user"]'::jsonb,
    updated_at = NOW();
