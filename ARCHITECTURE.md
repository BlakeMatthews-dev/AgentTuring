# Stronghold Architecture

**Version:** 0.1.0-draft
**Date:** 2026-03-25
**License:** Apache 2.0
**Status:** Design — no implementation yet

---

## 1. What Stronghold Is

Stronghold is an open-source, self-hosted agent governance platform. It wraps any LLM in a secure execution harness with intelligent routing, self-improving memory, autonomous operation, and zero-trust security.

It is extracted from a private homelab AI gateway (Project mAIstro / Conductor) but redesigned from first principles as a clean, enterprise-ready platform.

**Core principle: All input is untrusted. All tool output is untrusted. Trust is earned, not assumed.**

### 1.1 What Makes It Different

Eight innovations preserved from the Conductor codebase, each validated against the patterns in "Agentic Design Patterns" (Gulli, 2026):

1. **Scarcity-based model routing** — `score = quality^(qw*p) / (1/ln(remaining_tokens))^cw`. Cost rises smoothly as provider tokens are consumed. No cliffs, no manual rebalancing. (ADP §8.2: "Optimization is architecture")
2. **Self-improving memory** — learns from tool-call failures (fail→succeed extraction), auto-promotes corrections after N hits, bridges to permanent episodic memory. (ADP §6.2: "Learning means updating prompts, not retraining")
3. **7-tier episodic memory** — regrets (weight ≥0.6) are structurally unforgettable. Wisdom (≥0.9) survives across versions. (ADP §6.1: "Bad memory retrieval is worse than no memory")
4. **Defense-in-depth security** — Warden (threat detection) + Sentinel (policy enforcement) at every trust boundary. (ADP §8.4: "No single guardrail is enough")
5. **Skill Forge** — AI creates its own tools, validates via security scanner, output starts at ☠️ trust tier. (ADP §5.5: "Tool use enables environmental interaction")
6. **Multi-intent parallel dispatch** — compound requests are split by the Conduit and dispatched to specialist agents in parallel. Each agent gets a scoped subtask, not the full compound request. The Conduit aggregates results. (ADP §5.2: "Routing is both intelligence and policy", §5.3: "Parallelization")
7. **Task-type-aware speed bonuses** — voice gets speed weight, code gets quality weight. (ADP §8.2: "Resource-aware optimization")
8. **Tournament-based agent evolution** — agents compete head-to-head, winners earn routes, losers get demoted. Dynamic intent creation on agent import. (ADP §6.2: "Bounded adaptation with evaluation before rollout")

### 1.2 Design Principles

- **Agents are data, not processes.** An agent is rows in PostgreSQL, prompts in PostgreSQL, vectors in pgvector. The runtime is shared. (ADP §5.7: "Agent composition, not agent proliferation")
- **Every external dependency behind a protocol.** LiteLLM, Arize, PostgreSQL — all swappable. (ADP §10: "Make control flow visible")
- **The model proposes, the runtime executes.** LLMs suggest tool calls. Sentinel validates and dispatches. The agent never directly touches the outside world. (ADP §5.5: "Execution is external to the model")
- **Security at every boundary, not just the front door.** Warden scans untrusted ingress. Sentinel enforces policy everywhere. (ADP §8.4: "Safety is layered system controls")

---

## 2. Agent Architecture

### 2.1 What Is An Agent

An agent is a unit of configuration that determines behavior when combined with the shared runtime:

- **Identity** (agent.yaml + SOUL.md) — who it is, what it can do
- **Reasoning strategy** — how it thinks (react, plan-execute, classify-only, direct, delegate, or custom container)
- **Scoped memory** — its own learnings, episodic memories, knowledge, isolated by default
- **Security boundary** — its own Warden rules and Sentinel policies
- **Tool permissions** — which MCP tools it can access, enforced by LiteLLM per-key

There is no agent lifecycle. Agents don't start or stop. They exist as data. The runtime fetches their config from a prompt cache (LRU, evict-on-full) when a request arrives.

### 2.2 Agent Definition Format (GitAgent-Compatible)

```
my-agent/
├── agent.yaml              # REQUIRED — manifest
├── SOUL.md                 # REQUIRED — system prompt / personality
├── RULES.md                # Hard constraints (must-always / must-never)
├── skills/                 # SKILL.md files
├── tools/                  # MCP-compatible tool definitions
├── memory/                 # Seed memories (imported to pgvector)
├── knowledge/              # Reference docs (chunked + embedded for RAG)
├── strategy.py             # Custom deterministic logic (optional, containerized if untrusted)
├── Dockerfile              # For custom strategy containers (optional)
└── agents/                 # Sub-agent definitions (recursive)
```

Only agent.yaml and SOUL.md are required. Everything else is optional. Import/export round-trips cleanly.

### 2.3 Agent Identity

```yaml
# agent.yaml
spec_version: "0.1.0"
name: artificer
version: 1.0.0
description: Code and engineering specialist

soul: SOUL.md

reasoning:
  strategy: plan_execute          # direct | react | plan_execute | delegate | custom
  max_rounds: 10
  review_after_each: true

model: auto
model_fallbacks: [mistral-large, gemini-2.5-pro]
model_constraints:
  temperature: 0.3
  max_tokens: 4096

tools:
  - file_ops
  - shell
  - test_runner
  - lint_runner
  - git

skills: []

memory:
  learnings: true
  episodic: true
  knowledge: true
  session: true
  shared: false
  scope: agent                    # default scope for new memories

rules: RULES.md
trust_tier: t1

permissions:
  max_tool_calls_per_request: 20
  rate_limit: 60/minute

delegation_mode: none
sub_agents:
  - artificer-planner
  - artificer-coder
  - artificer-reviewer
  - artificer-debugger

proactive:
  heartbeat: null
  events: []
  cron: []
```

### 2.4 Agent Roster (Shipped With Stronghold)

| Agent | Strategy | Tools | Trust | Purpose |
|-------|----------|-------|-------|---------|
| **Arbiter** | delegate | none | t0 | Triages ambiguous requests. Sees all agent identities and memory summaries. Cannot act directly. |
| **Ranger** | react | web_search, database_query, knowledge_search | t1, untrusted output | Read-only information retrieval. Everything returned is Warden-scanned. |
| **Artificer** | plan_execute | file_ops, shell, test_runner, lint_runner, git | t1 | Code/engineering. Sub-agents: planner, coder, reviewer, debugger. |
| **Scribe** | plan_execute | file_ops | t1 | Writing/creative. Committee: researcher, drafter, critic, advocate, editor. |
| **Warden-at-Arms** | react | ha_control, ha_list_devices, ha_notify, api_call, runbook_execute | t1 elevated | Real-world interaction. API surface discovery on initialization. |
| **Forge** | react | file_ops, scanner, schema_validator, test_executor, prompt_manager | t1 elevated | Creates tools and agents. Output starts at ☠️ tier. Iterates until minimum viability. |

### 2.5 Reasoning Strategies

**Generic (no custom Python, any imported agent can use):**

| Strategy | Behavior | Lines |
|----------|----------|-------|
| `direct` | Single LLM call, no tools. Chat responses. | ~15 |
| `react` | LLM → tool calls → execute → feed back → repeat (max N rounds). | ~50 |
| `plan_execute` | Plan → decompose → execute subtasks via sub-agents → review. | ~70 |
| `delegate` | Classify intent → route to sub-agent. The Arbiter's brain. | ~20 |

**Custom (Python, shipped with Stronghold or containerized for untrusted):**

| Strategy | Agent | What's Deterministic |
|----------|-------|---------------------|
| Forge strategy | Forge | generate → scan → validate schema → test → iterate loop |
| Artificer strategy | Artificer | plan → code → run pytest → check exit code → review |
| Scribe strategy | Scribe | research → draft → critique → defend → edit committee |
| API discovery | Warden-at-Arms | fetch OpenAPI → parse → classify risk → test → generate skills |

Custom strategies from untrusted sources run in containers. The container is an A2A endpoint — receives a task, calls back to Stronghold for LLM/tools/memory, returns a result. Stronghold manages the container lifecycle.

### 2.6 Routing: Conduit + Tournaments

**Default routing:** Intent → agent lookup table. The classifier produces a task_type, the table maps it to an agent.

**Tournament evolution:** 5-10% of requests run two agents on the same task. Score both (LLM-as-judge, tool success rate, user feedback, trace annotation). Track Elo/win-rate. If a challenger consistently outscores the incumbent, auto-promote.

**Multi-intent parallel dispatch:** When the classifier detects multiple intents in a single request ("turn on the fan and write a poem about it"), the Conduit:

1. Splits the request into scoped subtasks — one per detected intent
2. Dispatches each subtask to the appropriate specialist agent **in parallel** (no dependency between them)
3. Each agent receives only its subtask, not the full compound request — Scribe gets "write a poem about a fan", Warden-at-Arms gets "turn on the fan"
4. Agents execute independently with their own tools, memory, and trust boundaries
5. Conduit aggregates all results into a single response
6. If any subtask fails, the Conduit reports partial success — other subtasks are not affected

This is architecturally different from Conductor's approach (merge all tools into one agent's context). Parallel dispatch preserves agent isolation: the Scribe never sees HA tools, the Warden-at-Arms never sees the poem request. Context windows stay focused, permission boundaries stay intact.

**Dynamic intent creation:** When an agent is imported with capabilities that don't fit existing intents, the system creates a new intent category from the agent's declared keywords. The imported agent becomes the default handler.

### 2.7 Execution Modes

| Mode | Behavior | Trigger |
|------|----------|---------|
| `best_effort` | Try once/twice, return what you have. Default for chat. | Chat input |
| `persistent` | Keep working until done or token budget exhausted. Retry with different approaches. | Form/API with budget |
| `supervised` | Same as persistent but pauses at decision points for user confirmation. | Form/API with confirmation flag |

Budget tracked via LiteLLM cost tracking. Sentinel checks remaining budget before each LLM call.

### 2.8 Inter-Agent Communication

A2A-shaped messages for all delegation:

```python
@dataclass
class AgentTask:
    id: str
    from_agent: str
    to_agent: str
    messages: list[dict]
    execution_mode: ExecutionMode
    token_budget: float | None
    status: str              # submitted | working | input-required | completed | failed
    result: str | None
    trace_id: str
```

Transport: function calls in-process. A2A JSON over HTTP when agents become separate services (enterprise K8s deployment).

### 2.9 Proactive Behavior (Reactor)

All proactive behavior flows through a single **Reactor** — a 1000Hz event loop that unifies event-driven, interval-based, and time-based triggers into one evaluation system.

**Core insight:** A trigger is `when CONDITION, do ACTION`. The condition can be an event (`tool_call == ha_control`), time (`05:45`), or interval (`every 30 minutes`). These are the same pattern with different predicates. One loop evaluates all of them.

#### Reactor Loop

The loop does **no I/O**. It drains an event queue, evaluates trigger conditions (pure logic), and spawns async tasks for matches. Benchmarked at 0.46% of 1 core with 100 triggers at 1000Hz. 35us average blocking latency.

```
┌───────────────────────────────────────┐
│          Reactor (1000Hz tick)         │
│  1. Drain event queue                 │
│  2. For each trigger: condition match?│
│     → blocking: resolve future inline │
│     → async: spawn worker task        │
│  3. sleep(1ms)                        │
└───────────────┬───────────────────────┘
                │ spawns
                ▼
┌───────────────────────────────────────┐
│         Worker Tasks (async)           │
│  agent.handle(), health checks, etc.  │
└───────────────────────────────────────┘
```

#### Trigger Modes

| Mode | Condition | Example |
|------|-----------|---------|
| `event` | Matches event name (regex) | `pre_tool_call`, `quota_exceeded`, `warden_alert` |
| `interval` | Elapsed time since last fire | Every 30 minutes (with optional PRNG jitter ±20%) |
| `time` | Clock matches HH:MM | `05:45` daily |
| `state` | Callable returns true | `quota.usage_pct > 80` |

#### Blocking vs Async

- **Blocking triggers** resolve the emitter's future inline (≤1ms). Used for gates: `pre_tool_call` → allow/deny. The request pipeline awaits the result.
- **Async triggers** spawn a task and return immediately. Used for side effects: learning extraction, health checks, notifications.

#### Circuit Breaker

Per-trigger failure tracking. Disable after N consecutive failures. Alert to audit log. Re-enable via admin API or restart.

#### Why a Tick Loop (Not Pure Event-Driven)

A pure `await queue.get()` loop uses zero CPU when idle but trusts all emitters to be reliable. The tick loop re-evaluates every condition every millisecond regardless of emitter health. If an emitter crashes, interval/time/state triggers still fire because the loop checks the clock itself. The 0.46% CPU is the cheapest reliability guarantee in the system.

#### Integration

All proactive triggers ultimately invoke `agent.handle()` with a system-generated message. Same pipeline, different input source. Event sources:
- **Request pipeline** (`route_request`): `pre_classify`, `post_classify`, `pre_tool_call`, `post_tool_call`, `post_response`
- **Internal clock**: interval and time triggers evaluated each tick
- **State monitors**: quota pressure, Warden alerts, agent import events

---

## 3. Security Architecture

### 3.1 Threat Baseline

`/root/conductor_security.md` documents 20 known gaps and 50 untouched security concerns in the current Conductor stack. Stronghold must improve on every one.

### 3.2 Warden (Threat Detection)

**Job:** Detect hostile content in untrusted data entering the system.
**Runs at exactly two points:** user input and tool results.
**Cannot:** call tools, access memory, invoke inference (intentionally incapable).

Three layers (cheap to expensive, short-circuit on detection):
1. **Regex patterns** — known attack shapes (prompt injection, role hijacking, system prompt extraction). Zero cost, sub-millisecond.
2. **Heuristic scoring** — instruction-density detection in tool results. Lightweight statistical check.
3. **LLM classification** — novel threat detection. Only triggered when heuristics are ambiguous. Cheap/fast model. Classification prompt managed in PostgreSQL prompt library.

Verdict: `clean | sanitized | blocked` with structured flags.

**Addresses Conductor gaps:** #1-6 (prompt injection), #3 (tool result injection), #10 (tool results fed to LLM unredacted).

### 3.3 Sentinel (Policy Enforcement)

**Job:** Enforce correctness and policy at every boundary crossing.
**Implementation:** LiteLLM guardrail plugin (pre-call and post-call hooks).

Capabilities:
- **Schema validation** — validate LLM tool_call arguments against MCP server's declared inputSchema.
- **Schema repair** — fuzzy match hallucinated arg names to real field names, coerce types, apply defaults. Repairs feed back into learnings.
- **Policy enforcement** — per-agent tool permissions via LiteLLM per-key configuration.
- **Token optimization** — compress bloated tool results (strip K8s metadata, truncate search results, compact JSON) before re-injection into LLM context.
- **Audit logging** — every boundary crossing logged to PostgreSQL + Arize trace span.
- **Rate limiting** — protocol connection to LiteLLM's rate limiting, controllable via LiteLLM UI or eventually Stronghold UI.
- **PII filtering** — scan outbound responses for leaked API keys, internal IPs, system prompt content.

**Addresses Conductor gaps:** #4 (no rate limiting), #5 (JWT audience), #6 (hardcoded roles), #12 (infra_action no allowlist), #13 (CoinSwarm spawn no bound), #22 (no body size limit), #29 (routing metadata leaks), #31 (error responses unfiltered), #47 (skill import from any URL).

### 3.4 The Gate (Input Processing)

**Job:** Process user input before it reaches the Conduit.
**Not an agent.** Infrastructure with limited capabilities.

Flow:
1. **Warden scan** — malicious intent detection
2. **Sanitize** — strip zero-width chars, normalize unicode, escape injection fragments
3. **If persistent/supervised mode:** Query Improver (good model) — summarize request, identify gaps, generate 1-5 clarifying questions (a,b,c,d,other), return to user for correction
4. **If chat/best_effort:** silent sanitize, pass through immediately
5. Pass safe, improved prompt to Conduit

**Addresses Conductor gaps:** #4 (classifier manipulation via keyword stuffing), #22 (no body size limit), #34 (client-provided session_id).

### 3.5 Trust Tiers

| Tier | Name | Description | Who Creates |
|------|------|-------------|-------------|
| ☠️ | Skull | In the Forge. Under construction. Cannot be used. | Forge agent |
| T3 | Forged | Passed Forge QA. Sandboxed. Read-only tools only. | Forge → promotion |
| T2 | Community | Marketplace install or operator-approved. Standard policies. | Import from URL |
| T1 | Installed | Operator-vetted. Full tool access per agent config. | GitAgent import, admin-approved |
| T0 | Built-in | Shipped with Stronghold. Core trust. | Stronghold maintainers |

Promotion path: ☠️ → T3 (Forge QA passes) → T2 (N successful uses, no Warden flags) → T1 (operator approval). Never auto-promotes to T0.

### 3.6 Security Concern Traceability

Every concern from `conductor_security.md` §17 mapped to a Stronghold mitigation:

**Prompt Injection (#1-6):** Warden regex+LLM at user input ingress. Warden scan on tool results before LLM re-injection. Memory scope isolation prevents poisoned learnings from leaking cross-user.

**Cross-User Data Leakage (#7-11):** Memory scoped by (global/team/user/agent/session). Retrieval queries filter by scope. Arize handles trace RBAC (Enterprise) or is single-tenant (Phoenix).

**Privilege Escalation (#12-17):** Sentinel schema validation against MCP inputSchema. Per-agent tool permissions via LiteLLM per-key config. Execution modes with token budgets. Config-driven permission tables, not hardcoded roles.

**Shared Credentials (#18-21):** K8s secrets manager (compatible with Vault, Vaultwarden). Per-agent credentials. No hardcoded keys in source. Service-to-service JWT signing (LiteLLM's Zero Trust JWT).

**DoS (#22-28):** Sentinel rate limiting via LiteLLM. Request body size limits at Gate. Circuit breaker pattern for failed backends. Connection pooling via asyncpg (not per-call SQLite connections).

**Information Disclosure (#29-33):** Sentinel PII filter on outbound responses. No routing metadata in production responses (debug mode only). Error responses sanitized before return.

**Session Integrity (#34-37):** Session IDs validated by Sentinel. User-scoped sessions enforced. Session revocation via API.

**Supply Chain (#38-41):** Pinned dependencies with hash verification. Docker image digest pinning. Checksummed binary downloads in Dockerfiles.

**Crypto (#42-44):** JWT audience verification enabled (Entra ID and Keycloak both enforce). CSRF protection via SameSite cookies. Constant-time token comparison for static keys.

---

## 4. Memory Architecture

### 4.1 Storage

Single PostgreSQL instance with pgvector extension. No SQLite.

```sql
-- stronghold schema
agents              -- agent registry (identity, config, trust tier)
learnings           -- self-improving corrections (per-agent scoped)
sessions            -- conversation history (per-user scoped)
quota_usage         -- token tracking (migrated from SQLite)
audit_log           -- Sentinel audit trail
permissions         -- RBAC config cache
tournaments         -- agent head-to-head results

-- memories schema (pgvector)
episodic            -- 7-tier weighted memories
knowledge           -- RAG chunks + embeddings
```

### 4.2 Memory Scopes

| Scope | Visibility | Example |
|-------|-----------|---------|
| `global` | All agents, all users | "GDPR means General Data Protection Regulation" |
| `team` | Agents in the same domain | "The data pipeline team uses Airflow" |
| `user` | All agents, for this specific user | "Blake prefers concise responses" |
| `agent` | Only this agent | "entity_id for the fan is fan.bedroom_lamp" |
| `session` | Only this conversation | "The user wants bullet points" |

Retrieval: `global + team (if applicable) + user (from auth) + agent (from agent_id) + session (if session_id)`. One query, ranked by `similarity(content, query) * weight`.

### 4.3 Episodic Memory Tiers

| Tier | Weight Bounds | Pruning | Purpose |
|------|--------------|---------|---------|
| Observation | 0.1 – 0.5 | Can decay to zero | Neutral notices |
| Hypothesis | 0.2 – 0.6 | Can decay to zero | What-if analysis |
| Opinion | 0.3 – 0.8 | Slow decay | Beliefs with confidence |
| Lesson | 0.5 – 0.9 | Resistant to decay | Actionable takeaways |
| Regret | 0.6 – 1.0 | **Cannot drop below 0.6** | Mistakes to never repeat |
| Affirmation | 0.6 – 1.0 | **Cannot drop below 0.6** | Wins to repeat |
| Wisdom | 0.9 – 1.0 | **Near-permanent** | Institutional knowledge |

### 4.4 Self-Improving Memory Loop

```
Request arrives with user text
  → Retrieve relevant learnings (keyword + embedding hybrid search)
  → Inject into system prompt
  → LLM generates response (may include tool calls)
  → Tool call fails → retry with different args → succeeds
  → Learning extractor: "tool X fails with arg A, succeeds with arg B"
  → Store as agent-scoped learning with trigger keywords
  → After N successful injections → auto-promote to permanent prompt
  → Optionally bridge to episodic memory (LESSON tier)
```

---

## 5. Tool Architecture

### 5.1 MCP Via LiteLLM

LiteLLM is the MCP gateway. Stronghold does not implement its own MCP gateway.

LiteLLM handles:
- MCP protocol (Streamable HTTP, SSE, stdio)
- OpenAPI-to-MCP auto-conversion (point at any OpenAPI spec, get MCP tools)
- Per-key/team tool permissions (allowed_tools, disallowed_tools, allowed_params)
- Semantic tool filtering (embedding-based, top-K relevant tools per request)
- OAuth mediation for MCP servers
- Tool call cost tracking
- A2A agent permissions

### 5.2 Sentinel As LiteLLM Guardrail

Sentinel registers as a LiteLLM guardrail (pre-call + post-call):

**Pre-call:** Schema validation + repair on tool arguments. Fuzzy match hallucinated field names. Coerce types. Apply defaults from MCP inputSchema.

**Post-call:** Warden scan on tool results (indirect injection detection). Token optimization (compress bloated results). Audit logging.

### 5.3 Tool Backends

| Backend | Protocol | Provided By |
|---------|----------|-------------|
| MCP servers | MCP native | Community servers (HA, filesystem, git, etc.) |
| OpenAPI endpoints | Auto-converted to MCP | LiteLLM OpenAPI-to-MCP |
| Kubernetes | MCP | K8s MCP servers (Red Hat, Azure, Flux159) |
| Legacy HTTP | Direct HTTP | Migration wrapper for Conductor tools |

### 5.4 Forge Tool/Agent Creation

The Forge agent iterates on created artifacts until they pass minimum viability:

```
Generate → Scanner (security) → Schema validator → Test with sample inputs
  → Test with empty inputs → Test with adversarial inputs
  → All pass → Promote from ☠️ to T3
  → Any fail → Fix and retry (max 10 rounds)
```

Forge output can never auto-promote past T3. Higher tiers require automated tournament evidence or human approval.

---

## 6. Authentication & Authorization

### 6.1 Auth Providers (Protocol-Based)

```python
class AuthProvider(Protocol):
    async def authenticate(self, authorization: str | None,
                           headers: dict | None = None) -> AuthContext: ...
```

| Provider | Use Case | Claims |
|----------|----------|--------|
| Keycloak OIDC | Homelab, open-source default | realm_access.roles |
| Entra ID | Enterprise (JedAI) | roles (app roles) |
| Static API key | Service-to-service, backward compat | Maps to system admin context |
| OpenWebUI headers | Thin client passthrough | X-OpenWebUI-User-* headers |

### 6.2 RBAC (Config-Driven)

```yaml
# permissions.yaml
roles:
  admin:
    tools: ["*"]
    agents: ["*"]
  engineer:
    tools: [web_search, file_ops, shell, git, test_runner]
    agents: [artificer, ranger, scribe]
  operator:
    tools: [ha_control, ha_list_devices, k8s_get_pods, k8s_scale]
    agents: [warden-at-arms, ranger]
    require_confirmation: [k8s_scale]
  viewer:
    tools: [web_search]
    agents: [ranger, scribe]

role_mapping:
  keycloak:
    admin: admin
    parent: operator
    kid: viewer
  entra_id:
    Stronghold.Admin: admin
    Stronghold.Engineer: engineer
    Stronghold.Operator: operator
    Stronghold.Viewer: viewer
```

**Addresses Conductor gap #6:** roles are config, not code. No `_USER_ROLES` dict.

---

## 7. Observability

### 7.1 Split Responsibilities

| Concern | Backend | Why |
|---------|---------|-----|
| Prompt management | PostgreSQL (stronghold.prompts table) | Versioning, labels, config metadata — all just columns. No external dependency. |
| Traces + scoring (small team / demo) | Arize Phoenix (OSS, 2 containers) | OTEL-native, lightweight, free |
| Traces + scoring (enterprise) | Arize Enterprise | RBAC, SSO, team scoping, audit logs, cost tracking, dashboards |
| LLM call telemetry | LiteLLM callbacks → Phoenix or Arize | Cost, tokens, latency per call |
| Audit trail | PostgreSQL (stronghold.audit_log) | Queryable, persistent, not dependent on external service |

### 7.2 Prompt Storage (PostgreSQL-Native)

Prompts are stored in PostgreSQL, not Langfuse. A prompt is a versioned text blob with structured metadata:

```sql
CREATE TABLE prompts (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,            -- "agent.artificer.soul"
    version     INTEGER NOT NULL,
    label       TEXT,                     -- "production", "staging", NULL
    content     TEXT NOT NULL,            -- the prompt text
    config      JSONB DEFAULT '{}',       -- structured metadata
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    created_by  TEXT DEFAULT 'system',
    UNIQUE(name, version),
    UNIQUE(name, label)
);
```

API endpoints for prompt management:
- `GET /api/prompts` — list all prompts
- `GET /api/prompts/{name}` — get prompt (label=production default)
- `GET /api/prompts/{name}/versions` — version history
- `PUT /api/prompts/{name}` — create new version
- `POST /api/prompts/{name}/promote` — move label to a version

This replaces Langfuse for prompt management. No external dependency. Multi-tenant via tenant_id column. Hot-reload via PostgreSQL LISTEN/NOTIFY or poll updated_at.

### 7.3 Protocol Layer

Every observability component behind a protocol:

| Protocol | Primary Impl | Fallback |
|----------|-------------|----------|
| `PromptManager` | PostgreSQL (stronghold.prompts) | Filesystem (YAML/MD for dev), Langfuse (legacy adapter) |
| `TracingBackend` | Arize Phoenix (small team) or Arize Enterprise (enterprise) | PostgreSQL raw, noop |
| `LLMClient` → callback | LiteLLM → Phoenix/Arize | LiteLLM → stdout |

### 7.4 Tracing Architecture

Every request is a trace. Every boundary crossing is a span:

```
trace (user_id, session_id, agent)
├── warden.user_input
├── sentinel.user_to_system
├── gate.query_improve (if persistent mode)
├── conduit.classify
├── conduit.route
├── agent.{name}.handle
│   ├── prompt.build (soul + tools + learnings + episodic)
│   ├── sentinel.system_to_llm
│   ├── llm_call_0 (LiteLLM callback fills details)
│   ├── sentinel.llm_to_system
│   ├── tool.{name} (via Sentinel guardrail)
│   │   ├── sentinel.validate_args
│   │   ├── sentinel.repair (if needed)
│   │   ├── execution
│   │   ├── warden.tool_result
│   │   └── sentinel.token_optimize
│   ├── llm_call_1
│   ├── learning.extraction
│   └── sentinel.system_to_user
└── trace.end
```

---

## 8. Protocol Layer

Every external dependency behind a protocol interface. Implementations are swappable without touching business logic.

| Protocol | Methods | Current Impl | Swap Target |
|----------|---------|-------------|-------------|
| `ModelProxy` | complete(), stream(), list_models() | LiteLLM | Archestra, direct provider SDKs |
| `ToolGateway` | list_tools(), call_tool(), register_*() | LiteLLM MCP gateway | Archestra, Kong, standalone |
| `AuthProvider` | authenticate() | Keycloak, Entra ID | Any OIDC provider |
| `PromptManager` | get(), get_with_config(), upsert() | PostgreSQL (stronghold.prompts) | Langfuse (legacy adapter) |
| `TracingBackend` | create_trace() → Trace, Span | Arize Enterprise | Phoenix, PostgreSQL, noop |
| `DataStore` | execute(), insert() | PostgreSQL (asyncpg) | SQLite (aiosqlite) for local dev |
| `LearningStore` | store(), find_relevant(), mark_used(), check_auto_promotions() | PostgreSQL | — |
| `EpisodicStore` | store(), retrieve(), reinforce() | PostgreSQL + pgvector | — |
| `SessionStore` | get_history(), append_messages() | PostgreSQL | Redis |
| `QuotaTracker` | record_usage(), get_usage_pct() | PostgreSQL | LiteLLM native spend tracking |

---

## 9. Deployment

### 9.1 Target: Kubernetes

Clean enterprise production K8s deployment. No enterprise license required for single-team use.

### 9.2 Components

| Component | Type | Notes |
|-----------|------|-------|
| Stronghold API | Deployment | FastAPI, the main application |
| PostgreSQL + pgvector | StatefulSet | Single instance, multiple schemas |
| Arize Phoenix (small team) or Arize Enterprise | Deployment | Traces + dashboards |
| LiteLLM | Deployment | Model proxy + MCP gateway + tool policy |
| Arize | Managed or self-hosted | Trace storage + dashboards |
| MCP servers | Deployments (1 per tool backend) | HA, K8s, filesystem, etc. |
| Custom agent containers | Deployments (optional) | For teams running containerized strategies |

### 9.3 Secrets

K8s secret manager (primary). Compatible with HashiCorp Vault and Vaultwarden. No hardcoded keys in source or config files.

### 9.4 Multi-Tenant Isolation

Per-tenant K8s namespace. Each namespace gets:
- Own LiteLLM API keys (tool permissions scoped)
- Own Arize project/space (trace isolation via RBAC)
- Memory scoped by tenant_id in shared PostgreSQL, or separate PostgreSQL per namespace

---

## 10. Import / Export

### 10.1 GitAgent Import

```
git clone → stronghold agent import ./my-agent/
```

| Source | Destination | Purpose |
|--------|------------|---------|
| agent.yaml | PostgreSQL agents table | Registry |
| SOUL.md | PostgreSQL prompt: agent.{name}.soul | Hot-swappable system prompt |
| RULES.md | PostgreSQL prompt + Warden rule set | Security policy |
| skills/*.md | PostgreSQL prompts: skill.{name} | Tool system prompts |
| tools/*.yaml | PostgreSQL prompts: tool.{name} | MCP tool definitions |
| memory/ | PostgreSQL pgvector (episodic) | Seed memories |
| knowledge/ | PostgreSQL pgvector (knowledge) | RAG chunks + embeddings |
| compliance/ | Sentinel policy store | Per-agent policies |
| strategy.py + Dockerfile | Container image (if untrusted) | Custom deterministic logic |
| agents/ | Recursive import | Sub-agent definitions |

### 10.2 GitAgent Export

Running agent → GitAgent directory. Includes updated soul (from production-labeled prompt), accumulated memories, learned corrections. Push to GitHub. Anyone can clone and run the improved agent.

### 10.3 GitHub → Stronghold Prompt Sync

GitHub Action: on push to main → sync prompts to PostgreSQL prompt library with "production" label. On push to staging → "staging" label. ~100 line script (parses YAML frontmatter + markdown, calls Stronghold prompt API).

---

## 11. Package Structure

```
stronghold/
├── protocols/              # Abstract interfaces (the skeleton)
│   ├── router.py, classifier.py, memory.py, tools.py
│   ├── auth.py, skills.py, quota.py, tracing.py, llm.py
│
├── types/                  # Shared value objects + error hierarchy
│   ├── intent.py, model.py, auth.py, skill.py, tool.py
│   ├── memory.py, session.py, config.py, errors.py
│
├── classifier/             # Intent classification engine
│   ├── keyword.py, llm_fallback.py, multi_intent.py
│   ├── complexity.py, engine.py
│
├── router/                 # Model selection (the scoring formula)
│   ├── scorer.py, scarcity.py, speed.py, filter.py, selector.py
│
├── security/               # Warden + Sentinel + Gate
│   ├── warden/             # Threat detection (regex + heuristics + LLM)
│   ├── sentinel/           # LiteLLM guardrail (schema repair, token opt, audit)
│   └── gate.py             # Input processing (sanitize, improve, clarify)
│
├── memory/                 # Memory systems
│   ├── learnings/          # Self-improving corrections
│   ├── episodic/           # 7-tier weighted memories
│   └── scopes.py           # global/team/user/agent/session filtering
│
├── sessions/               # Conversation history
├── quota/                  # Token tracking
│
├── agents/                 # Agent runtime
│   ├── base.py             # Agent class, AgentIdentity, handle()
│   ├── cache.py            # Prompt LRU cache
│   ├── strategies/         # Generic: direct, react, plan_execute, delegate
│   ├── forge/              # Forge agent custom strategy
│   ├── artificer/          # Artificer custom strategy
│   ├── scribe/             # Scribe custom strategy
│   ├── warden_at_arms/     # Warden-at-Arms custom strategy + API discovery
│   ├── registry.py         # Agent CRUD
│   ├── importer.py         # GitAgent import
│   ├── exporter.py         # GitAgent export
│   ├── tournament.py       # Head-to-head scoring + promotion
│   └── intents.py          # Dynamic intent registry
│
├── tools/                  # Tool integration
│   ├── registry.py         # Aggregate MCP + prompt library + legacy tools
│   └── legacy.py           # Wrapper for Conductor tools not yet on MCP
│
├── skills/                 # Skill ecosystem
│   ├── parser.py, loader.py, forge.py, marketplace.py, registry.py
│
├── tracing/                # Observability
│   ├── arize.py, langfuse.py, noop.py, trace.py
│
├── config/                 # Configuration
│   ├── loader.py, defaults.py, env.py
│
├── events.py               # Async EventBus for proactive triggers
├── container.py            # DI container (wires protocols to implementations)
│
└── api/                    # Thin FastAPI transport layer
    ├── app.py              # FastAPI factory
    ├── routes/             # chat.py, models.py, status.py, admin.py, skills.py, agents.py
    └── middleware/          # auth.py, tracing.py
```

---

## 12. What We Build First

### Phase 0: Scaffold
- Repository setup, PostgreSQL schema, file skeleton, agent definitions, dev-tools-mcp server

### Phase 1: Types + Protocols + Auth
- types/ and protocols/ (the contract)
- Auth providers (Keycloak, Entra ID, static key, OpenWebUI headers)
- Config (Pydantic validation, env resolution)
- Test infrastructure (fakes, factories, fixtures)

### Phase 2: Router + Classifier
- router/ (port from Conductor, split into modules)
- classifier/ (port keyword engine + LLM fallback)
- Full test suites (property-based for scoring)

### Phase 3: Security Layer + Security Gate
- security/warden/ (port Bouncer regex patterns, add tool result scanning)
- security/sentinel/ (LiteLLM guardrail — schema validation, repair, token optimization)
- security/gate.py (input processing — sanitize, improve, clarify)

### Phase 4: Memory
- memory/learnings/ (port from Conductor, PostgreSQL, add agent_id + user_id scope)
- memory/episodic/ (port 7-tier system, add scope filtering)
- memory/scopes.py

### Phase 5: Data Layer + Auth
- sessions/ (port, PostgreSQL)
- quota/ (port, PostgreSQL)
- config/ finalized
- Permission table (config-driven RBAC)

### Phase 6: Agent Runtime
- agents/base.py (Agent class, handle(), AgentIdentity)
- agents/strategies/ (direct, react, plan_execute, delegate)
- agents/cache.py (prompt LRU)
- agents/registry.py + intents.py
- events.py (async EventBus)

### Phase 7: Agent Roster + Tools + Security Gate
- Agent definitions (YAML + SOUL.md) for Arbiter, Ranger, Artificer, Scribe, Warden-at-Arms, Forge
- tools/ (LiteLLM MCP gateway integration, legacy wrapper)
- Sentinel registered as LiteLLM guardrail
- Custom strategies for specialists
- Tournament manager (stub) + dynamic intent registry

### Phase 8: Import/Export + API
- agents/importer.py, exporter.py (GitAgent format)
- api/ (thin FastAPI routes)
- GitHub → Stronghold prompt sync action

### Phase 9: Deployment
- Dockerfile, Helm chart, K8s secret manager
- Multi-tenant namespace isolation

### Phase 10: Polish + Ship + Security Gate
- Test coverage audit, performance tests, load tests
- Documentation, README, CHANGELOG, CONTRIBUTING
- v1.0 tag + publish

---

## 13. Source Reference

| Stronghold Module | Conductor Source | Action |
|-------------------|-----------------|--------|
| router/scorer.py | app/router.py:54-226 | Port scoring formula verbatim |
| router/scarcity.py | app/router.py:229-261 | Extract pure function |
| classifier/ | app/classifier.py | Port + split into modules |
| memory/learnings/ | app/learnings.py | Port + PostgreSQL + agent_id scope |
| memory/episodic/ | orchestrator/memory/episodic.py | Port tier system |
| security/warden/ | orchestrator/agents/bouncer.py | Port regex patterns + add tool result scanning |
| agents/base.py | app/main.py:190-698 | Decompose into Agent + strategies |
| tools/legacy.py | app/tools.py | Thin wrapper, migrate to MCP over time |
| sessions/ | app/sessions.py | Port + PostgreSQL |
| quota/ | app/quota.py | Port + PostgreSQL |
| config/ | app/auth.py (permissions only) | Redesign: config-driven RBAC |
| skills/ | app/skills.py, forge.py, skill_hub.py, skill_registry.py | Port + rename |

---

## 14. Threat Model Baseline

See `/root/conductor_security.md` for the full 50-concern threat model of the current Conductor stack. Every concern has a corresponding mitigation in this architecture. The Stronghold security model (Warden + Sentinel + Gate + trust tiers + config-driven RBAC + per-agent memory scoping + K8s secrets) is designed to close every identified gap.
