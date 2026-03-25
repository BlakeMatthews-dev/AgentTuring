-- Stronghold Initial Schema
-- PostgreSQL 17 + pgvector + pg_trgm

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ============================================================================
-- Agents
-- ============================================================================

CREATE TABLE agents (
    name            TEXT PRIMARY KEY,
    version         TEXT NOT NULL DEFAULT '0.1.0',
    description     TEXT NOT NULL DEFAULT '',
    config          JSONB NOT NULL DEFAULT '{}',
    trust_tier      TEXT NOT NULL DEFAULT 't1',
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Prompt Library
-- ============================================================================

CREATE TABLE prompts (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    version         INTEGER NOT NULL,
    label           TEXT,
    content         TEXT NOT NULL,
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_by      TEXT NOT NULL DEFAULT 'system',
    UNIQUE(name, version),
    UNIQUE(name, label)
);

CREATE INDEX idx_prompts_name ON prompts (name);
CREATE INDEX idx_prompts_label ON prompts (name, label);

-- ============================================================================
-- Learnings (Self-Improving Memory)
-- ============================================================================

CREATE TABLE learnings (
    id              SERIAL PRIMARY KEY,
    category        TEXT NOT NULL DEFAULT 'general',
    trigger_keys    TEXT NOT NULL,
    learning        TEXT NOT NULL,
    tool_name       TEXT NOT NULL DEFAULT '',
    source_query    TEXT NOT NULL DEFAULT '',
    agent_id        TEXT,
    user_id         TEXT,
    scope           TEXT NOT NULL DEFAULT 'agent',
    hit_count       INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'active',
    promoted_at     TIMESTAMPTZ,
    embedding       vector(768),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used       TIMESTAMPTZ,
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_learnings_agent ON learnings (agent_id, active);
CREATE INDEX idx_learnings_status ON learnings (status, active);
CREATE INDEX idx_learnings_scope ON learnings (scope, active);

-- ============================================================================
-- Sessions (Conversation History)
-- ============================================================================

CREATE TABLE sessions (
    session_id      TEXT NOT NULL,
    user_id         TEXT NOT NULL DEFAULT '',
    seq             INTEGER NOT NULL,
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, seq)
);

CREATE INDEX idx_sessions_ts ON sessions (session_id, timestamp);
CREATE INDEX idx_sessions_user ON sessions (user_id, session_id);

-- ============================================================================
-- Quota Usage (Token Tracking)
-- ============================================================================

CREATE TABLE quota_usage (
    provider        TEXT NOT NULL,
    cycle_key       TEXT NOT NULL,
    input_tokens    BIGINT NOT NULL DEFAULT 0,
    output_tokens   BIGINT NOT NULL DEFAULT 0,
    total_tokens    BIGINT NOT NULL DEFAULT 0,
    request_count   INTEGER NOT NULL DEFAULT 0,
    last_updated    TIMESTAMPTZ,
    PRIMARY KEY (provider, cycle_key)
);

-- ============================================================================
-- Audit Log (Sentinel)
-- ============================================================================

CREATE TABLE audit_log (
    id              BIGSERIAL PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    boundary        TEXT NOT NULL,
    user_id         TEXT NOT NULL DEFAULT '',
    agent_id        TEXT NOT NULL DEFAULT '',
    tool_name       TEXT,
    verdict         TEXT NOT NULL,
    violations      JSONB NOT NULL DEFAULT '[]',
    trace_id        TEXT NOT NULL DEFAULT '',
    request_id      TEXT NOT NULL DEFAULT '',
    detail          TEXT NOT NULL DEFAULT ''
);

CREATE INDEX idx_audit_ts ON audit_log (timestamp DESC);
CREATE INDEX idx_audit_user ON audit_log (user_id, timestamp DESC);
CREATE INDEX idx_audit_agent ON audit_log (agent_id, timestamp DESC);
CREATE INDEX idx_audit_verdict ON audit_log (verdict, timestamp DESC);

-- ============================================================================
-- Episodic Memory (7-Tier Weighted)
-- ============================================================================

CREATE TABLE episodic (
    memory_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id            TEXT,
    user_id             TEXT,
    team                TEXT,
    scope               TEXT NOT NULL DEFAULT 'agent',
    tier                TEXT NOT NULL DEFAULT 'observation',
    weight              DOUBLE PRECISION NOT NULL DEFAULT 0.3,
    content             TEXT NOT NULL,
    embedding           vector(768),
    source              TEXT NOT NULL DEFAULT '',
    context             JSONB NOT NULL DEFAULT '{}',
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted             BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_episodic_scope ON episodic (scope, deleted);
CREATE INDEX idx_episodic_agent ON episodic (agent_id, scope, deleted);
CREATE INDEX idx_episodic_user ON episodic (user_id, scope, deleted);
CREATE INDEX idx_episodic_tier ON episodic (tier, weight DESC);
CREATE INDEX idx_episodic_trgm ON episodic USING gin (content gin_trgm_ops);

-- ============================================================================
-- Knowledge (RAG Chunks)
-- ============================================================================

CREATE TABLE knowledge (
    chunk_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        TEXT,
    content         TEXT NOT NULL,
    embedding       vector(768),
    source          TEXT NOT NULL DEFAULT '',
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_knowledge_agent ON knowledge (agent_id);

-- ============================================================================
-- Tournaments (Agent Head-to-Head)
-- ============================================================================

CREATE TABLE tournaments (
    id              BIGSERIAL PRIMARY KEY,
    intent          TEXT NOT NULL,
    agent_a         TEXT NOT NULL,
    agent_b         TEXT NOT NULL,
    winner          TEXT,
    score_a         DOUBLE PRECISION,
    score_b         DOUBLE PRECISION,
    judge           TEXT NOT NULL DEFAULT 'llm',
    trace_id_a      TEXT NOT NULL DEFAULT '',
    trace_id_b      TEXT NOT NULL DEFAULT '',
    prompt_hash     TEXT NOT NULL DEFAULT '',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_tournaments_intent ON tournaments (intent, created_at DESC);

-- ============================================================================
-- Permissions (RBAC Config)
-- ============================================================================

CREATE TABLE permissions (
    role            TEXT PRIMARY KEY,
    tools           JSONB NOT NULL DEFAULT '[]',
    agents          JSONB NOT NULL DEFAULT '[]',
    config          JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Seed default roles
INSERT INTO permissions (role, tools, agents, config) VALUES
    ('admin', '["*"]', '["*"]', '{}'),
    ('engineer', '["web_search", "file_ops", "shell", "git", "test_runner"]', '["artificer", "ranger", "scribe"]', '{}'),
    ('operator', '["ha_control", "ha_list_devices", "ha_notify", "k8s_get_pods", "k8s_get_logs", "k8s_scale"]', '["warden-at-arms", "ranger"]', '{"require_confirmation": ["k8s_scale"]}'),
    ('viewer', '["web_search"]', '["ranger", "scribe"]', '{}')
ON CONFLICT (role) DO NOTHING;
