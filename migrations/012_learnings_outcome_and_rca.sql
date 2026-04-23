-- Stronghold 012: structured RCA + outcome feedback counters on learnings.
--
-- Adds four columns backing the RCA taxonomy and the success/failure
-- feedback loop. All are nullable-friendly (text with '' default, integers
-- with 0 default) so existing rows continue to read cleanly.

ALTER TABLE learnings ADD COLUMN IF NOT EXISTS rca_category TEXT;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS rca_prevention TEXT NOT NULL DEFAULT '';
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS success_after_use INTEGER NOT NULL DEFAULT 0;
ALTER TABLE learnings ADD COLUMN IF NOT EXISTS failure_after_use INTEGER NOT NULL DEFAULT 0;
