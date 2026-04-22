# Production Readiness Audit — Stronghold

**Branch:** `claude/audit-production-readiness-lakGr`
**Date:** 2026-04-21
**Scope:** production readiness, lifelikeness, code quality, spec coverage

## Headline

**Not production-ready.** The scaffolding is substantial and well-tested (257 src files / 33K LOC, 339 test files / 67K LOC, ~3,995 tests passing), but three of the eight headline innovations in ARCHITECTURE.md §1.1 are missing or dead code, and two of the six shipped specialist agents have no strategy implementation.

| Axis | Grade | Notes |
|---|---|---|
| Lint (ruff check + format) | **Pass** | 257 files clean |
| Type check (mypy --strict) | **Skipped** | mypy 1.20.1 internal error, not a code defect |
| Bandit (medium+) | **Pass** | 3 findings, all false positives (whitelisted dynamic identifiers in pg_outcomes / profile) |
| Tests | **Pass\*** | 3,993 passed, 16 failed, 44 skipped, 6 xfailed. All 16 failures are environmental (`tests/tools/test_workspace.py` — git needs user.email/name in sandbox) |
| Spec coverage | **~60%** | See gaps below |

## Lifelikeness — real vs. scaffold

Real, substantive implementations:
- `conduit.py` 767 lines — full classify → tier → quota precheck → route → sufficiency → dispatch pipeline
- `agents/base.py` 531 lines — traced 12-step `handle()` with warden scans, context build, strategy.reason, RCA, learnings, outcome, session save
- `agents/artificer/strategy.py` 249 lines — multi-phase plan → execute → fix → commit loop with real tool calls
- `security/warden/detector.py` — 4-layer scanner (regex → heuristic → semantic → optional LLM) with ReDoS timeout and Unicode NFKD normalization
- `security/sentinel/policy.py` 258 lines — real pre/post hooks: permission + schema repair + warden + PII + token optimize + audit
- `router/scorer.py` + `scarcity.py` — scarcity formula `1/ln(remaining)` correctly ported, priority multiplier, strength/speed bonuses
- `classifier/engine.py` — three-phase keyword → LLM fallback → complexity
- `memory/episodic/tiers.py` — 7-tier weight bounds with REGRET floor enforcement
- `agents/tournament.py` 236 lines — complete Elo system with promotion thresholds
- `persistence/pg_*.py` — full async asyncpg implementations for prompts, learnings, outcomes, sessions, audit, quota, agents

Pure placeholder files (docstring only, no code):
- `src/stronghold/agents/forge/strategy.py` (1 line)
- `src/stronghold/agents/scribe/strategy.py` (1 line)
- `src/stronghold/agents/warden_at_arms/strategy.py` (1 line)
- `src/stronghold/agents/importer.py` (1 line) — claimed module for GitAgent import
- `src/stronghold/agents/exporter.py` (1 line) — claimed module for GitAgent export
- `src/stronghold/agents/registry.py` (1 line) — claimed "Agent CRUD in PostgreSQL"

Because `factory.py:194-228` only registers `react`, `delegate`, `builders_learning`, `plan_execute`, and `artificer` strategies, any agent declaring an unregistered strategy falls back to `DirectStrategy` (single LLM call, no tools). Scribe's `agent.yaml` declares `strategy: plan_execute`, which resolves to `ArtificerStrategy` (`factory.py:225`) — Scribe therefore runs the code-engineering workflow (pytest/ruff/mypy/bandit) instead of writing, which is incorrect for a creative-writing agent.

## Spec coverage — ARCHITECTURE.md vs. src

| Architecture claim | Status | Evidence |
|---|---|---|
| §1.1 #1 Scarcity routing | Implemented | `router/scarcity.py:27-52` |
| §1.1 #2 Self-improving memory | Implemented | `memory/learnings/{extractor,promoter,approval}.py` wired in `agents/base.py:408-444` |
| §1.1 #3 7-tier episodic | Implemented | `memory/episodic/tiers.py:16-19` clamps REGRET ≥0.6 |
| §1.1 #4 Defense-in-depth | Implemented | Warden L1-L3 + Sentinel pre/post |
| §1.1 #5 Skill Forge | **Missing** | No `agents/forge/` dir; `src/stronghold/agents/forge/strategy.py` is 1-line docstring; no Forge agent wired |
| §1.1 #6 Multi-intent parallel dispatch | **Dead code** | `classifier/multi_intent.py:13` detects, but `conduit.py` never calls it — no `asyncio.gather`, no subtask split (grep confirms zero call sites outside `engine.py:124`) |
| §1.1 #7 Task-type speed bonuses | Implemented | `router/speed.py`, `scorer.py:51` |
| §1.1 #8 Tournament evolution | **Dead code** | `Tournament()` instantiated in `container.py:444`; `record_battle` / `check_promotions` only invoked from `tests/test_new_modules.py` — no production call site, no persistence to `tournaments` table mentioned in §4.1 |
| §2.4 Forge agent | **Missing** | No agent dir, no strategy |
| §2.4 Scribe committee | **Missing** | No sub-agent definitions; strategy falls through to ArtificerStrategy |
| §2.6 Dynamic intent creation on import | **Missing** | `agents/intents.py:10-17` — hardcoded static dict, no `add_intent` API |
| §5.2 Sentinel as LiteLLM guardrail | **Unverified** | Sentinel class has pre/post methods but no LiteLLM guardrail registration observed; grep for `guardrail`, `register_hook` returns nothing |
| §5.4 Forge iteration loop | **Missing** | `skills/forge.py` exists as a skill-building helper but no agent-level iteration/trust-tier promotion |
| §9.4 Multi-tenant namespace isolation | **Partial** | `memory/scopes.py` exists; per-query scope enforcement not audited for all retrieval paths |
| §10 GitAgent import/export | **Partial** | Logic exists in `agents/store.py` and `agents/factory.py:_parse_agent_dir`, but the promised `agents/importer.py` / `exporter.py` modules are 1-line stubs (API shape drift from docs) |
| §3.4 Gate clarifying questions | Implemented | `security/gate.py` + `api/routes/chat.py:101-123` |
| §2.9 Reactor 1000Hz loop | Implemented | `events.py`, `triggers.py` |

## Security review

- `conduit.py:47-52`, `_apply_tenant_policy` `:55-60` — explicitly documented stubs (`return False`, `return tier`). Cluster pressure and tenant-tier overrides are no-ops.
- `agents/strategies/builders_learning.py:116` — `# Step 5: Store diagnostic artifact (TODO: wire to orchestrator)`
- `api/routes/admin.py:1244` — `TODO: Gate on superadmin role once trust tiers are wired`
- `security/auth_demo_cookie.py:34-40` — warns if HS256 key < 32 bytes, then accepts it. Tests exercise with 7- and 11-byte keys (visible in test warnings). Should reject in non-test mode.
- `security/tool_policy.py` — Casbin policy loads with a catch-all `except Exception: logger.warning(...); tool_policy = None` (`container.py:324-329`); if the policy file is malformed the system runs with **no policy enforcement** and only logs a warning. Fail-open on a security primitive.
- `pg_outcomes.py:114,173`, `profile.py:175` — Bandit B608 medium-severity warnings; all are whitelist-gated dynamic SQL identifiers (safe, but the `# noqa` comments hide future regressions).
- All inline SQL uses `$1`-style parameters (asyncpg). No string concatenation of user data into queries found.
- `tools/shell_exec.py` uses an allowlist but invokes `asyncio.create_subprocess_shell`; if a future caller bypasses the allowlist check the shell is exposed — worth switching to `create_subprocess_exec` with an argv list.

## Code quality signals

- Consistent layering: protocols → types → implementations → DI (`container.py`). Business logic imports protocols; DI wires impls. Adheres to CLAUDE.md rule #5.
- `container.py` has grown to 530 lines with many `Any`-typed fields (`coin_ledger`, `tournament`, `canary_manager`, `orchestrator`, `learning_approval_gate`, …) — half the container state uses `Any = None`, losing most of the benefit of the protocol layer for those components.
- `conduit.route_request` is 550 lines — several responsibilities (classify, tier, consent, quota, sufficiency, dispatch, trace) in one method. Functional but harder to verify than the protocol-per-concern goal in ARCHITECTURE §1.2.
- Test infrastructure is real: `tests/fakes.py`, `tests/factories.py`, protocol-parity fakes; tests import real classes (InMemoryLearningStore, Warden, Gate) per CLAUDE.md testing rule #1.

## Top production blockers

1. **Implement or remove Forge.** §1.1 #5 is marketed as a headline innovation; no code exists. Either build it or strike from docs.
2. **Wire multi-intent parallel dispatch.** `classifier.multi_intent.detect_multi_intent` is called by nothing; `Conduit` forces a single intent. Either add the parallel dispatch in `Conduit.route_request` step 2 or remove §1.1 #6 and §2.6.
3. **Wire Tournament into the runtime.** Currently instantiated but never called outside tests. Add a canary/tournament dispatch path or remove from ARCHITECTURE.
4. **Implement Scribe / Warden-at-Arms / (Forge) strategies.** Replace 1-line docstring files. Register each in `_register_custom_strategies`.
5. **Persistent Tournament + audit storage.** No `tournaments` table migration; `Tournament` is in-memory only, contradicting §4.1.
6. **Promote HS256 short-key warning to a startup-blocking error** when not running in test mode.
7. **Sentinel ↔ LiteLLM guardrail hook** — verify or implement per §5.2.
8. **Fail-closed on tool policy load.** In `container.py:327-329`, re-raise on malformed Casbin config in prod; only fall back in dev.
9. **Delete or fill importer.py / exporter.py / registry.py.** Currently the promised public API doesn't exist; logic lives in `agents/store.py` and `agents/factory.py`.
10. **Decompose `conduit.route_request`.** 550-line monolith — split into `_classify`, `_resolve_consent`, `_check_quota`, `_check_sufficiency`, `_dispatch` helpers for testability.

## Positive signals

- Warden `detector.py` handles homoglyph / NFKD bypass + 0.5 s ReDoS timeout — solid.
- `agents/base.py` pipeline is fully traced and end-to-end covered by tests.
- RBAC is config-driven (`types/auth.PermissionTable`) — closes Conductor gap #6.
- Real asyncpg migrations auto-applied at boot (`persistence/get_pool → run_migrations`).
- Scarcity + Elo + 7-tier memory are genuinely implemented to the level claimed.
- 3,993 passing tests, 85%+ coverage gates enforced per CI tier (`pyproject.toml`).

---

**Bottom line:** the *runtime and security spine* (conduit, base agent, Warden, Sentinel, router, classifier, memory, persistence) is production-shaped — good. The *ecosystem layer* (Forge, specialist strategies, tournament evolution, dynamic intent creation, multi-intent dispatch, GitAgent importer/exporter) is largely ARCHITECTURE fiction. Ship requires either building those or trimming the architecture to match reality.
