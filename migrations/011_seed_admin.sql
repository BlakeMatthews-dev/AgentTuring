-- Stronghold 011: Ensure admin account exists on every boot.
-- Uses ON CONFLICT DO NOTHING so it never overwrites existing data.
-- Password must be set via the UI or API after first creation.

INSERT INTO users (email, display_name, org_id, team_id, roles, status)
VALUES (
    'blakematthews@agentstronghold.com',
    'Blake Matthews',
    'agent-stronghold',
    'engineering',
    '["admin", "org_admin", "team_admin", "user"]'::jsonb,
    'approved'
)
ON CONFLICT (email) DO NOTHING;
