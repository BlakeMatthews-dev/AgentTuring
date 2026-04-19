-- Project Turing — durable memory schema (SQLite sketch)
--
-- Two tables:
--   episodic_memory — non-durable tiers (OBSERVATION, HYPOTHESIS, OPINION, LESSON).
--                     Soft-delete allowed.
--   durable_memory  — durable tiers (REGRET, ACCOMPLISHMENT, WISDOM, AFFIRMATION).
--                     Append-only. No `deleted` column. DELETE blocked by trigger.
--
-- Plus self_identity for the stable self_id.

CREATE TABLE IF NOT EXISTS episodic_memory (
    memory_id              TEXT PRIMARY KEY,
    self_id                TEXT NOT NULL,
    tier                   TEXT NOT NULL CHECK (tier IN (
        'observation', 'hypothesis', 'opinion', 'lesson'
    )),
    source                 TEXT NOT NULL CHECK (source IN (
        'i_did', 'i_was_told', 'i_imagined'
    )),
    content                TEXT NOT NULL,
    weight                 REAL NOT NULL,
    affect                 REAL NOT NULL CHECK (affect BETWEEN -1.0 AND 1.0),
    confidence_at_creation REAL NOT NULL CHECK (confidence_at_creation BETWEEN 0.0 AND 1.0),
    surprise_delta         REAL NOT NULL CHECK (surprise_delta BETWEEN 0.0 AND 1.0),
    intent_at_time         TEXT NOT NULL DEFAULT '',
    supersedes             TEXT,
    superseded_by          TEXT,
    origin_episode_id      TEXT,
    immutable              INTEGER NOT NULL DEFAULT 0,
    reinforcement_count    INTEGER NOT NULL DEFAULT 0,
    contradiction_count    INTEGER NOT NULL DEFAULT 0,
    deleted                INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL,
    last_accessed_at       TEXT NOT NULL,
    context                TEXT
);

CREATE INDEX IF NOT EXISTS idx_episodic_self_tier
    ON episodic_memory (self_id, tier, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_episodic_supersedes
    ON episodic_memory (supersedes);


CREATE TABLE IF NOT EXISTS durable_memory (
    memory_id              TEXT PRIMARY KEY,
    self_id                TEXT NOT NULL,
    tier                   TEXT NOT NULL CHECK (tier IN (
        'regret', 'accomplishment', 'wisdom', 'affirmation'
    )),
    source                 TEXT NOT NULL CHECK (source = 'i_did'),
    content                TEXT NOT NULL,
    weight                 REAL NOT NULL,
    affect                 REAL NOT NULL CHECK (affect BETWEEN -1.0 AND 1.0),
    confidence_at_creation REAL NOT NULL CHECK (confidence_at_creation BETWEEN 0.0 AND 1.0),
    surprise_delta         REAL NOT NULL CHECK (surprise_delta BETWEEN 0.0 AND 1.0),
    intent_at_time         TEXT NOT NULL,
    supersedes             TEXT,
    superseded_by          TEXT,
    origin_episode_id      TEXT,
    immutable              INTEGER NOT NULL DEFAULT 1,
    reinforcement_count    INTEGER NOT NULL DEFAULT 0,
    contradiction_count    INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL,
    last_accessed_at       TEXT NOT NULL,
    context                TEXT
    -- explicitly: no `deleted` column
);

CREATE INDEX IF NOT EXISTS idx_durable_self_tier
    ON durable_memory (self_id, tier, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_durable_supersedes
    ON durable_memory (supersedes);

CREATE INDEX IF NOT EXISTS idx_durable_superseded_by
    ON durable_memory (superseded_by);

-- Block all DELETE against durable_memory.
CREATE TRIGGER IF NOT EXISTS durable_memory_block_delete
    BEFORE DELETE ON durable_memory
BEGIN
    SELECT RAISE(ABORT, 'durable_memory is append-only');
END;

-- Block ACCOMPLISHMENT writes without non-empty intent_at_time.
CREATE TRIGGER IF NOT EXISTS durable_memory_accomplishment_requires_intent
    BEFORE INSERT ON durable_memory
    WHEN NEW.tier = 'accomplishment' AND (NEW.intent_at_time IS NULL OR NEW.intent_at_time = '')
BEGIN
    SELECT RAISE(ABORT, 'ACCOMPLISHMENT requires non-empty intent_at_time');
END;

-- Block WISDOM writes. Tier is reserved until the dreaming spec lands.
CREATE TRIGGER IF NOT EXISTS durable_memory_wisdom_deferred
    BEFORE INSERT ON durable_memory
    WHEN NEW.tier = 'wisdom'
BEGIN
    SELECT RAISE(ABORT, 'wisdom writes deferred; see specs/wisdom-write-path.md');
END;


CREATE TABLE IF NOT EXISTS self_identity (
    self_id        TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    archived_at    TEXT,
    archive_reason TEXT
);
