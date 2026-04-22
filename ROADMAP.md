# Stronghold Roadmap

**Last Updated:** 2026-04-16
**Status:** Active development — core security, routing, classification, memory, agent runtime implemented. See progress dashboard at bottom.

---

## Release Timeline

```
v0.1  Skeleton + Tests (all red)          ← Phase 0-1
v0.2  Router + Classifier (tested)        ← Phase 2
v0.3  Security layer (Warden + Sentinel)  ← Phase 3 + Security Gate
v0.4  Memory systems                      ← Phase 4
v0.5  Data layer + Auth                   ← Phase 5
v0.6  Agent runtime                       ← Phase 6
v0.7  Agent roster + Tools                ← Phase 7 + Security Gate
v0.8  Import/Export + API                 ← Phase 8
v0.9  Deployment + K8s                    ← Phase 9
v1.0  Production release                  ← Phase 10 + Security Gate

v1.1  Closed-loop feedback (phase 1-3)
v1.2  Tournaments + Forge + advanced memory
v1.3  Multi-tenant + adaptive tools
v1.4  Review queue + Session Trust Floor + trust ledger  ← CFM-1, CFM-2
v1.5  Recipe + variant evolution + APM                   ← CFM-3, CFM-4
v1.6  Intel dashboard + structured evolution timeline    ← CFM-5
v1.7  Trust economy surface + currency exchange
v2.0  Full personalized intelligence
```

---

## Phase 0: Scaffold

**Goal:** Every file exists. Nothing runs. The skeleton is the architecture made concrete.

### 0.1 Repository Setup
- [ ] pyproject.toml (ruff, mypy, pytest, bandit config)
- [ ] .pre-commit-config.yaml
- [ ] .github/workflows/ci.yml (pytest + ruff + mypy + bandit)
- [ ] .gitignore
- [ ] LICENSE (Apache 2.0)
- [ ] Dockerfile (Python 3.12-slim)
- [ ] docker-compose.yml (stronghold + postgres + langfuse + litellm)

### 0.2 PostgreSQL Schema
- [ ] migrations/001_initial.sql
  - agents table (identity, config, trust_tier, active)
  - learnings table (category, trigger_keys, learning, agent_id, user_id, scope, hit_count, status, embedding vector)
  - sessions table (session_id, user_id, seq, role, content, timestamp)
  - quota_usage table (provider, cycle_key, input_tokens, output_tokens, total_tokens, request_count)
  - audit_log table (timestamp, boundary, user_id, agent_id, tool_name, verdict, violations, trace_id)
  - episodic table (memory_id, agent_id, user_id, scope, tier, weight, content, embedding vector, source, created_at, last_accessed_at, deleted)
  - knowledge table (chunk_id, agent_id, content, embedding vector, source, created_at)
  - tournaments table (intent, agent_a, agent_b, winner, score_a, score_b, judge, trace_id_a, trace_id_b, created_at)
  - permissions table (role, tools jsonb, agents jsonb, config jsonb)
- [ ] CREATE EXTENSION vector;
- [ ] CREATE EXTENSION pg_trgm;

### 0.3 File Skeleton
Every file created with module docstring, imports placeholder, and empty class/function signatures. Zero implementation. `mypy --strict` must pass on the skeleton (all functions return `...` or `raise NotImplementedError`).

```
stronghold/
├── __init__.py
├── py.typed
│
├── protocols/
│   ├── __init__.py
│   ├── router.py              # ModelRouter
│   ├── classifier.py          # IntentClassifier
│   ├── memory.py              # LearningStore, LearningExtractor, EpisodicStore
│   ├── tools.py               # ToolExecutor, ToolRegistry
│   ├── auth.py                # AuthProvider
│   ├── skills.py              # SkillLoader, SkillForge, SkillMarketplace
│   ├── quota.py               # QuotaTracker
│   ├── tracing.py             # TracingBackend, Trace, Span
│   ├── llm.py                 # LLMClient (ModelProxy)
│   ├── prompts.py             # PromptManager
│   └── data.py                # DataStore
│
├── types/
│   ├── __init__.py
│   ├── intent.py              # Intent, TaskType, Complexity, Priority
│   ├── model.py               # ModelCandidate, ModelSelection, ProviderConfig, ModelConfig
│   ├── auth.py                # AuthContext, Role, Permission
│   ├── skill.py               # SkillDefinition, SkillMetadata, ForgeRequest
│   ├── tool.py                # ToolCall, ToolResult, ToolDefinition
│   ├── memory.py              # Learning, EpisodicMemory, MemoryTier, MemoryScope, WeightBounds
│   ├── session.py             # SessionMessage, SessionConfig
│   ├── agent.py               # AgentIdentity, AgentTask, ExecutionMode, ReasoningResult
│   ├── security.py            # WardenVerdict, SentinelVerdict, Violation, AuditEntry, TrustTier
│   ├── config.py              # StrongholdConfig (Pydantic)
│   └── errors.py              # Error hierarchy
│
├── classifier/
│   ├── __init__.py
│   ├── keyword.py             # Strong indicators + config keywords + negative signals
│   ├── llm_fallback.py        # LLM-based classification for ambiguous queries
│   ├── multi_intent.py        # Compound request detection
│   ├── complexity.py          # Complexity + priority estimation
│   └── engine.py              # ClassifierEngine: orchestrates the pipeline
│
├── router/
│   ├── __init__.py
│   ├── scorer.py              # quality^(qw*p) / cost^cw
│   ├── scarcity.py            # 1/ln(remaining_daily_tokens)
│   ├── speed.py               # Task-type-aware speed bonuses
│   ├── filter.py              # Modality, tier, quota, status filters
│   └── selector.py            # RouterEngine: filter → score → rank → fallback
│
├── security/
│   ├── __init__.py
│   ├── warden/
│   │   ├── __init__.py
│   │   ├── detector.py        # Regex + heuristic layers
│   │   ├── patterns.py        # Known attack patterns (ported from bouncer.py)
│   │   └── sanitizer.py       # Strip/escape detected threats
│   ├── sentinel/
│   │   ├── __init__.py
│   │   ├── validator.py       # Schema validation + repair
│   │   ├── policy.py          # Permission enforcement (config-driven)
│   │   ├── token_optimizer.py # Compress bloated tool results
│   │   ├── pii_filter.py      # Outbound data loss prevention
│   │   └── audit.py           # Persistent audit log
│   └── gate.py                # Input processing: sanitize → improve → clarify
│
├── memory/
│   ├── __init__.py
│   ├── learnings/
│   │   ├── __init__.py
│   │   ├── store.py           # PostgreSQL CRUD, scoped by agent_id + user_id
│   │   ├── extractor.py       # PURE FUNCTION: fail→succeed pattern detection
│   │   ├── promoter.py        # Auto-promotion after N hits + episodic bridge
│   │   └── embeddings.py      # Embedding retrieval (pgvector)
│   ├── episodic/
│   │   ├── __init__.py
│   │   ├── tiers.py           # 7 tiers, weight bounds, clamp/reinforce/decay
│   │   ├── store.py           # PostgreSQL + pgvector CRUD
│   │   └── retrieval.py       # Trigram similarity * weight, scope-filtered
│   └── scopes.py              # Scope enum + query builder (global/team/user/agent/session)
│
├── sessions/
│   ├── __init__.py
│   └── store.py               # PostgreSQL session CRUD
│
├── quota/
│   ├── __init__.py
│   ├── tracker.py             # Usage recording + cycle management
│   └── billing.py             # Cycle key generation, daily budget normalization
│
├── agents/
│   ├── __init__.py
│   ├── base.py                # Agent class, handle(), AgentContext
│   ├── identity.py            # AgentIdentity parsing from agent.yaml
│   ├── cache.py               # Prompt LRU cache
│   ├── context_builder.py     # Assemble prompt: soul + tools + learnings + episodic
│   ├── streaming.py           # SSE streaming + tool-loop-to-SSE conversion
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── direct.py          # Single LLM call
│   │   ├── react.py           # LLM → tool loop → repeat
│   │   ├── plan_execute.py    # Plan → subtasks → execute → review
│   │   └── delegate.py        # Classify → route to sub-agent
│   ├── registry.py            # Agent CRUD (PostgreSQL)
│   ├── importer.py            # GitAgent dir → PostgreSQL + pgvector
│   ├── exporter.py            # Running agent → GitAgent dir
│   ├── tournament.py          # Head-to-head scoring + promotion (v1.1, stub for now)
│   └── intents.py             # Intent registry + routing table
│
├── tools/
│   ├── __init__.py
│   ├── registry.py            # Aggregate MCP tools from LiteLLM + prompt library skills
│   └── legacy.py              # Wrapper for Conductor tools during migration
│
├── skills/
│   ├── __init__.py
│   ├── parser.py              # YAML frontmatter + markdown body
│   ├── loader.py              # Load SKILL.md from filesystem
│   ├── forge.py               # Forge tool (generate SKILL.md, no iteration yet)
│   ├── marketplace.py         # Search + install from URLs (renamed from skill_hub)
│   └── registry.py            # PostgreSQL-backed skill versioning
│
├── tracing/
│   ├── __init__.py
│   ├── arize.py               # Arize Enterprise implementation
│   ├── prompts.py             # PostgreSQL PromptManager implementation
│   ├── noop.py                # No-op for tests
│   └── trace.py               # Backend-agnostic RequestTrace + SpanContext
│
├── config/
│   ├── __init__.py
│   ├── loader.py              # YAML → validated Pydantic StrongholdConfig
│   ├── defaults.py            # Sensible defaults
│   └── env.py                 # Environment variable resolution
│
├── events.py                  # Async EventBus for proactive triggers
├── container.py               # DI container: wires protocols → implementations
│
└── api/
    ├── __init__.py
    ├── app.py                 # FastAPI factory
    ├── routes/
    │   ├── __init__.py
    │   ├── chat.py            # POST /v1/chat/completions
    │   ├── models.py          # GET /v1/models
    │   ├── status.py          # GET /status/*, /health
    │   ├── admin.py           # POST /admin/*, learnings CRUD, config reload
    │   ├── skills.py          # Forge + marketplace + skill CRUD
    │   ├── agents.py          # Agent CRUD, import/export
    │   ├── sessions.py        # Session CRUD
    │   ├── conductor.py       # Orchestrator admin (memory, tasks, progress)
    │   ├── dashboard.py       # HTML serving (existing dashboards)
    │   └── traces.py          # Trace proxy (Arize)
    └── middleware/
        ├── __init__.py
        ├── auth.py            # Extract AuthContext from request
        └── tracing.py         # Create trace per request
```

### 0.4 Agent Definitions (GitAgent format)
- [ ] agents/conduit/ (agent.yaml + SOUL.md)
- [ ] agents/ranger/ (agent.yaml + SOUL.md + RULES.md)
- [ ] agents/artificer/ (agent.yaml + SOUL.md + RULES.md + sub-agents/)
- [ ] agents/scribe/ (agent.yaml + SOUL.md)
- [ ] agents/warden-at-arms/ (agent.yaml + SOUL.md + RULES.md)

### 0.5 dev-tools-mcp Server (separate repo)
- [ ] Agent-StrongHold/dev-tools-mcp repository created
- [ ] Python tools: run_pytest, run_ruff_check, run_ruff_format, run_mypy, run_bandit
- [ ] Structured ToolResult returns (exit_code, passed, findings[])
- [ ] Dockerfile with Python + all linters installed
- [ ] MCP server (FastMCP or raw)

**Checkpoint:** `mypy --strict stronghold/` passes. `ruff check` passes. All files exist. Nothing runs.

---

## Phase 1: Types + Protocols + Auth

**Goal:** The contract is defined. Test factories exist. Fakes exist for every protocol. Auth works (Keycloak + Entra ID are day 1).

### 1.1 Error Hierarchy
- [ ] StrongholdError base
- [ ] RoutingError (QuotaReserveError, NoModelsError)
- [ ] ClassificationError
- [ ] AuthError (TokenExpiredError, PermissionDeniedError)
- [ ] ToolError, SecurityError (InjectionError, TrustViolationError)
- [ ] ConfigError, SkillError

### 1.2 Value Types
- [ ] Intent (task_type, complexity, priority, min_tier, max_tier, preferred_strengths, classified_by, keyword_score, user_text)
- [ ] ModelConfig, ProviderConfig, ModelCandidate, ModelSelection
- [ ] AuthContext (user_id, username, roles frozenset, tenant_id, auth_method, has_role(), can_use_tool())
- [ ] Learning, EpisodicMemory, MemoryTier enum, MemoryScope enum, WeightBounds
- [ ] ToolCall, ToolResult, ToolDefinition
- [ ] SkillDefinition, SkillMetadata
- [ ] AgentIdentity, AgentTask, ExecutionMode enum, ReasoningResult
- [ ] WardenVerdict, SentinelVerdict, Violation, AuditEntry, TrustTier enum
- [ ] StrongholdConfig (Pydantic BaseModel, validated)

### 1.3 Protocols
- [ ] All 12 protocol interfaces with docstrings and type annotations

### 1.4 Auth Providers (Day 1 Priority)
- [ ] Keycloak AuthProvider — JWT validation, JWKS caching with lock, realm_access.roles extraction (port from auth.py)
- [ ] Entra ID AuthProvider — JWT validation, JWKS from Microsoft endpoint, app roles extraction
- [ ] Static key AuthProvider — backward compat, maps to system admin context
- [ ] OpenWebUI header AuthProvider — X-OpenWebUI-User-* header extraction
- [ ] PermissionTable — config-driven role → tool mapping (replaces hardcoded _USER_ROLES)
- [ ] permissions.yaml — role definitions with tool and agent access

### 1.5 Test Infrastructure
- [ ] tests/conftest.py — shared fixtures, FakeLLMClient, FakePromptManager, FakeTracingBackend
- [ ] tests/factories.py — builder functions for every type (build_intent(), build_model_config(), build_auth_context(), etc.)
- [ ] tests/fakes.py — noop/fake implementations of every protocol
- [ ] tests/auth/test_keycloak.py — JWT validation, JWKS caching, role extraction
- [ ] tests/auth/test_entra_id.py — Entra ID JWT, app roles mapping
- [ ] tests/auth/test_static_key.py — static key → system admin context
- [ ] tests/auth/test_permissions.py — config-driven role → tool mapping

**Checkpoint:** `mypy --strict` passes. Auth providers tested. All types importable.

---

## Phase 2: Router + Classifier

**Goal:** The two pure-logic engines work and are exhaustively tested.

### 2.1 Test Stubs (RED)
- [ ] tests/routing/test_scoring_properties.py — mathematical invariants
- [ ] tests/routing/test_scarcity_curve.py — monotonicity, budget sensitivity
- [ ] tests/routing/test_speed_bonus.py — task-type weights, capping
- [ ] tests/routing/test_tier_filtering.py — min/max enforcement
- [ ] tests/routing/test_modality_filtering.py — image_gen/embedding/text
- [ ] tests/routing/test_quota_reserve.py — reserve block, critical override, paygo
- [ ] tests/routing/test_fallback.py — all filtered → highest quality
- [ ] tests/routing/test_strength_matching.py — 1.15x/0.90x/1.0x
- [ ] tests/classification/test_keyword_matching.py — strong indicators, word boundaries
- [ ] tests/classification/test_negative_signals.py — suppression
- [ ] tests/classification/test_complexity.py — word count + regex → simple/moderate/complex
- [ ] tests/classification/test_priority.py — urgency keywords
- [ ] tests/classification/test_multi_intent.py — compound splitting
- [ ] tests/classification/test_smart_home_tier.py — short→small, long→medium
- [ ] tests/classification/test_llm_fallback.py — mocked LLM classification

### 2.2 Implementation
- [ ] router/scarcity.py — `compute_effective_cost()` (port from router.py:229-261)
- [ ] router/speed.py — speed weight lookup + norm_speed calculation
- [ ] router/filter.py — modality, tier, status, quota filters
- [ ] router/scorer.py — `quality^(qw*p) / cost^cw` with speed bonus + strength matching
- [ ] router/selector.py — RouterEngine: filter → score → sort → fallback
- [ ] classifier/keyword.py — strong indicators + config keywords + negative signals (port from classifier.py)
- [ ] classifier/complexity.py — word count + regex heuristics + priority inference
- [ ] classifier/multi_intent.py — conjunction splitting + per-part classification
- [ ] classifier/llm_fallback.py — async LLM call via LLMClient protocol
- [ ] classifier/engine.py — ClassifierEngine: keyword → LLM fallback pipeline

### 2.3 Verification
- [ ] All routing tests green
- [ ] All classification tests green
- [ ] Property-based tests for scoring (score always positive, monotonic in quality, monotonic in cost)
- [ ] `pytest --tb=short -q` — all pass
- [ ] `mypy --strict` — clean
- [ ] `ruff check && ruff format --check` — clean
- [ ] `bandit -r stronghold/router stronghold/classifier -ll` — clean

**Checkpoint:** ~200 tests green. The two hardest algorithms are proven correct.

---

## Phase 3: Security Layer

**Goal:** Warden + Sentinel + Gate operational. Every trust boundary guarded.

### 3.1 Test Stubs (RED)
- [ ] tests/security/test_prompt_injection.py — 10+ regex patterns
- [ ] tests/security/test_role_hijacking.py
- [ ] tests/security/test_system_prompt_extraction.py
- [ ] tests/security/test_tool_result_scanning.py — indirect injection in search/email/HA results
- [ ] tests/security/test_warden_isolation.py — Warden module has no tool/file/LLM imports
- [ ] tests/security/test_schema_validation.py — validate against MCP inputSchema
- [ ] tests/security/test_schema_repair.py — fuzzy match, coerce, defaults
- [ ] tests/security/test_tool_permissions.py — config-driven role → tool mapping
- [ ] tests/security/test_token_optimization.py — K8s metadata strip, search truncation, JSON compact
- [ ] tests/security/test_pii_filter.py — API keys, internal IPs, system prompt leakage
- [ ] tests/security/test_audit_log.py — every boundary crossing logged
- [ ] tests/security/test_gate_sanitize.py — zero-width chars, unicode normalization
- [ ] tests/security/test_gate_improve.py — query improvement + clarifying questions (mocked LLM)

### 3.2 Implementation
- [ ] security/warden/patterns.py — port regex patterns from bouncer.py:76-168
- [ ] security/warden/detector.py — 3-layer: regex → heuristic → LLM classify
- [ ] security/warden/sanitizer.py — strip/escape injection fragments
- [ ] security/sentinel/validator.py — JSON Schema validation against MCP inputSchema
- [ ] security/sentinel/validator.py — schema repair (fuzzy match, type coercion, defaults)
- [ ] security/sentinel/policy.py — PermissionTable from config YAML, check(roles, tool_name)
- [ ] security/sentinel/token_optimizer.py — result compression by tool type
- [ ] security/sentinel/pii_filter.py — regex for API keys, IPs, prompt content
- [ ] security/sentinel/audit.py — PostgreSQL audit_log writes
- [ ] security/gate.py — sanitize + query improve (LLM call for persistent mode)

### 3.3 Verification
- [ ] All security tests green
- [ ] Warden isolation verified (inspect module imports)
- [ ] Schema repair tested with real LLM hallucination patterns
- [ ] Audit log populated on every test that crosses a boundary

### SECURITY REVIEW GATE
- [ ] Map every concern from conductor_security.md §17 to a passing test
- [ ] Verify: cross-user memory leakage impossible (scoped queries)
- [ ] Verify: cookie auth bypass impossible (protocol-based auth only)
- [ ] Verify: tool args validated before dispatch
- [ ] Verify: tool results scanned before LLM re-injection
- [ ] Verify: no hardcoded credentials in any source file
- [ ] `bandit -r stronghold/ -ll` — zero findings

**Checkpoint:** Security layer complete. ~100 additional tests green.

---

## Phase 4: Memory

**Goal:** All memory systems operational with scope isolation.

### 4.1 Test Stubs (RED)
- [ ] tests/memory/test_learning_storage.py — CRUD, dedup (>50% key overlap)
- [ ] tests/memory/test_learning_scoping.py — agent_id + user_id isolation
- [ ] tests/memory/test_correction_extraction.py — fail→succeed detection (pure function)
- [ ] tests/memory/test_positive_extraction.py — first-try success patterns
- [ ] tests/memory/test_auto_promotion.py — hit_count ≥ threshold → promoted
- [ ] tests/memory/test_episodic_tiers.py — weight bounds, regret ≥ 0.6, wisdom ≥ 0.9
- [ ] tests/memory/test_episodic_retrieval.py — trigram similarity * weight, scope filtered
- [ ] tests/memory/test_scope_isolation.py — global/team/user/agent/session boundaries
- [ ] tests/memory/test_weight_mechanics.py — reinforce/decay clamped to bounds

### 4.2 Implementation
- [ ] memory/scopes.py — MemoryScope enum, scope query builder
- [ ] memory/learnings/store.py — PostgreSQL CRUD, dedup, scope filtering
- [ ] memory/learnings/extractor.py — pure function: tool_history → list[Learning]
- [ ] memory/learnings/promoter.py — auto-promote logic + episodic bridge
- [ ] memory/learnings/embeddings.py — pgvector similarity search
- [ ] memory/episodic/tiers.py — MemoryTier enum, WeightBounds, clamp/reinforce/decay
- [ ] memory/episodic/store.py — PostgreSQL + pgvector CRUD
- [ ] memory/episodic/retrieval.py — scope-filtered similarity * weight query

### 4.3 Verification
- [ ] All memory tests green
- [ ] Scope isolation: agent A's learnings never appear in agent B's retrieval
- [ ] Scope isolation: user A's memories never appear in user B's retrieval
- [ ] Regret tier: weight cannot drop below 0.6 under any operation

**Checkpoint:** Memory systems complete. ~80 additional tests green.

---

## Phase 5: Data Layer + Auth

**Goal:** Sessions, quota, config, and auth all operational.

### 5.1 Test Stubs (RED)
- [ ] tests/sessions/test_crud.py — store/retrieve/delete, max message limit
- [ ] tests/sessions/test_ttl.py — expiry pruning
- [ ] tests/sessions/test_isolation.py — user_id:session_id prevents cross-user
- [ ] tests/config/test_validation.py — Pydantic validates, rejects bad values
- [ ] tests/config/test_env_override.py — env vars override YAML
- [ ] tests/auth/test_keycloak.py — JWT validation, JWKS caching, role extraction
- [ ] tests/auth/test_entra_id.py — Entra ID JWT, app roles mapping
- [ ] tests/auth/test_static_key.py — static key → system admin context
- [ ] tests/auth/test_permissions.py — config-driven role → tool mapping

### 5.2 Implementation
- [ ] sessions/store.py — PostgreSQL session CRUD (port from sessions.py)
- [ ] quota/tracker.py — PostgreSQL usage recording (port from quota.py)
- [ ] quota/billing.py — cycle key generation, daily budget normalization
- [ ] config/loader.py — Pydantic StrongholdConfig from YAML
- [ ] config/defaults.py — sensible defaults for every field
- [ ] config/env.py — environment variable resolution
- [ ] api/middleware/auth.py — AuthProvider dispatch (Keycloak, Entra ID, static key)
- [ ] Keycloak AuthProvider (port JWT validation from auth.py)
- [ ] Entra ID AuthProvider
- [ ] Static key AuthProvider
- [ ] PermissionTable (config-driven)

### 5.3 Verification
- [ ] All session/config/auth tests green
- [ ] Config loads and validates from YAML
- [ ] Auth providers tested with mock JWTs

**Checkpoint:** Full data layer + auth operational. ~60 additional tests green.

---

## Phase 6: Agent Runtime

**Goal:** A single agent can receive a message, build context, call LLM, dispatch tools, and respond.

### 6.1 Test Stubs (RED)
- [ ] tests/agents/test_full_pipeline.py — request→classify→route→LLM→respond (FakeLLM)
- [ ] tests/agents/test_tool_loop.py — multi-round: LLM→tool_call→execute→LLM→text
- [ ] tests/agents/test_prompt_assembly.py — order: soul + tools + promoted + learnings + episodic
- [ ] tests/agents/test_streaming.py — tool loop non-streaming → SSE conversion
- [ ] tests/agents/test_session_injection.py — session_id → history prepend
- [ ] tests/agents/test_model_fallback.py — primary 5xx → next-best candidate
- [ ] tests/agents/test_learning_feedback.py — post-loop extraction + mark_used + auto_promote
- [ ] tests/agents/test_execution_modes.py — best_effort vs persistent vs supervised
- [ ] tests/agents/test_delegation.py — Conduit routes to correct specialist

### 6.2 Implementation
- [ ] agents/base.py — Agent class with handle()
- [ ] agents/identity.py — AgentIdentity parsing from agent.yaml
- [ ] agents/cache.py — PromptCache (LRU, evict-on-full)
- [ ] agents/context_builder.py — assemble prompt from soul + tools + memories
- [ ] agents/streaming.py — SSE streaming + tool-loop-to-SSE conversion
- [ ] agents/strategies/direct.py — single LLM call (~15 lines)
- [ ] agents/strategies/react.py — tool loop (~50 lines, port from main.py:486-609)
- [ ] agents/strategies/plan_execute.py — plan → subtasks → sub-agents → review (~70 lines)
- [ ] agents/strategies/delegate.py — classify → route to sub-agent (~20 lines)
- [ ] agents/registry.py — PostgreSQL agent CRUD
- [ ] agents/intents.py — intent registry + static routing table
- [ ] events.py — async EventBus

### 6.3 Verification
- [ ] Full pipeline test: request in, response out, with FakeLLM
- [ ] Tool loop: 3-round tool dispatch with mocked tools
- [ ] Streaming: non-streaming tool loop converted to valid SSE
- [ ] Delegation: Conduit classifies and delegates correctly

**Checkpoint:** One agent handles a request end-to-end. ~80 additional tests green.

---

## Phase 7: Agent Roster + Tools

**Goal:** All v1.0 agents operational. MCP tools connected. Sentinel guardrail registered.

### 7.1 Agent Definitions
- [ ] Conduit agent (delegate strategy, static routing table)
- [ ] Ranger agent (react strategy, web_search + database_query tools)
- [ ] Artificer agent (plan_execute strategy, file_ops + shell + test_runner)
  - [ ] artificer-planner sub-agent (direct strategy)
  - [ ] artificer-coder sub-agent (react strategy)
  - [ ] artificer-reviewer sub-agent (custom strategy — runs pytest/ruff/mypy/bandit)
  - [ ] artificer-debugger sub-agent (react strategy)
- [ ] Scribe agent (plan_execute strategy, simple — no committee yet)
- [ ] Warden-at-Arms agent (react strategy, ha_control + api_call)

### 7.2 Tool Integration
- [ ] tools/registry.py — aggregate tools from LiteLLM MCP gateway
- [ ] Sentinel registered as LiteLLM guardrail (pre-call + post-call)
- [ ] tools/legacy.py — wrapper for any Conductor tools not yet on MCP

### 7.3 Test Stubs (RED)
- [ ] tests/agents/test_conduit_routing.py — each task_type routes to correct agent
- [ ] tests/agents/test_ranger_untrusted.py — Warden scans all Ranger output
- [ ] tests/agents/test_artificer_loop.py — plan → code → review → fix cycle
- [ ] tests/tools/test_registry.py — MCP tool aggregation + group filtering
- [ ] tests/tools/test_sentinel_guardrail.py — schema repair via LiteLLM hook

### 7.4 Verification
- [ ] Each agent handles its designated task type correctly
- [ ] Sentinel repairs hallucinated tool args in at least 3 test cases
- [ ] Warden catches indirect injection in Ranger search results

### SECURITY REVIEW GATE
- [ ] Each agent's tool list is enforced (can't call tools outside its config)
- [ ] Untrusted Ranger output is Warden-scanned before injection into other agents
- [ ] Artificer's reviewer actually runs all 5 quality checks
- [ ] Trust tiers enforced on skill loading

**Checkpoint:** Full agent roster operational. ~60 additional tests green.

---

## Phase 8: Import/Export + API

**Goal:** GitAgent import works. FastAPI serves traffic. The system is usable.

### 8.1 Implementation
- [ ] agents/importer.py — GitAgent dir → PostgreSQL + pgvector
- [ ] agents/exporter.py — running agent → GitAgent dir
- [ ] .github/actions/langfuse-sync — GitHub Action for prompt sync
- [ ] api/app.py — FastAPI factory with DI container
- [ ] api/routes/chat.py — POST /v1/chat/completions (delegates to Agent.handle())
- [ ] api/routes/models.py — GET /v1/models
- [ ] api/routes/status.py — GET /status/*, /health
- [ ] api/routes/admin.py — POST /admin/*, learnings CRUD
- [ ] api/routes/skills.py — skill CRUD + forge
- [ ] api/routes/agents.py — agent CRUD + import/export
- [ ] api/routes/sessions.py — session CRUD
- [ ] api/middleware/auth.py — AuthContext extraction
- [ ] api/middleware/tracing.py — trace-per-request

### 8.2 Test Stubs (RED)
- [ ] tests/integration/test_http_lifecycle.py — full HTTP → pipeline → FakeLLM → HTTP
- [ ] tests/integration/test_openai_compat.py — response format matches OpenAI spec
- [ ] tests/agents/test_import_export.py — import → use → export → re-import round-trip
- [ ] tests/skills/test_parsing.py — YAML frontmatter + markdown body
- [ ] tests/skills/test_marketplace.py — search + install + uninstall (mocked HTTP)

### 8.3 Verification
- [ ] Can import a GitAgent repo and route a request to it
- [ ] /v1/chat/completions returns OpenAI-compatible response
- [ ] /health returns 200

**Checkpoint:** System is usable via HTTP. ~40 additional tests green.

---

## Phase 9: Deployment

**Goal:** Deploys to K8s and serves production traffic.

### 9.1 Implementation
- [ ] Dockerfile (production)
- [ ] Helm chart (stronghold/)
  - [ ] Deployment (Stronghold API)
  - [ ] StatefulSet (PostgreSQL + pgvector)
  - [ ] ConfigMap (stronghold config)
  - [ ] Secret (credentials)
  - [ ] Service + Ingress
  - [ ] values.yaml (all configurable)
- [ ] K8s secret manager integration
- [ ] Arize Phoenix deployment config (or Arize Enterprise reference)
- [ ] LiteLLM deployment config (or reference existing)

### 9.2 Verification
- [ ] `helm install stronghold ./helm/stronghold` succeeds
- [ ] Pod comes up healthy
- [ ] /health returns 200 from K8s service
- [ ] /v1/chat/completions routes through LiteLLM successfully

**Checkpoint:** Running in K8s.

---

## Phase 10: Polish + Ship

**Goal:** Production-ready v1.0 release.

### 10.1 Quality
- [ ] Test coverage audit — identify gaps, add missing edge cases
- [ ] Performance test: routing < 1ms for 100 models, classification < 5ms
- [ ] Load test: concurrent requests don't deadlock or leak connections
- [ ] Error message review: every user-facing error is helpful

### 10.2 Documentation
- [ ] README.md — project overview, quickstart (5 minutes to running)
- [ ] docs/architecture.md — link to ARCHITECTURE.md
- [ ] docs/quickstart.md — Docker Compose up and running
- [ ] docs/agents.md — how to create and import agents
- [ ] docs/security.md — Warden/Sentinel/Gate/trust tiers
- [ ] docs/configuration.md — config reference
- [ ] docs/api.md — endpoint reference

### 10.3 Final Items
- [ ] ARCHITECTURE.md final review (does code match design?)
- [ ] CHANGELOG.md
- [ ] CONTRIBUTING.md
- [ ] Apache 2.0 LICENSE file
- [ ] .pre-commit-config.yaml finalized
- [ ] CI/CD pipeline finalized

### SECURITY REVIEW GATE
- [ ] Full `bandit -r stronghold/` — zero findings
- [ ] Full conductor_security.md §17 traceability — every concern has a test
- [ ] No hardcoded credentials anywhere (`grep -rn 'sk-\|password\|secret' stronghold/`)
- [ ] JWT audience verification enabled in all auth providers
- [ ] OWASP top 10 review against API routes

### 10.4 Release
- [ ] Tag v1.0.0
- [ ] Push to Agent-StrongHold/stronghold
- [ ] Docker image published
- [ ] Helm chart published

**Checkpoint:** v1.0 shipped.

---

## v1.1: Closed-Loop Feedback + Tournament Hardening

**Theme:** The feedback primitives exist (Auditor/Mason cycle, learning extraction, tournament scaffolding). v1.1 wires them into production and makes them self-tuning.

- [ ] Latency tracking → rolling P50/P99 per model → adjust speed scores
- [ ] Tool success rate per model per task_type → adjust quality scores
- [ ] Retrospective intent labels (compare classified task_type vs actual tools used) → adjust keyword weights
- [ ] Tournament system wired to production routing (currently in-memory only, not connected to live traffic)
- [ ] Dynamic intent creation on agent import
- [ ] Automated trust tier promotion gates (currently manual via `update_trust_tier` — no AI+admin auto-promotion exists yet)

## v1.2: Forge Iteration + Advanced Memory + RASO Phase 1

**Theme:** Forge gains a real test→iterate loop (currently generate→scan→save only). Memory decay ships. RASO inner loop formalized.

- [ ] Forge agent iteration loop: generate → scan → validate → **test with sample inputs** → iterate (max N rounds). Currently missing: test execution step and retry loop.
- [ ] Learning A/B evaluation (random withhold + measure outcome delta)
- [ ] Memory decay function (unused learnings lose weight over time — mechanism exists in episodic tiers, not yet in learnings)
- [ ] Scribe committee (critic/advocate/editor debate)
- [ ] Contradiction detection in learnings
- [ ] RASO Phase 1: Formalize the Auditor→Mason→extract→store→track cycle as the inner feedback loop. Measure interaction effects between agents (not just individual pass/fail).

## v1.3: Multi-Tenant + RASO Phase 2

**Theme:** Enterprise multi-tenancy ships. RASO meta-agent wraps the builders graph.

- [ ] K8s namespace-per-tenant isolation
- [ ] Per-tenant prompt isolation (tenant_id scoping in prompts table)
- [ ] Namespace-scoped secrets (K8s secret manager per tenant)
- [ ] Agent marketplace (registry for importing/sharing agents across tenants)
- [ ] Custom agent containers (Dockerfile + A2A endpoint)
- [ ] RASO Phase 2: Meta-agent that can modify graph structure (add/remove/reorder nodes, adjust strategy selection, tune scoring weights). Learns parameter sensitivity — which knobs to turn by inches, which to turn by leaps.

## v1.4: Review Queue + Session Trust Floor + Trust Ledger

**Theme:** Governance becomes a first-class runtime subsystem. Every promotion, every tier crossing, every potentially-poisoning input is a queued decision with a reviewer.

### Review Queue Engine (CFM-1 — foundation)
- [ ] `src/stronghold/review/` beside `orchestrator/` — reviews are HITL-often; latency, failure modes, and scaling differ from execution `WorkItem`s
- [ ] Typed `ReviewItem` kinds: `forge_skill`, `forge_node_kind`, `recipe_variant_promote`, `apm_change`, `user_tier_promote`, `stf_ratchet_decision`, `learning_promote`, `agent_import`
- [ ] Priority calculator = `f(stakes_impact, −origin_stf, plan_tier_sla, age_bonus, blast_radius, backlog_pressure)`
- [ ] Reviewer classes: `human_only` / `ai_allowed` / `ai_only`. Auditor agent consumes AI-eligible items; maps to existing Herald→QM→Archie→Mason→Auditor→Gatekeeper→Master-at-Arms pipeline
- [ ] `/dashboard/reviews.html` inbox; reactor-driven enqueue on forge/promote/change events; SLA + escalation + auto-expire
- [ ] Shared with orchestrator only via `types/priority.py` and `types/review.py`

### Session Trust Floor (CFM-2)
- [ ] `src/stronghold/trust/` — `reducer.py`, `signals.py`, `ledger.py`, `thresholds.py`, `policy.py`, `exchange.py`
- [ ] STF = `min()` over all contributors (agent, recipe, node, tool, input source, user trust score tier, Warden safety confidence tier, …)
- [ ] Monotonically non-increasing within a session — redaction/compaction/summarization do not heal. New session required to reset
- [ ] Forks and sub-flows inherit parent STF
- [ ] `TrustSignal { source, tier, confidence, rationale, trace_ref }` contract; unknown sources default to `☠️ Skull`
- [ ] Warden verdict gains `confidence ∈ [0,1]` — low confidence floors input's effective contribution
- [ ] HITL surface: pending-input dialog (accept-and-ratchet or reject), blocked-action dialog, passive trust indicator with descent timeline

### Trust Ledger
- [ ] User trust accrual: `Δ = plan_multiplier × copper_value × session_T_score` on each completed action
- [ ] `plan_multiplier`: free=0, paid=1, team_plan=2, team_admin=5, org_admin=10, super_admin=100
- [ ] `session_T_score`: T1=+2, T2=+1, T3=0, ☠️Skull=−10 (clamps to 0 for team_admin+)
- [ ] Exponential tier thresholds — narrow T2 band, wide T1/T3, unbounded T0/Skull; origin centered slightly positive into T2 for new paid users
- [ ] Copper = `tokens_used × token_value`; conversion from other currencies via `trust/exchange.py`
- [ ] Thresholds hot-reloadable via `trust/thresholds.yaml`
- [ ] Dispatch refuses execution when `STF < recipe.required_tier` — emits event to review engine, doesn't raise

### Reactor Enhancements (land with CFM-1)
- [ ] Density-aware jitter for shared firing times — `max_jitter_secs = min(ceiling, base + k × log2(density))`
- [ ] Coalescence / timer-slack — `leeway: "±Nmin"` lets reactor snap low-density triggers together for batch efficiency
- [ ] Extend `TriggerSpec` jitter to `TIME` mode (not just `INTERVAL`); add `leeway` field
- [ ] Log bucketing decisions in trigger audit

## v1.5: Recipe + Variant Evolution + APM

**Theme:** Agent structure becomes a declarative spec. Tournaments have a real selection backbone. Agent personality is a first-class, reviewable, round-trippable artifact.

### Recipe + Variant Engine (CFM-3)
- [ ] `src/stronghold/types/recipe.py` — `RecipeSpec` with `FlowSpec` body. Pure data, YAML-serializable, no Python callables
- [ ] Single envelope for all agent shapes — strategy agents are degenerate graphs (one node, no edges); graph/workflow agents share the same envelope
- [ ] `src/stronghold/evaluation/` — spec CRUD, Thompson sampling over `Beta(successes, failures)` posteriors per `(recipe_id, variant_id, intent)`, outcome recording, promotion logic, validator (reachability + schema + no-orphan edges + no-undeclared-state-refs)
- [ ] `src/stronghold/execution/` — `graph_runner.py` + `node_handlers.py` + `state.py`. Spec/engine separation means the same spec can be run by multiple executors (today's tool-loop, tomorrow's streaming, a replay engine for RCA)
- [ ] `NodeSpec.kind` is an OPEN registry. Built-in kinds reserved: `reason`, `tool`, `branch`, `recipe`, `collect` (ship at T0). Unknown kinds default to `☠️ Skull` — execution gated, specs harmless
- [ ] Per-kind `param_schema` required at registration; `declared_side_effects` enforced by Sentinel (kind claiming `["network"]` can't open filesystem)
- [ ] `effective_tier = min(recipe.tier, min(node.kind.tier for node in flow.nodes))`
- [ ] Variants carry spec diffs, not runtime objects; Thompson sampling operates on spec hashes
- [ ] Variant promotion → review queue (not immediate) with policy-driven auto-approve thresholds
- [ ] Round-trips through GitAgent export/import as YAML
- [ ] `migrations/00XX_recipes.sql` — `recipes`, `variants`, `variant_outcomes`, `node_kinds`

### APM — Agent Personality Manifest (CFM-4)
- [ ] `src/stronghold/types/apm.py` — Pydantic model with seven sections: `identity`, `core_values`, `communication_style`, `expertise`, `boundaries`, `tools_and_methods`, `memory_anchors`
- [ ] Every agent resolves exactly one APM at load (merged from trust-tier baseline if none declared)
- [ ] `PUT /v1/stronghold/agents/{id}/apm` — Warden-scanned (APM is an agent prompt; this is a high-trust boundary)
- [ ] Changes enqueue review — `human_only` by default; policy-driven downgrade to `ai_allowed` later
- [ ] Rendered into system prompt by every strategy via `prompts/apm_renderer.py` — strategy-agnostic wiring
- [ ] Included in GitAgent export bundle; re-hydrates on import
- [ ] Audit entry per change: actor, old_hash, new_hash, trace_id
- [ ] `/dashboard/agents/{id}/apm` — diff preview and "request review" flow

## v1.6: Intel Dashboard + Structured Evolution Timeline

**Theme:** Memory, traces, and mutations become an inspectable, annotable audit trail.

### Intel Dashboard (CFM-5)
- [ ] `src/stronghold/intel/` — `traces.py` + `rca.py` + `evolution.py`
- [ ] Four tabs: **Traces**, **RCA**, **Evolution**, **Reviews**
- [ ] **Traces** — paginated Langfuse browse, filter by agent/intent/verdict, click into span tree, inline score (1–5 + tags + note)
- [ ] `POST /v1/stronghold/traces/{id}/score` — dual-writes to Langfuse + outcomes store; reviewer earns trust points
- [ ] **RCA** — auto-generated post-mortems from failed `WorkItem`s. Reactor-triggered `rca.generate_rca` on `work_failed`; candidates feed learnings extractor at low weight until reinforced
- [ ] **Evolution** — chronological `EvolutionEvent` stream across memory, recipes, skills, learnings, node-kind mutations. Structural diffs (RecipeSpec + FlowSpec + node graph changes) — not just prompt text
- [ ] **Reviews** — mirrors Review Queue inbox with the same filters

## v1.7: Trust Economy Surface + Currency Exchange

**Theme:** Trust ledger surfaces in the UX. Soft barriers do the right thing by plan tier. Gamification makes clean behavior visible.

- [ ] **Top-tier gamification** — profile badges at T0/T0+/T0++, profile-load effects (fireworks, aurora), differential AI greetings keyed off rank (T0: `"Welcome back, {name}. Ready when you are."` → T0++: `"Welcome back, Supreme Divine Ruler of the Universe. How can we be of service?"`). Skull: guarded greeting + small warning sigil
- [ ] **Skull soft-barrier engine** — plan-aware depth response:
  - Paid: progressive action rate-limits; auto-block past threshold
  - Team plan: escalating admin notifications (digest → alert → real-time); progressive tool lockdown
  - Team/org/super admin: skull T-score clamps to 0 (no accrual, no penalty) — security testing remains legitimate
- [ ] **Currency exchange layer** — copper as canonical unit; other currencies (credits, compute-minutes) plug in via `trust/exchange.py` with configurable rates
- [ ] **Reviewer trust accrual** — thoughtful approvals earn trust points; rubber-stamp and stale decisions flagged
- [ ] **Trust timeline widget** — per-session descent visualization with cause annotations

## v2.0: Personalized Intelligence

- [ ] User satisfaction signals (thumbs up/down, rephrase detection)
- [ ] Confidence-calibrated routing (classifier uncertainty → model tier)
- [ ] Few-shot embedding clusters (replace keyword lists with example sentences)
- [ ] Memory impact scoring (injected memory → outcome → weight adjustment)
- [ ] Cross-user generalization (individual learnings → validated system facts)
- [ ] Ebbinghaus forgetting curve for episodic memory
- [ ] Stronghold native UI (replace Arize + LiteLLM dashboards, add prompt editor)
- [ ] RASO Phase 3: The guide learns how to pick routes — meta-optimization of the optimization process itself

---

## Progress Dashboard

Updated 2026-04-16:

```
Phase 0: Scaffold           [x] ██████████  done   (208 source files, pre-commit, CI)
Phase 1: Types + Protocols  [x] ██████████  done   (20 protocols, 32+ Protocol classes, all value types, error hierarchy)
Phase 2: Router + Classifier [x] ██████████  done   (scorer, scarcity, speed, filter, keyword, engine)
Phase 3: Security Layer     [x] ██████████  done   (4-layer Warden, Sentinel pipeline, Gate, 203 attack payloads, 30+ vulns fixed in Apr 13 audit)
Phase 4: Memory             [~] ████████░░  80%    (learnings store+extractor+promoter, 7-tier episodic, 5 scopes — embeddings retrieval stub)
Phase 5: Data + Auth        [~] ██████░░░░  60%    (Keycloak+Entra+static key auth, config loader, sessions — PG quota partial)
Phase 6: Agent Runtime      [~] ████████░░  80%    (base.py, react, plan_execute, delegate, direct, context_builder, streaming — execution modes partial)
Phase 7: Roster + Tools     [~] ██████░░░░  60%    (Artificer+Mason+Frank strategies, agent routes, MCP registry — Scribe/Ranger/WaA definitions partial)
Phase 8: Import/Export + API [~] ████████░░  80%    (17 route files, chat+admin+status+skills+agents+mcp — import/export partial)
Phase 9: Deployment         [~] ██████░░░░  60%    (Dockerfile, docker-compose, Helm chart skeleton, K8s ADRs 001-031)
Phase 10: Polish + Ship     [~] ████░░░░░░  40%    (550+ tests, 95% coverage, ruff+mypy clean — docs and final audit pending)

Tests: 3,000+ green, 95% coverage
Security gates: 1/3 passed (Phase 3 — Phases 7 and 10 pending)
```
