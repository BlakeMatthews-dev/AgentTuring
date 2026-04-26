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
    weight                 DOUBLE PRECISION NOT NULL,
    affect                 DOUBLE PRECISION NOT NULL CHECK (affect BETWEEN -1.0 AND 1.0),
    confidence_at_creation DOUBLE PRECISION NOT NULL CHECK (confidence_at_creation BETWEEN 0.0 AND 1.0),
    surprise_delta         DOUBLE PRECISION NOT NULL CHECK (surprise_delta BETWEEN 0.0 AND 1.0),
    intent_at_time         TEXT NOT NULL DEFAULT '',
    supersedes             TEXT,
    superseded_by          TEXT,
    origin_episode_id      TEXT,
    immutable              BOOLEAN NOT NULL DEFAULT FALSE,
    reinforcement_count    INTEGER NOT NULL DEFAULT 0,
    contradiction_count    INTEGER NOT NULL DEFAULT 0,
    deleted                BOOLEAN NOT NULL DEFAULT FALSE,
    created_at             TIMESTAMPTZ NOT NULL,
    last_accessed_at       TIMESTAMPTZ NOT NULL,
    context                JSONB
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
    weight                 DOUBLE PRECISION NOT NULL,
    affect                 DOUBLE PRECISION NOT NULL CHECK (affect BETWEEN -1.0 AND 1.0),
    confidence_at_creation DOUBLE PRECISION NOT NULL CHECK (confidence_at_creation BETWEEN 0.0 AND 1.0),
    surprise_delta         DOUBLE PRECISION NOT NULL CHECK (surprise_delta BETWEEN 0.0 AND 1.0),
    intent_at_time         TEXT NOT NULL,
    supersedes             TEXT,
    superseded_by          TEXT,
    origin_episode_id      TEXT,
    immutable              BOOLEAN NOT NULL DEFAULT TRUE,
    reinforcement_count    INTEGER NOT NULL DEFAULT 0,
    contradiction_count    INTEGER NOT NULL DEFAULT 0,
    created_at             TIMESTAMPTZ NOT NULL,
    last_accessed_at       TIMESTAMPTZ NOT NULL,
    context                JSONB
);

CREATE INDEX IF NOT EXISTS idx_durable_self_tier
    ON durable_memory (self_id, tier, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_durable_supersedes
    ON durable_memory (supersedes);

CREATE INDEX IF NOT EXISTS idx_durable_superseded_by
    ON durable_memory (superseded_by);


CREATE OR REPLACE FUNCTION block_durable_delete() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'durable_memory is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS durable_memory_block_delete ON durable_memory;
CREATE TRIGGER durable_memory_block_delete
    BEFORE DELETE ON durable_memory
    FOR EACH ROW EXECUTE FUNCTION block_durable_delete();


CREATE OR REPLACE FUNCTION check_accomplishment_intent() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.tier = 'accomplishment' AND (NEW.intent_at_time IS NULL OR NEW.intent_at_time = '') THEN
        RAISE EXCEPTION 'ACCOMPLISHMENT requires non-empty intent_at_time';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS durable_memory_accomplishment_requires_intent ON durable_memory;
CREATE TRIGGER durable_memory_accomplishment_requires_intent
    BEFORE INSERT ON durable_memory
    FOR EACH ROW EXECUTE FUNCTION check_accomplishment_intent();


CREATE OR REPLACE FUNCTION check_wisdom_origin() RETURNS TRIGGER AS $$
BEGIN
    IF NEW.tier = 'wisdom' AND (NEW.origin_episode_id IS NULL OR NEW.origin_episode_id = '') THEN
        RAISE EXCEPTION 'WISDOM requires origin_episode_id pointing at a dream session marker';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS durable_memory_wisdom_requires_origin ON durable_memory;
CREATE TRIGGER durable_memory_wisdom_requires_origin
    BEFORE INSERT ON durable_memory
    FOR EACH ROW EXECUTE FUNCTION check_wisdom_origin();


-- Voice section: a single self-owned string the agent writes via the
-- voice-section-maintenance loop and that appears in every chat prompt.
CREATE TABLE IF NOT EXISTS voice_section (
    self_id     TEXT PRIMARY KEY,
    content     TEXT NOT NULL DEFAULT '',
    max_chars   INTEGER NOT NULL DEFAULT 600,
    updated_at  TIMESTAMPTZ NOT NULL
);


-- Conversation turns: per-session user/assistant history for in-session
-- context retrieval.
CREATE TABLE IF NOT EXISTS conversation_turn (
    turn_id         TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    self_id         TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL,
    embedding       BYTEA
);

CREATE INDEX IF NOT EXISTS idx_conversation_turn_convo
    ON conversation_turn (conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_conversation_turn_self
    ON conversation_turn (self_id, created_at DESC);
