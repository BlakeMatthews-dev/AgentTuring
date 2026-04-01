# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**Project**: Stronghold — Secure Agent Governance Platform
**License**: Apache 2.0

---

## IMPORTANT: Project Identity

Stronghold is an **enterprise multi-tenant agent governance platform**. It is NOT:
- NOT conductor-router (that's the homelab predecessor, a different repo)
- NOT a homelab tool (it targets K8s + Entra ID deployment)
- NOT a chatbot wrapper (it's a governance layer with security, routing, memory, and audit)

All architecture decisions must account for: **tenant isolation, namespace-scoped secrets, per-user memory, pluggable integrations** (no hardcoded profiles, no SQLite in production).

---

## What Is This

Stronghold is an open-source, self-hosted agent governance platform. It wraps any LLM in a secure execution harness with intelligent routing, self-improving memory, autonomous operation, and zero-trust security.

**Read ARCHITECTURE.md first.** It is the authoritative design document.

---

## Development Commands

```bash
# Run all tests
pytest tests/ -v

# Run a single test file
pytest tests/routing/test_selector.py -v

# Run a single test by name
pytest tests/ -v -k "test_claim_returns_none"

# Linting + formatting
ruff check src/stronghold/
ruff format --check src/stronghold/

# Type checking
mypy src/stronghold/ --strict

# Security scanning
bandit -r src/stronghold/ -ll

# All checks (CI equivalent)
pytest tests/ -v && ruff check src/stronghold/ && ruff format --check src/stronghold/ && mypy src/stronghold/ --strict && bandit -r src/stronghold/ -ll

# Pre-commit hooks
pre-commit install
pre-commit run --all-files

# Run the app
docker compose up -d
curl http://localhost:8100/health
```

Python 3.12+. Install dev dependencies: `pip install -e ".[dev]"`. Tests use `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed). The `perf` marker gates tests that hit real LLMs.

---

## Testing Rules (MANDATORY)

1. **Real integration tests, not mocks.** Import and instantiate real classes (`InMemoryLearningStore`, `Warden`, `Gate`, etc.). Only mock external HTTP calls. All protocols have fakes in `tests/fakes.py` — use those, not `unittest.mock`.
2. **Never modify production code when writing tests.** If a test requires a production change, document what's needed but don't make the change in the same task.
3. **Never move or rename production files.** Sub-agents writing tests especially must not reorganize `src/`.
4. **Run the full test suite after each change.** Not just the file you touched — cascading failures are common.
5. **Verify claimed fixes.** After saying "removed X" or "fixed Y", grep to confirm. Don't trust the diff alone.

---

## Build Rules (MANDATORY)

1. **No Code Without Architecture** — Every module must be described in ARCHITECTURE.md before implementation begins.
2. **No Code Without Tests (TDD)** — Failing test stubs first, then implementation.
3. **Every Change Must Pass** — pytest, ruff check, ruff format, mypy --strict, bandit -ll. Enforced via pre-commit hooks. The Artificer agent runs the same checks.
4. **No Hardcoded Secrets** — Config via env vars or K8s secrets. Defaults must be example values (`sk-example-xxx`, `10.0.0.x`).
5. **No Direct External Imports** — Never import `litellm`, `langfuse`, `arize` in business logic. Import the protocol; the DI container wires the implementation.
6. **Every Protocol Needs a Noop/Fake** — Test fakes in `tests/fakes.py` so tests run without external services.
7. **Security Review Gates** — Phases 3, 7, and 10 have mandatory security review checkpoints per ARCHITECTURE.md §3.6.
8. **No Co-Authored-By Lines** — Never add `Co-Authored-By` trailers to commits. PRs with these will be deleted.

---

## Architecture Overview

### Request Flow

```
POST /v1/chat/completions
  → Auth validation
  → Warden scan (user input)
  → Classifier: keyword scoring → LLM fallback if score < 3.0
  → Session stickiness check (reuse previous specialist for same session)
  → Ambiguous? → Route to Arbiter for clarification
  → Intent registry: task_type → agent_name
  → Agent.handle():
      → Warden scan
      → Context builder (system prompt + session history + tools + memory)
      → Strategy.reason() (direct | react | plan_execute | delegate | custom)
      → Extract learnings from tool history
      → Warden scan (tool results)
  → Return response
```

### Protocol-Driven DI

All business logic depends on protocols (`src/stronghold/protocols/`), never concrete implementations. The DI container (`container.py`) wires everything. Key protocols: `LLMClient`, `LearningStore`, `AuthProvider`, `IntentClassifier`, `ModelRouter`, `QuotaTracker`, `PromptManager`, `TracingBackend`, `ToolRegistry`, `SkillRegistry`.

### Core Components

| Component | Source | What It Does |
|-----------|--------|-------------|
| **Container** | `container.py` | DI wiring + `route_request()` orchestration (classify → route → agent.handle) |
| **Agent** | `agents/base.py` | Shared pipeline: warden scan → build context → strategy.reason() → extract learnings |
| **Strategies** | `agents/strategies/` | `DirectStrategy` (single call), `ReactStrategy` (tool loop), `PlanExecuteStrategy`, `DelegateStrategy` |
| **Classifier** | `classifier/engine.py` | Three-phase: keyword scoring → LLM fallback → complexity/priority inference |
| **Router** | `router/selector.py` | Filter by tier/quota/status → score by quality/speed/strength → select best model |
| **Warden** | `security/warden/` | Regex patterns → heuristic scoring → optional LLM scan (cheap-to-expensive, short-circuit) |
| **LiteLLM Client** | `api/litellm_client.py` | Async HTTP to LiteLLM proxy with automatic model fallback on 429/5xx |
| **Learnings** | `memory/learnings/` | Extract fail→succeed patterns from tool history, auto-promote after N hits |
| **Context Builder** | `agents/context_builder.py` | Assemble system prompt + memory + tools + constraints within token budget |
| **Tracing** | `tracing/phoenix_backend.py` | OTEL spans → Arize Phoenix |

### Agent Roster

| Agent | Strategy | Role |
|-------|----------|------|
| **Arbiter** | delegate | Triages ambiguous requests. Clarifies, then delegates to specialists. |
| **Artificer** | plan_execute (custom) | Code agent with sub-agents (planner, coder, reviewer, debugger). Quality gates: pytest + ruff + mypy + bandit. |
| **Scribe** | plan_execute | Writing specialist with committee pattern. |
| **Ranger** | react | Read-only search. Output always Warden-scanned. |
| **Warden-at-Arms** | react | Device control, API calls, runbook execution. |
| **Forge** | react | Creates tools/agents. Output starts at skull trust tier. |

### Types

All dataclasses live in `src/stronghold/types/`. Key ones: `AgentIdentity` (agent.yaml equivalent), `Intent`, `ModelConfig`/`ModelSelection`, `AuthContext`, `Learning`, `EpisodicMemory`, `WardenVerdict`, `StrongholdConfig`. Error hierarchy: `StrongholdError` → `{RoutingError, ClassificationError, AuthError, ToolError, SecurityError, ConfigError, SkillError}`.

### Testing

Tests mirror source structure under `tests/`. Shared fixtures in `tests/conftest.py` (fake_config, fake_llm, fake_tracer, etc.). Fake implementations for all protocols in `tests/fakes.py`. Integration tests in `tests/integration/` test the full pipeline, HTTP lifecycle, and real LLM calls (gated by `perf` marker).

### Configuration

YAML config loaded by `config/loader.py`. Path from `STRONGHOLD_CONFIG` env var (default: `config/example.yaml`). Env overrides: `DATABASE_URL`, `LITELLM_URL`, `LITELLM_MASTER_KEY`, `ROUTER_API_KEY`, `PHOENIX_COLLECTOR_ENDPOINT`. Config schema in `types/config.py`.

### Ruff Config

Line length 100. Target Python 3.12. Enabled rule sets: E, F, W, I, N, UP, B, A, SIM, TCH.

---

## Design Principles

These override the ADP book (Gulli, 2026) where they conflict.

1. **Use the cheapest reliable tool** — Deterministic code > cheap model > strong model > human. Start at #1, only escalate if genuinely needed.
2. **Runtime is in charge** — The LLM proposes; the runtime validates, bounds, and may reject. LLM never directly touches the outside world.
3. **All input is untrusted** — User input AND tool results get Warden scans before entering LLM context.
4. **Memory must forget** — Decay without reinforcement, resolve contradictions explicitly, weight floors for wisdom/regrets.
5. **Evaluate inline** — Validation at every boundary during execution, not post-hoc.
6. **Budget context windows** — Priority-ordered context assembly with hard token limits. Cut from bottom priority, not randomly.
7. **Autonomy is a tradeoff** — Every capability needs bounds (max rounds, token budgets, timeouts, Warden scans).
8. **Multi-agent for isolation only** — Add agents for permission, trust, or strategy isolation. Not for aesthetic decomposition.

---

## Component Names

| Name | Role |
|------|------|
| **Conduit** | Request pipeline (orchestration channel) |
| **Arbiter** | Triage + clarification (was "Conduit") |
| **Warden** | Threat detection (user input + tool results) |
| **Sentinel** | Policy enforcement (LiteLLM guardrail plugin) |
| **Gate** | Input sanitization/improvement |
| **Artificer** | Code agent |
| **Scribe** | Writing agent |
| **Ranger** | Search agent (read-only, untrusted output) |
| **Warden-at-Arms** | Device/API control |
| **Forge** | Tool/agent creator (output starts at skull tier) |
| **Herald** | Voice/notifications (backlog) |

---

## Trust Tiers

Skull (in Forge, unusable) → T3 (sandboxed, read-only) → T2 (community/operator-approved) → T1 (operator-vetted, full tools) → T0 (built-in).

## Memory Scopes

global (all agents, all users) → team (same domain) → user (all agents, one user) → agent (one agent) → session (one conversation).

---

## Key Reference Files

| File | Purpose |
|------|---------|
| `ARCHITECTURE.md` | Full system design — read first |
| `conductor_security.md` (in /root/) | Threat model baseline — 50 concerns Stronghold must address |
| `Agentic_Design_Patterns.pdf` (in /root/) | Reference book for design patterns |
| `ADP_master_condensed_study_guide.md` (in /root/) | Condensed study guide of the ADP book |
