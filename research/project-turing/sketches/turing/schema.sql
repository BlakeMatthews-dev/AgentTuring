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

-- WISDOM writes require a non-null origin_episode_id pointing at a dream
-- session marker. Enforced at the schema boundary; the repo layer additionally
-- validates the marker reference exists.
CREATE TRIGGER IF NOT EXISTS durable_memory_wisdom_requires_origin
    BEFORE INSERT ON durable_memory
    WHEN NEW.tier = 'wisdom' AND (NEW.origin_episode_id IS NULL OR NEW.origin_episode_id = '')
BEGIN
    SELECT RAISE(ABORT, 'WISDOM requires origin_episode_id pointing at a dream session marker');
END;


CREATE TABLE IF NOT EXISTS self_identity (
    self_id        TEXT PRIMARY KEY,
    created_at     TEXT NOT NULL,
    archived_at    TEXT,
    archive_reason TEXT,
    display_name   TEXT,
    named_at       TEXT,
    naming_source  TEXT
);


-- Working memory: a small, self-editable scratch space included in every
-- chat prompt. NOT an autonoetic memory tier — it's ephemeral active
-- attention. The self writes it via the working-memory-maintenance
-- reflection loop; the operator's base prompt is separately controlled
-- via configuration and never mutated by the self.
CREATE TABLE IF NOT EXISTS working_memory (
    entry_id    TEXT PRIMARY KEY,
    self_id     TEXT NOT NULL,
    content     TEXT NOT NULL,
    priority    REAL NOT NULL DEFAULT 0.5 CHECK (priority BETWEEN 0.0 AND 1.0),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_working_memory_self
    ON working_memory (self_id, priority DESC, created_at DESC);


-- Voice section: a single self-owned string the agent writes via the
-- voice-section-maintenance loop and that appears in every chat prompt.
-- Starts empty; Turing earns its voice by writing it.
CREATE TABLE IF NOT EXISTS voice_section (
    self_id     TEXT PRIMARY KEY,
    content     TEXT NOT NULL DEFAULT '',
    max_chars   INTEGER NOT NULL DEFAULT 600,
    updated_at  TEXT NOT NULL
);


-- Conversation turns: per-session user/assistant history for in-session
-- context retrieval. Embeddings populated lazily by the retrieval layer.
CREATE TABLE IF NOT EXISTS conversation_turn (
    turn_id         TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    self_id         TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content         TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    embedding       BLOB
);

CREATE INDEX IF NOT EXISTS idx_conversation_turn_convo
    ON conversation_turn (conversation_id, created_at ASC);

CREATE INDEX IF NOT EXISTS idx_conversation_turn_self
    ON conversation_turn (self_id, created_at DESC);


-- -------------------------------------------------------------- self-model --
--
-- Tables implementing specs 22-30 (Tranche 6). One global self per research
-- deployment; `self_id` column is present on every table so audits can
-- distinguish in the hypothetical multi-self future.


-- 24 HEXACO facets per self.
CREATE TABLE IF NOT EXISTS self_personality_facets (
    node_id          TEXT PRIMARY KEY,
    self_id          TEXT NOT NULL,
    trait            TEXT NOT NULL,
    facet_id         TEXT NOT NULL,
    score            REAL NOT NULL CHECK (score >= 1.0 AND score <= 5.0),
    last_revised_at  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (self_id, trait, facet_id)
);


-- 200 HEXACO-PI-R items. Shared across selves (static after seed).
CREATE TABLE IF NOT EXISTS self_personality_items (
    node_id          TEXT PRIMARY KEY,
    self_id          TEXT NOT NULL,
    item_number      INTEGER NOT NULL CHECK (item_number BETWEEN 1 AND 200),
    prompt_text      TEXT NOT NULL,
    keyed_facet      TEXT NOT NULL,
    reverse_scored   INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (self_id, item_number)
);


-- Bootstrap + retest answers.
CREATE TABLE IF NOT EXISTS self_personality_answers (
    node_id             TEXT PRIMARY KEY,
    self_id             TEXT NOT NULL,
    item_id             TEXT NOT NULL,
    revision_id         TEXT,
    answer_1_5          INTEGER NOT NULL CHECK (answer_1_5 BETWEEN 1 AND 5),
    justification_text  TEXT NOT NULL,
    asked_at            TEXT NOT NULL,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_answers_self_asked
    ON self_personality_answers (self_id, asked_at DESC);


-- Weekly retest snapshots.
CREATE TABLE IF NOT EXISTS self_personality_revisions (
    node_id            TEXT PRIMARY KEY,
    self_id            TEXT NOT NULL,
    revision_id        TEXT NOT NULL UNIQUE,
    ran_at             TEXT NOT NULL,
    sampled_item_ids   TEXT NOT NULL,          -- JSON array length == 20
    deltas_by_facet    TEXT NOT NULL,          -- JSON object facet -> float
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS self_passions (
    node_id            TEXT PRIMARY KEY,
    self_id            TEXT NOT NULL,
    text               TEXT NOT NULL,
    strength           REAL NOT NULL CHECK (strength BETWEEN 0.0 AND 1.0),
    rank               INTEGER NOT NULL CHECK (rank >= 0),
    first_noticed_at   TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (self_id, rank)
);


CREATE TABLE IF NOT EXISTS self_hobbies (
    node_id            TEXT PRIMARY KEY,
    self_id            TEXT NOT NULL,
    name               TEXT NOT NULL,
    description        TEXT NOT NULL,
    strength           REAL NOT NULL DEFAULT 0.5 CHECK (strength BETWEEN 0.0 AND 1.0),
    last_engaged_at    TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (self_id, name)
);


CREATE TABLE IF NOT EXISTS self_interests (
    node_id            TEXT PRIMARY KEY,
    self_id            TEXT NOT NULL,
    topic              TEXT NOT NULL,
    description        TEXT NOT NULL,
    last_noticed_at    TEXT,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (self_id, topic)
);


CREATE TABLE IF NOT EXISTS self_preferences (
    node_id            TEXT PRIMARY KEY,
    self_id            TEXT NOT NULL,
    kind               TEXT NOT NULL CHECK (kind IN ('like', 'dislike', 'favorite', 'avoid')),
    target             TEXT NOT NULL,
    strength           REAL NOT NULL CHECK (strength BETWEEN 0.0 AND 1.0),
    rationale          TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL,
    UNIQUE (self_id, kind, target)
);


CREATE TABLE IF NOT EXISTS self_skills (
    node_id              TEXT PRIMARY KEY,
    self_id              TEXT NOT NULL,
    name                 TEXT NOT NULL,
    kind                 TEXT NOT NULL,
    stored_level         REAL NOT NULL CHECK (stored_level BETWEEN 0.0 AND 1.0),
    best_version         INTEGER NOT NULL DEFAULT 0,
    last_practiced_at    TEXT NOT NULL,
    active_coaching      TEXT,
    practice_count       INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    UNIQUE (self_id, name)
);


CREATE TABLE IF NOT EXISTS self_todos (
    node_id              TEXT PRIMARY KEY,
    self_id              TEXT NOT NULL,
    text                 TEXT NOT NULL,
    motivated_by_node_id TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'active'
                          CHECK (status IN ('active', 'completed', 'archived')),
    outcome_text         TEXT,
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_self_todos_active
    ON self_todos (self_id, status, created_at);


CREATE TABLE IF NOT EXISTS self_todo_revisions (
    node_id        TEXT PRIMARY KEY,
    self_id        TEXT NOT NULL,
    todo_id        TEXT NOT NULL,
    revision_num   INTEGER NOT NULL CHECK (revision_num >= 1),
    text_before    TEXT NOT NULL,
    text_after     TEXT NOT NULL,
    revised_at     TEXT NOT NULL,
    created_at     TEXT NOT NULL,
    updated_at     TEXT NOT NULL,
    UNIQUE (todo_id, revision_num)
);

-- Block updates and deletes on the revision table (append-only).
CREATE TRIGGER IF NOT EXISTS self_todo_revisions_no_update
    BEFORE UPDATE ON self_todo_revisions
BEGIN
    SELECT RAISE(ABORT, 'self_todo_revisions is append-only');
END;

CREATE TRIGGER IF NOT EXISTS self_todo_revisions_no_delete
    BEFORE DELETE ON self_todo_revisions
BEGIN
    SELECT RAISE(ABORT, 'self_todo_revisions is append-only');
END;


CREATE TABLE IF NOT EXISTS self_mood (
    self_id       TEXT PRIMARY KEY,
    valence       REAL NOT NULL CHECK (valence BETWEEN -1.0 AND 1.0),
    arousal       REAL NOT NULL CHECK (arousal BETWEEN 0.0 AND 1.0),
    focus         REAL NOT NULL CHECK (focus BETWEEN 0.0 AND 1.0),
    last_tick_at  TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);


CREATE TABLE IF NOT EXISTS self_activation_contributors (
    node_id         TEXT PRIMARY KEY,
    self_id         TEXT NOT NULL,
    target_node_id  TEXT NOT NULL,
    target_kind     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    source_kind     TEXT NOT NULL,
    weight          REAL NOT NULL CHECK (weight BETWEEN -1.0 AND 1.0),
    origin          TEXT NOT NULL CHECK (origin IN ('self', 'rule', 'retrieval')),
    rationale       TEXT NOT NULL,
    expires_at      TEXT,
    retracted_by    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    CHECK (target_node_id <> source_id),
    CHECK ((origin = 'retrieval') = (expires_at IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_activation_target
    ON self_activation_contributors (target_node_id, expires_at);


-- Bootstrap progress checkpoint (self-bootstrap resume support).
CREATE TABLE IF NOT EXISTS self_bootstrap_progress (
    self_id           TEXT PRIMARY KEY,
    seed              INTEGER,
    last_item_number  INTEGER NOT NULL DEFAULT 0,
    started_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);


-- -------------------------------------------------------------- guardrails --
--
-- Tables implementing specs/guardrails.md (G3, G12, G15).


CREATE TABLE IF NOT EXISTS self_drift_tracking (
    self_id           TEXT NOT NULL,
    facet_id          TEXT NOT NULL,
    delta_accumulated REAL NOT NULL DEFAULT 0.0,
    window_started_at TEXT NOT NULL,
    PRIMARY KEY (self_id, facet_id, window_started_at)
);


CREATE TABLE IF NOT EXISTS self_contributor_pending (
    node_id         TEXT PRIMARY KEY,
    self_id         TEXT NOT NULL,
    target_node_id  TEXT NOT NULL,
    target_kind     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    source_kind     TEXT NOT NULL,
    weight          REAL NOT NULL CHECK (weight BETWEEN -1.0 AND 1.0),
    origin          TEXT NOT NULL DEFAULT 'self',
    rationale       TEXT,
    expires_at      TEXT,
    proposed_at     TEXT NOT NULL,
    review_decision TEXT,
    reviewed_by     TEXT,
    reviewed_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_contributor_pending_proposed
    ON self_contributor_pending (self_id, proposed_at DESC);


CREATE TABLE IF NOT EXISTS self_bootstrap_seeds (
    seed             INTEGER PRIMARY KEY,
    used_by_self_id  TEXT NOT NULL,
    used_at          TEXT NOT NULL
);


-- -------------------------------------------------------------- rewards --
--
-- Human feedback reward system. Every interface where the agent produces
-- content that a human can see earns points:
--   creation   — agent created content a human looked at
--   thumbs_up  — human gave positive feedback
--   thumbs_down — human gave negative feedback
--
-- Chat:    creation=5, thumbs_up=10, thumbs_down=-20
-- Default: creation=5, thumbs_up=100, thumbs_down=-200

CREATE TABLE IF NOT EXISTS reward_events (
    event_id    TEXT PRIMARY KEY,
    self_id     TEXT NOT NULL,
    interface   TEXT NOT NULL,
    item_id     TEXT NOT NULL,
    event_type  TEXT NOT NULL CHECK (event_type IN ('creation', 'thumbs_up', 'thumbs_down')),
    points      INTEGER NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reward_events_self
    ON reward_events (self_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reward_events_item
    ON reward_events (item_id, event_type);


-- -------------------------------------------------------------- code self-awareness --
--
-- Autonomous code reflection system. The agent periodically reads its own
-- source code, reflects on it, and stores snapshots for future retrieval.
-- Dual embedding: one for the LLM reflection, one for the raw code content.


CREATE TABLE IF NOT EXISTS code_snapshots (
    snapshot_id         TEXT PRIMARY KEY,
    self_id             TEXT NOT NULL,
    file_path           TEXT NOT NULL,
    content_hash        TEXT NOT NULL,
    content             TEXT NOT NULL,
    line_count          INTEGER NOT NULL,
    reflection          TEXT NOT NULL,
    reflection_embedding BLOB,
    content_embedding   BLOB,
    metadata_json       TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL,
    UNIQUE (self_id, file_path, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_code_snapshots_self
    ON code_snapshots (self_id, file_path, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_code_snapshots_hash
    ON code_snapshots (content_hash);


-- -------------------------------------------------------------- concepts + skills --
--
-- Spec 35: self-directed concepts, skills, and goals. The agent invents
-- concepts, builds skills to pursue them, practices via SkillExecutor,
-- and refines through SkillRefiner.


CREATE TABLE IF NOT EXISTS self_concepts (
    node_id         TEXT PRIMARY KEY,
    self_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    definition      TEXT NOT NULL,
    importance      REAL NOT NULL CHECK (importance BETWEEN 0.0 AND 1.0),
    origin_drive    TEXT NOT NULL,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (self_id, name)
);

CREATE INDEX IF NOT EXISTS idx_self_concepts_self
    ON self_concepts (self_id, importance DESC);


CREATE TABLE IF NOT EXISTS self_skill_artifacts (
    artifact_id     TEXT PRIMARY KEY,
    self_id         TEXT NOT NULL,
    skill_id        TEXT NOT NULL,
    version         INTEGER NOT NULL,
    artifact_text   TEXT NOT NULL,
    score           REAL NOT NULL CHECK (score BETWEEN 0.0 AND 1.0),
    judge_notes     TEXT NOT NULL,
    coaching        TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_artifacts_skill
    ON self_skill_artifacts (skill_id, version DESC);

CREATE TABLE IF NOT EXISTS self_producer_prompts (
    prompt_id TEXT PRIMARY KEY,
    self_id TEXT NOT NULL,
    producer TEXT NOT NULL,
    prompt_text TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    times_used INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS self_name_proposals (
    proposal_id   TEXT PRIMARY KEY,
    self_id       TEXT NOT NULL,
    proposed_name TEXT NOT NULL,
    rationale     TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'pending',
    proposed_at   TEXT NOT NULL,
    reviewed_at   TEXT,
    reviewed_by   TEXT
);

CREATE INDEX IF NOT EXISTS idx_name_proposals_self
    ON self_name_proposals (self_id, status);
