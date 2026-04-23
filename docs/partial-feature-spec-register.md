# Stronghold Partial-Feature Spec Register — 2026-04-23

Features that currently ship as code, routes, docs, or agent configs but whose implementation is a stub, a placeholder, or a subset of what the surrounding scaffolding advertises. Each entry: what's there today, what's missing, acceptance criteria to call it done.

Severity key: **S1** = security/integrity impact, **S2** = user-visible correctness, **S3** = architectural debt.

---

## Index

1. Empty-module feature stubs (18)
2. Half-implemented agents (Scribe, Warden-at-Arms, Forge)
3. Conduit execution-tier stubs (tenant policy, cluster pressure)
4. Schedules route: `run_schedule_now` fakes 202
5. MCP routes: `repo_url` deploy pipeline
6. MCP OAuth `/authorize` auto-approves any user_id
7. Builders learning: store methods just log
8. Builders learning: orphan diagnostic artifact
9. Artificer: `max_retries` advertised, never used
10. Agent store: `update()` ignores identity fields
11. Admin: `update_coin_settings` missing superadmin gate
12. Tournament: never records a battle
13. Canary: never routes traffic
14. Rate limiter: enforced only on webhooks
15. Skill catalog / Agent catalog: instantiated, never read
16. Guest peers (A2A outbound): defined, never instantiated
17. Agent cards (`agent_card.json`): published, never read
18. Missing tools referenced by agent configs (canvas, web_search, ha_*, etc.)
19. Arize tracing backend: docstring only
20. Bug-contract tests (§1.2 of code-smell catalog)

---

## 1. Empty-module feature stubs

**Severity:** S3 (architectural debt); S2 when the docstring implies a working module is being imported.

Eighteen source files exist only to host a single-line docstring announcing a feature. They would look like "coming soon" placeholders except that each appears in the import graph in at least one place (as a namespace hint for tests, `__init__` re-exports, or future wiring).

| File | Advertised feature |
|------|-------------------|
| `agents/cache.py` | "Prompt LRU cache" |
| `agents/exporter.py` | "GitAgent directory export" |
| `agents/identity.py` | "AgentIdentity parsing from agent.yaml" |
| `agents/importer.py` | "GitAgent directory import" |
| `agents/registry.py` | "Agent CRUD in PostgreSQL" |
| `agents/streaming.py` | "SSE streaming + tool-loop-to-SSE conversion" |
| `agents/forge/strategy.py` | "Forge agent: iterative tool/agent creation" |
| `agents/scribe/strategy.py` | "Scribe agent: research → draft → critique → edit" |
| `agents/warden_at_arms/strategy.py` | "Warden-at-Arms: real-world interaction + API discovery" |
| `api/middleware/auth.py` | "Auth middleware: extract AuthContext from request" |
| `api/middleware/tracing.py` | "Tracing middleware: create trace per request" |
| `api/routes/conductor.py` | "API route: conductor" |
| `config/defaults.py` | "Sensible defaults for all configuration fields" |
| `config/env.py` | "Environment variable resolution" |
| `tools/legacy.py` | "Legacy tool wrapper for Conductor migration" |
| `tracing/arize.py` | "Arize Enterprise tracing backend. Stub for now." |
| `tracing/prompts.py` | "PostgreSQL PromptManager implementation" |
| `tracing/trace.py` | "Backend-agnostic trace and span types" |

**Spec to finish (per file):**
1. Decide: promote or delete. Promotion candidates must back a roadmap item in `BACKLOG.md`; everything else is dead scaffolding.
2. For the stub strategies (§2), see Section 2.
3. For middleware (`api/middleware/auth.py`, `api/middleware/tracing.py`), consolidate the 17 route files' hand-rolled auth-header parsing (code-smell catalog §7.7) into the middleware. Acceptance: each route calls `request.state.auth` and `request.state.trace_context`, no route reads `request.headers["authorization"]` directly.
4. For `config/defaults.py` and `config/env.py`, absorb the 12 inline `os.environ.get()` calls cataloged in §7.19. Acceptance: `grep -rn "os.environ.get" src/stronghold/` returns 0 matches outside `config/`.
5. For `tracing/arize.py`, either implement the backend against the `TracingBackend` protocol with a feature flag in `StrongholdConfig`, or delete the file and remove references from ARCHITECTURE.md §7.
6. For the agents/* files, either wire the feature behind the stated name or delete the module.

**Acceptance (global):** each file is either removed from source control or exports at least one symbol that production code imports. `vulture src/stronghold/` with confidence 70 should find no class or function named after the module that isn't reached.

---

## 2. Half-implemented agents: Scribe, Warden-at-Arms, Forge

**Severity:** S2. These are three of the six named agents in ARCHITECTURE.md §2.4. Their `agent.yaml` files ship. Their SOUL.md personalities ship. Their strategy modules are docstring-only. In production they silently fall through to whatever generic strategy is registered under their stated `strategy:` name.

### 2.1 Scribe

- **What ships:** `agents/scribe/{agent.yaml, SOUL.md, agent_card.json}`; yaml says `strategy: plan_execute`.
- **What happens at runtime:** `plan_execute` is registered in `src/stronghold/agents/factory.py:225` as `ArtificerStrategy` — the *code-engineering* workflow (plan → write-file → pytest → mypy → commit). A user asking Scribe to "write a short story" gets ArtificerStrategy attempting to call `write_file` / `run_pytest`.
- **What's advertised:** `research → draft → critique → defend → edit committee` (ARCHITECTURE.md §2.5).
- **Spec to finish:**
  1. Implement `ScribeStrategy` in `src/stronghold/agents/scribe/strategy.py` as a committee pattern: researcher (web_search) → drafter (LLM) → critic (LLM second pass against rubric) → advocate (LLM rebuttal) → editor (final merge).
  2. Register it in `factory.py` under a new name, e.g. `scribe_committee`, and update `agents/scribe/agent.yaml` to point at it.
  3. Emit Phoenix spans per committee role.
  4. Acceptance: an integration test sends a writing prompt to `/v1/chat/completions` with `intent_hint: "writing"`, routes to Scribe, produces a non-empty `content`, and records five Phoenix spans (`scribe.research`, `scribe.draft`, `scribe.critique`, `scribe.advocate`, `scribe.edit`).

### 2.2 Warden-at-Arms

- **What ships:** `agents/warden-at-arms/agent.yaml`, SOUL.md; yaml says `strategy: react`; tools listed: `ha_control, ha_list_devices, ha_notify, api_call, runbook_execute`.
- **What happens at runtime:** `react` strategy is real, but **none of the five tools exist** — `container.py` registers only `github`, `file_ops`, `shell`, `workspace`, and the quality-gate tools. Any call through Warden-at-Arms will fail with "Tool not found" for every listed capability.
- **What's advertised:** "API surface discovery on initialization" + device control.
- **Spec to finish:**
  1. Build five tool executors in `src/stronghold/tools/`: `home_assistant.py` (HA_TOKEN env + REST), `api_call.py` (generic outbound HTTP behind SSRF block + warden scan of response), `runbook_execute.py` (reads a runbook spec, executes steps with per-step policy gate).
  2. Add corresponding `TOOL_DEF` entries and register them in `container.py` alongside `GITHUB_TOOL_DEF`.
  3. Implement "API surface discovery": on first call to an unknown host, fetch `/.well-known/openapi.yaml` (or `/openapi.json`), pass through Sentinel risk classifier, emit a generated skill into `SkillCatalog`.
  4. Acceptance: `/v1/chat/completions` with a Warden-at-Arms prompt triggers an `api_call` tool call that succeeds end-to-end against a local test HTTP server; subsequent discovery step creates a skill in the catalog.

### 2.3 Forge

- **What ships:** `agents/forge/strategy.py` (docstring stub). No `agent.yaml` either — `agents/` has `arbiter`, `archie`, `artificer`, `auditor`, `davinci`, `default`, `fabulist`, `frank`, `herald`, `mason`, `master-at-arms`, `quartermaster`, `ranger`, `scribe`, `warden-at-arms` — **no `forge/`**.
- **What happens at runtime:** Forge doesn't exist as an agent at all. Its strategy file is orphaned.
- **What's advertised:** Creates tools and agents. Output starts at ☠️ tier. Iterates `generate → scan → validate schema → test → iterate` (ARCHITECTURE.md §5.4).
- **Spec to finish:**
  1. Create `agents/forge/{agent.yaml, SOUL.md, agent_card.json}` with `strategy: forge_iterate`, trust_tier `t1 elevated`, tools `[file_ops, scanner, schema_validator, test_executor, prompt_manager]`.
  2. Build the missing tools: `schema_validator` (validates candidate agent.yaml / skill frontmatter), `test_executor` (runs the candidate in a sandbox — reuse `sandbox/deployer.py`), `prompt_manager` (tool-call wrapper around existing PromptManager).
  3. Implement `ForgeStrategy` in `src/stronghold/agents/forge/strategy.py` as the cited iteration loop.
  4. Ensure output agents/skills are saved with `trust_tier="skull"` and require operator approval before being reachable from `create_agents`.
  5. Acceptance: Forge can be invoked via chat with "create a new skill that summarizes a URL", returns a skill in skull tier, and attempting to use the skill from another agent fails until approved.

---

## 3. Conduit execution-tier override stack

**Severity:** S2 (correctness); S1 if cluster pressure is the only thing standing between a spike and LiteLLM saturation.

`src/stronghold/conduit.py:63–112` — `determine_execution_tier` docstring advertises a 4-step override stack. Two of the four are stubs:

- `_get_cluster_pressure()` (line 45–52) — "Stub: always returns False. Will be wired to real metrics later." Result: the cluster-pressure downgrade at line 98 never fires.
- `_apply_tenant_policy(tier, _tenant_id=None)` (line 55–60) — "Stub: returns tier unchanged. Will consult tenant config later." Caller at line 95 doesn't even pass `_tenant_id`. Tenant overrides in `StrongholdConfig` have no effect.

**Spec to finish:**
1. `_get_cluster_pressure`: read recent LiteLLM latency/error-rate from the router's `QuotaTracker` (or a new `ClusterMetrics` protocol). Returns `True` when P95 latency > 10s or 5xx rate > 5% over the last minute. Config thresholds in `StrongholdConfig.router.pressure`.
2. `_apply_tenant_policy`: accept `tenant_id`, look up `config.tenants[tenant_id].tier_overrides`, return the mapped tier or input tier if no override.
3. Update `determine_execution_tier` call site in `conduit.py:95` to pass `intent.tenant_id` (add field to `Intent` if missing).
4. Acceptance: unit tests for all 4 override-stack orderings; integration test that sets a tenant policy override in config and verifies the route picks it up.

---

## 4. `run_schedule_now` pretends to queue

**Severity:** S2.

`src/stronghold/api/routes/schedules.py:129–142` — the endpoint returns `202 Accepted` with `{"task_id": task.id, "status": "triggered"}` and nothing else happens. The comment admits: *"Record immediate execution intent — the Reactor or worker will pick it up. For now, return 202 Accepted to indicate the task has been queued."* No `record_intent` call, no reactor notification, no queue write.

Users see a success response and expect the schedule to fire; it doesn't.

**Spec to finish:**
1. Add `ScheduleStore.mark_due(task_id)` (updates `next_run_at = now`) or `Reactor.trigger_schedule(task_id)` (posts a synthetic `_schedule:<id>` event to the reactor queue).
2. Call from `run_schedule_now` before the 202 response.
3. Confirm via `GET /schedules/{id}/history` that an execution was recorded within the next reactor tick.
4. Acceptance: integration test that creates a schedule with `next_run_at` 1 hour out, POSTs `/run`, and observes a history entry within 2 seconds.

---

## 5. MCP `deploy_server` repo-url path returns a fake pipeline

**Severity:** S2.

`src/stronghold/api/routes/mcp.py:274–295` — when a caller POSTs `deploy_server` with `{"repo_url": "..."}`, the route returns `202 Accepted` with a body shaped like a pipeline status:

```json
{"pipeline": {"clone": "pending", "scan": "pending", "build": "pending",
              "deploy": "pending", "discover": "pending"}, ...}
```

No clone happens. No scan, build, deploy, or discover step exists. The comment says "full implementation in v1.1". The response is indistinguishable from a real async pipeline; clients polling will never see status changes.

**Spec to finish:**
1. Either remove the `repo_url` branch and return 501 Not Implemented, or:
2. Build the pipeline: clone → `bandit`+`ruff` scan → container build (reuse `sandbox/deployer.py` infra) → deploy via `K8sDeployer` → `/tools` discovery → skill generation.
3. Persist pipeline state (add `mcp_pipeline_runs` table) so `GET /mcp/pipeline/{id}` reflects real progress.
4. Acceptance: point at a sample MCP server repo, observe all five steps complete, and confirm the resulting MCP server is listable via `GET /mcp/servers`.

---

## 6. MCP OAuth `/authorize` auto-approves arbitrary user IDs

**Severity:** S1 — this is a security bug, not just a stub.

`src/stronghold/mcp/oauth/endpoints.py:124–158` — the authorization endpoint takes `user_id` and `tenant_id` **from query parameters** and mints an auth code for that identity. Comment: *"Auto-approve for now (production: redirect to consent UI). The user_id/tenant_id would come from the session in production."*

Any client that knows a registered `client_id` + valid `redirect_uri` + PKCE challenge can request an auth code for any user in any tenant by appending `?user_id=victim@corp.com&tenant_id=corp`.

**Spec to finish:**
1. Read the current session (cookie via `CookieAuthProvider`) and require it to be authenticated.
2. Derive `user_id` / `tenant_id` from the session, never from query params.
3. Render a consent HTML page (template under `src/stronghold/dashboard/`) that shows requested scopes and the `client_name` from the DCR record.
4. Only issue an auth code on POST from the consent form with CSRF token + session match.
5. Acceptance: integration test that an unauthenticated `/oauth/authorize` redirects to login; an authenticated request renders consent; POST without matching session returns 403; successful POST returns the auth code and records a consent audit-log entry.

---

## 7. Builders learning: store methods only log

**Severity:** S2. The agent-roster doc calls this "BuildersLearningStrategy" and ARCHITECTURE.md §4.4 describes a self-improving memory loop. The strategy *claims* to store learnings.

`src/stronghold/agents/strategies/builders_learning.py:305–324` —

```python
async def _store_frank_learning(self, ...) -> None:
    """Store Frank learning — logs for now, memory store in follow-up."""
    logger.info("Frank learning: ...")

async def _store_mason_learning(self, ...) -> None:
    """Store Mason learning — logs for now, memory store in follow-up."""
```

Nothing is written to `LearningStore`. The "learning" strategy doesn't learn.

**Spec to finish:**
1. Inject `LearningStore` into `BuildersLearningStrategy.__init__` (via the factory).
2. In `_store_frank_learning`: construct a `Learning` with `task_type="builders.recon"`, `scope=MemoryScope.AGENT`, `agent="frank"`, and relevant keys (repo state summary, failure patterns). Call `learning_store.add(learning)`.
3. Same for `_store_mason_learning` (task_type `builders.diagnostics`).
4. Tag both so `LearningPromoter.check_and_promote` can surface them.
5. Acceptance: after one Frank run and one Mason run, `SELECT COUNT(*) FROM learnings WHERE agent IN ('frank','mason')` increases by ≥ 2; subsequent runs retrieve the prior learning via `find_relevant`.

---

## 8. Builders learning: orphan diagnostic artifact

**Severity:** S3.

`src/stronghold/agents/strategies/builders_learning.py:116–126` — builds a diagnostic dict that is explicitly discarded with `_ = {...}` and a comment `TODO: wire to orchestrator`. Logs "Frank diagnostic produced" and moves on.

**Spec to finish:**
1. Wire to `orchestrator/pipeline.py` — post a `PipelineEvent` of kind `diagnostic` with the dict as payload.
2. Store in `outcomes` or a new `diagnostics` table keyed by `run_id`.
3. Surface on the Mason dashboard per run.
4. Acceptance: each Frank run produces a row visible via `GET /v1/stronghold/pipeline/{run_id}/diagnostics`. Delete the `_ =` anti-pattern; linter sees no unused value.

---

## 9. Artificer: `max_retries_per_phase` is dead config

**Severity:** S3; S2 because it implies per-phase retry which isn't implemented.

`src/stronghold/agents/artificer/strategy.py:42–48` — constructor takes `max_retries_per_phase: int = 2`, stores as `self.max_retries`. Class docstring (lines 30–40) promises:

> 2. For each phase:
>    c. If fail: fix and recheck (max 2 retries)
>    d. Commit when green

The `reason()` body implements a single generic tool loop with `max_phases * 3` LLM rounds (line 99). There is no phase concept — no plan decomposition, no per-phase retry, no green-gate commit. `self.max_retries` is never read (vulture flagged this).

**Spec to finish:**
1. Parse the plan output from `_plan()` into discrete phases (numbered list → `list[Phase]`).
2. For each phase: run tool loop → check `run_pytest` / `run_ruff` / `run_mypy` exit status → if red, give the model the failure log and retry, up to `self.max_retries` times → commit via the `git_commit` tool on green.
3. Update the status callback to emit `phase_started`, `phase_retry`, `phase_committed` events.
4. Acceptance: integration test with a plan containing 3 phases sees 3 `phase_committed` events and at least one retry surfaced.

---

## 10. `InMemoryAgentStore.update` silently drops identity changes

**Severity:** S2.

`src/stronghold/agents/store.py:144–167` — `update()` accepts a dict and only applies `soul_prompt` and `rules`. Comment: *"For identity field updates, we'd need to rebuild the Agent (AgentIdentity is frozen). For now, update soul/rules only."*

The admin dashboard's agent edit form sends `{model, tools, trust_tier, priority_tier, max_tool_rounds, ...}` — these are silently discarded. The API returns 200 with the updated object (which still has old values), so the user thinks the change took effect.

**Spec to finish:**
1. Rebuild the `AgentIdentity` dataclass with the new values via `dataclasses.replace` on a non-frozen copy, then re-freeze.
2. Validate each field against its allowed domain (trust_tier ∈ {t0..t3, skull}, priority_tier ∈ {P0..P5}, model exists in router, tools exist in registry).
3. Persist to `PgAgentRegistry` when available.
4. Return the updated object; reject unknown fields with 400.
5. Acceptance: a PUT to `/v1/stronghold/agents/{name}` with new `trust_tier` and `max_tool_rounds` is reflected on a follow-up GET; an invalid `trust_tier` returns 400 with a structured error.

---

## 11. `update_coin_settings` missing superadmin gate

**Severity:** S1.

`src/stronghold/api/routes/admin.py:1240–1270` — any admin (`_require_admin`, not `_require_superadmin`) can change the banking rate that applies to every wallet. TODO comment admits the gate is missing.

**Spec to finish:**
1. Add `_require_superadmin(request)` (checks `"superadmin"` in auth.roles or equivalent). Define the role in `auth_composite` / Casbin config.
2. Wrap `update_coin_settings` with it.
3. Add an audit-log entry per change (old → new).
4. Acceptance: as admin-but-not-superadmin, PUT returns 403; as superadmin, succeeds and appears in audit log.

---

## 12. Tournament system: instantiated, never records a battle

**Severity:** S3.

`Tournament` is fully implemented (`src/stronghold/agents/tournament.py`) with Elo ratings, promotion checks, and leaderboard queries. It's wired into `Container.tournament` at `container.py:444`. But **no production code calls `record_battle`**. The only reference is `triggers.py:125` calling `get_stats()` for a periodic log.

ARCHITECTURE.md §2.6 ("Routing: Conduit + Tournaments") implies tournaments feed routing decisions.

**Spec to finish:**
1. On ambiguous requests (the arbiter path in `conduit.py:266–285`), run a pair of candidate agents, judge with the `judge_model`, record via `Tournament.record_battle`.
2. Expose `Tournament.check_promotions` on a nightly trigger (add to `triggers.py`).
3. Surface leaderboard at `/v1/stronghold/tournament` (already has route scaffolding? — verify).
4. Acceptance: at least one `battles` row recorded per ambiguous request; promotion threshold crossing moves an agent's `trust_tier` up.

---

## 13. Canary manager: nothing actually routes through the canary

**Severity:** S2 — "canary deployments" is a feature name used in `BACKLOG.md`.

`src/stronghold/skills/canary.py` implements staged canary rollout with `should_use_new_version(skill_name, org_id)` returning a bool based on traffic %. It's never called. `record_result()` is also never called. The only canary interaction is a trigger that polls `check_promotion_or_rollback` (triggers.py:144), which cannot fire sensibly because no results have been recorded.

**Spec to finish:**
1. In the skill dispatcher (wherever skills are invoked — `skills/forge.py` or a `SkillRegistry.get` wrapper), consult `canary_manager.should_use_new_version(skill_name, auth.org_id)` before picking the version.
2. After invocation, call `canary_manager.record_result(skill_name, success=ok, org_id=auth.org_id)`.
3. Ensure the existing promotion/rollback trigger now has real data to act on.
4. Acceptance: deploy a canary at 10% traffic; run 1000 requests; observe approximately 100 go to new version, failure-rate trigger promotes or rolls back as configured.

---

## 14. Rate limiter enforced only on webhooks

**Severity:** S1 — classifier route ingests user text without throttling.

`container.py:267–282` picks a Redis or in-memory `RateLimiter`. The only enforcement sites are `api/routes/webhooks.py:171, 252` (two webhook handlers). `chat.py`, `agents.py`, `admin.py`, etc. have no rate-limit check. `conduit.py`'s `route_request` doesn't consult the limiter at all.

Config section `config.rate_limit` with `requests_per_minute` gives the impression of a global cap; in reality it caps a fraction of one route pair.

**Spec to finish:**
1. Hoist rate-limit enforcement into `api/middleware/auth.py` (pair with the auth extraction already planned in §1).
2. Default key: `auth.org_id + auth.user_id`; unauthenticated requests keyed on remote IP.
3. Per-route overrides (config-driven) for expensive endpoints.
4. Acceptance: `config.rate_limit.requests_per_minute = 10` + 20 requests from one user in 60s returns at least 10 × 429; headers contain `X-RateLimit-Remaining`.

---

## 15. `SkillCatalog` / `AgentCatalog` instantiated but unreferenced

**Severity:** S3.

`container.py:337` constructs `skill_catalog = SkillCatalog()`, passes it into `Container(..., skill_catalog=skill_catalog, ...)`. `grep -rn "skill_catalog\." src/stronghold/` returns zero matches outside construction. `ResourceCatalog` is in the same boat. `AgentCatalog` (`src/stronghold/agents/catalog.py`) isn't even instantiated — vulture flags its class, `from_identity`, `list_by_trust_tier`, `list_by_priority_tier` as unused.

ARCHITECTURE.md §2.7/§5.3 references "catalog" as a first-class discovery surface.

**Spec to finish:**
1. Decide product direction: catalogs back the Marketplace + dashboard skill browser, or they're cruft.
2. If product: populate on startup from `agents/` and `skills/` dirs, expose via `/v1/stronghold/catalog/{agents,skills,resources}`, consult in `api/routes/marketplace.py` browse flows.
3. If not: delete `agents/catalog.py`, `skills/catalog.py`, `resources/catalog.py`, and the container fields.
4. Acceptance: either each catalog has ≥ 3 call sites outside construction, or vulture at 60% confidence has zero matches for the class names.

---

## 16. `GuestPeerRegistry` (A2A outbound) defined, never instantiated

**Severity:** S3.

`src/stronghold/a2a/guest_peers.py:85–135` defines `GuestPeerRegistry` with `register_peer`, `remove_peer`, `list_peers`, `delegate`. None are reachable from production code (all flagged by vulture). ADR-K8S-029 references it; container does not instantiate it.

**Spec to finish:**
1. Wire into `Container` (new field `guest_peers`), populated from `config.a2a.guest_peers`.
2. Add outbound A2A tool executor (`tools/a2a_delegate.py`) that consults the registry before delegating.
3. Audit every outbound delegation via `AuditLog`.
4. Enforce cross-tenant prohibition at the registry level.
5. Acceptance: configure one guest peer in YAML, have Artificer delegate a task to it via a tool call, observe an `AuditLog` entry with `action="a2a_delegate"`.

---

## 17. `agent_card.json` published per agent, never consumed

**Severity:** S3.

Every agent dir under `agents/` ships a JSON file like `agents/arbiter/agent_card.json` with an A2A v2024-11-05 card (capabilities, skills, trust tier, protocolVersion). `grep -rn "agent_card" src/stronghold/` returns zero matches. The cards aren't served, parsed, or validated.

The `protocolVersion` field implies A2A interoperability; in reality only the YAML config is loaded by `agents/factory.py`.

**Spec to finish:**
1. Add `/v1/stronghold/agents/{name}/card` route that returns the contents of `agent_card.json`.
2. Validate against the A2A schema on agent load; fail fast if malformed.
3. Keep in sync with `agent.yaml` — either generate the card from the yaml at build time, or validate they match on load (tools list, trust_tier, model).
4. Acceptance: A2A-capable client fetches `/agents/arbiter/card` and gets a v2024-11-05 card matching the yaml; mismatched card → startup error.

---

## 18. Agent configs reference tools that don't exist

**Severity:** S2.

Spot-check of registered vs declared tools:

| Agent | `agent.yaml` tools declared | Registered in `container.py` |
|-------|------------------------------|------------------------------|
| davinci | `canvas` | missing |
| scribe | `file_ops, web_search` | `web_search` missing |
| ranger | `web_search, database_query, knowledge_search` | all three missing |
| warden-at-arms | `ha_control, ha_list_devices, ha_notify, api_call, runbook_execute` | all five missing |
| artificer (ARCHITECTURE §2.4) | `file_ops, shell, test_runner, lint_runner, git` | `test_runner`, `lint_runner`, `git` missing (replaced by `run_pytest`, `run_ruff_check`, implicit) |
| forge (ARCHITECTURE §2.4) | `scanner, schema_validator, test_executor, prompt_manager` | all missing |

Running these agents produces "tool not found" or the agent just can't do the thing its description promises.

**Spec to finish:**
1. Implement or rename each missing tool so that every `agent.yaml` tool is satisfied by a `TOOL_DEF` in `src/stronghold/tools/`.
2. Add a startup-time check: for each agent in `agents_dir`, verify all declared tools resolve against `ToolRegistry`. Fail loud on mismatch.
3. Update ARCHITECTURE.md §2.4 to match reality.
4. Acceptance: startup log lists "Tool parity check: ok (N agents × M tools)" or aborts.

---

## 19. Arize tracing backend: 1-line docstring

**Severity:** S3. Phoenix is the real backend; Arize is advertised as enterprise.

`src/stronghold/tracing/arize.py` contains only `"""Arize Enterprise tracing backend. Stub for now."""`. README/ARCHITECTURE name-check Arize. Container instantiates `PhoenixTracingBackend`; there's no switch to Arize.

**Spec to finish:**
1. If on the roadmap: implement `ArizeTracingBackend` against `TracingBackend` protocol, select via `config.tracing.backend = "arize" | "phoenix"`.
2. Otherwise: delete the file and remove references.
3. Acceptance: config value toggles backend at startup; Phoenix and Arize both pass the existing `TracingBackend` contract tests.

---

## 20. Bug-contract tests — specs already written

**Severity:** S1 (seven known live vulnerabilities).

Already enumerated in `docs/code-smell-catalog-2026-04-23.md §1.2`. Each inverted assert in `tests/security/test_security_audit_2026_03_30.py` encodes a required fix. The spec for each is the test itself — when the fix ships, the test's assertion flips and the `BUG CONFIRMED` comment is deleted.

Rollup:
- C1 (line 160): add `org_id` to upsert conflict key in `PgAgentRegistry`.
- C2 (line 349): reject empty caller `org_id` in `get/delete/list`.
- H2 (line 392): forbid `/` in `org_id` or use delimiter-aware parsing for session IDs.
- H3 (line 441): Warden must scan the middle of long content, not only head+tail windows.
- H4 (line 485): Warden L3 must return `"inconclusive"` (not `"safe"`) on LLM exceptions.
- H6 (line 726): Warden must not exit early when the first 200 chars look like code.
- Q1 (line 972): `PgQuotaTracker.record_usage` signature regression guard.

---

## Priority rollup

Top security items (S1): 6, 11, 14, and all seven bug contracts in 20.

Top user-visible correctness (S2): 2 (Scribe/Warden-at-Arms falling through), 3 (tier overrides), 4 (run_schedule_now), 5 (MCP repo_url), 7 (builders learning not stored), 9 (Artificer no-retry), 10 (agent update drops fields), 13 (canary doesn't route), 18 (missing tools).

Architecture debt (S3): 1 (empty modules), 8 (orphan diagnostic), 12 (tournament), 15 (catalogs), 16 (guest peers), 17 (agent cards), 19 (Arize).

**Recommended sequence:**
1. Ship the bug contracts (§20) — fixes are scoped and already have tests.
2. Close OAuth consent (§6) and superadmin gate (§11) — remaining S1 items.
3. Hoist rate limiting (§14) into shared middleware (pairs with §1 middleware consolidation).
4. Fix `AgentStore.update` (§10) and `run_schedule_now` (§4) — both return-200 lies that mislead users.
5. Decide fate of Scribe / Warden-at-Arms / Forge (§2) — the architecture doc needs to stop overselling regardless.
6. Clean up the S3 tier per roadmap.
