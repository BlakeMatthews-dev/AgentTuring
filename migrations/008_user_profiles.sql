-- Stronghold 008: User profile enhancements
-- Avatar (base64 data URL), bio, team bio for profile pages.
-- Password hash column (was missing from original users table).

ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_data TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS team_bio TEXT NOT NULL DEFAULT '';
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash TEXT NOT NULL DEFAULT '';
