# Stronghold Code-Smell Catalog — 2026-04-23

Scan of `src/stronghold/` (257 files, ~21.8K LOC) plus `tests/` (339 files). Tools used: `ruff`, `mypy --strict`, `bandit -l`, `vulture`, `radon cc/mi`, plus targeted grep passes. Test suite was not executed (Python 3.11 in this environment; project requires 3.12+).

This catalog is diagnostic only. Remediation is deferred — each entry is a pointer, not a ticket.

---

## 0. Top-line counts

| Signal                                   | Count   |
|------------------------------------------|---------|
| `ruff check` findings                    | 0       |
| `mypy --strict` errors                   | 295 (56 files)¹ |
| `bandit -l` findings                     | 27      |
| `vulture` ≥80% confidence findings       | 16      |
| Source modules with no test-import       | 28      |
| `except Exception`-catching blocks       | 96      |
| Lazy imports marked `noqa: PLC0415`      | 158     |
| `typing.Any` annotations                 | 139     |
| TODO/FIXME markers in production code    | 2       |
| `pytest.xfail(strict=False)` tests       | 6       |

¹ Most mypy errors are environment-only (`fastapi`, `httpx`, `jwt`, `argon2` stub lookups) that a real CI venv resolves. The non-stub errors are called out in §2.

---

## 1. Broken / buggy code

### 1.1 Real type error in `conduit.py` (mypy, non-stub)

`src/stronghold/conduit.py:112`

```python
current_tier: str = ...
return replace(intent, tier=current_tier)    # Intent.tier is Literal["P0"..."P5"]
```

`Intent.tier` is `Literal["P0","P1","P2","P3","P4","P5"]` but `current_tier` is typed plain `str`. `dataclasses.replace` accepts any value at runtime, so a typo in `_apply_tenant_policy` (lines 55–60, currently a no-op) or an unexpected agent `priority_tier` would produce an `Intent` with an invalid tier literal that downstream code uses unchecked.

### 1.2 Known security bugs documented as tests

`tests/security/test_security_audit_2026_03_30.py` contains seven **inverted** asserts — the test passes only while the bug is still live. They are *contracts for a fix*, not regressions:

| Line | Bug summary                                                                                          |
|------|------------------------------------------------------------------------------------------------------|
| 160  | Upsert conflict key lacks `org_id` → cross-tenant overwrite possible                                |
| 349  | Empty caller `org_id` returns an org-scoped agent                                                    |
| 392  | `org_id` containing `/` enables prefix-collision access across orgs                                  |
| 441  | Warden scan window gap (bytes 10240..len-2048) lets injections through                               |
| 485  | Warden L3 LLM classifier returns `label="safe"` on exception (fail-open)                             |
| 726  | Code prefix in first 200 chars bypasses full scan                                                    |

These are **known broken behaviors in production code** — the test file calls them "BUG CONFIRMED". Each one needs its fix shipped before the matching assert is flipped.

### 1.3 Unused `type: ignore` in `mcp/deployer.py:35`

Mypy reports `Unused "type: ignore" comment`. The ignore is stacked on a `kubernetes` import which then fails with `import-not-found` — the existing ignore doesn't cover the right error code. Either the ignore comment is stale (fix by removing) or the code assumed a different kubernetes stub package was pinned.

### 1.4 `Any` leaking through `LiteLLMClient`

`src/stronghold/api/litellm_client.py:121,132` — two methods declared as returning `dict[str, Any] | Exception` actually `return <something>` whose type is `Any`, defeating the union. Mypy: `Returning Any from function declared to return "dict[str, Any] | Exception"`.

### 1.5 `Any` leaking through `MCPOAuthStore`

`src/stronghold/mcp/oauth/store.py:21,25,30` — three functions annotated `-> str` / `-> bool` return `Any` from argon2 calls with no cast. These affect OAuth token handling so the missing typing is worth closing.

---

## 2. Dead / stub code

### 2.1 Three agent strategies are single-line docstring stubs

ARCHITECTURE.md documents these as first-class agents, but the implementation is absent:

| File                                                       | LOC | Content                 |
|------------------------------------------------------------|-----|-------------------------|
| `src/stronghold/agents/forge/strategy.py`                  | 1   | `"""Forge agent…"""`    |
| `src/stronghold/agents/warden_at_arms/strategy.py`         | 1   | `"""Warden-at-Arms…"""` |
| `src/stronghold/agents/scribe/strategy.py`                 | 1   | `"""Scribe agent…"""`   |

`Artificer` is real (248 LOC). Anything that tries to `create_agents(...)` for Forge/Scribe/Warden-at-Arms and reach a strategy will crash or silently fall back — see §2.2.

### 2.2 `factory.py` swallows `ImportError` on every strategy registration

`src/stronghold/agents/factory.py:196–228` wraps each `register_strategy(...)` in `try/except ImportError: pass`. If any strategy module has a bug that manifests as `ImportError` (typo, circular import, missing dep), the registration silently no-ops. `create_agents()` then builds an agent whose strategy is `None`, and the failure only surfaces at `agent.handle()` with a confusing `NoneType` error — nowhere near the real cause. Either let `ImportError` propagate or log with the module name at WARNING.

### 2.3 Orphaned diagnostic artifact

`src/stronghold/agents/strategies/builders_learning.py:116–126` builds a "diagnostic artifact" dict into `_` so ruff F841 stays quiet, with the comment `TODO: wire to orchestrator`. The dict is constructed every call, logged only as a constant string `"Frank diagnostic produced"`, then discarded. Either wire it or delete the dead construction.

### 2.4 Vulture ≥80%-confidence dead items (16)

Mostly unused exception-unpack tuples (`exc_tb`), unused dataclass args surfaced as "unused variable", and a handful of assign-and-forget locals:

- `src/stronghold/agents/auditor/checks.py:320` — `commit_count` (100%)
- `src/stronghold/protocols/agent_pod.py:60,88,89,91,109,110` — unused positional fields
- `src/stronghold/protocols/data.py:30`, `memory.py:83`, `mcp.py:70`, `secrets.py:56,79`
- `src/stronghold/tracing/{noop,phoenix_backend}.py` — `exc_tb` unused in `__aexit__`
- `src/stronghold/tools/decorator.py:22` — `required_permissions` assigned, never read

These are near-certainly real (protocol arg placeholders, `exc_tb` idiom). The auditor `commit_count` at line 320 is worth a second look — it's the only 100%-confident one that sits in branching logic.

(Vulture at 60% confidence emits 467 findings — dominated by FastAPI route handlers reached via decorators, which the tool misses. Noise.)

### 2.5 Module stubs in `config/` and `tracing/`

`config/defaults.py`, `config/env.py`, `tracing/prompts.py`, `tracing/trace.py`, `tracing/arize.py` have zero test imports (§3). They may still be referenced by production code, but nothing locks down their shape — they're "written once, never re-entered".

---

## 3. Untested modules

Detected by grepping `tests/` for `from <module>` / `import <module>` — **28 source modules have zero test references.** Grouped by subsystem:

| Subsystem   | Modules                                                                                                    |
|-------------|------------------------------------------------------------------------------------------------------------|
| persistence | `pg_audit`, `pg_outcomes`, `pg_sessions`                                                                   |
| tracing     | `prompts`, `trace`, `arize`                                                                                |
| config      | `defaults`, `env`                                                                                          |
| protocols   | `spec`, `llm`                                                                                              |
| security    | `warden/patterns`                                                                                          |
| api         | `routes/conductor`, `middleware/tracing`, `middleware/auth`                                                |
| builders    | `runtime`, `orchestrator`, `services`                                                                      |
| agents      | `streaming`, `cache`, `importer`, `identity`, `registry`, `exporter`, `forge/strategy`, `warden_at_arms/strategy`, `scribe/strategy` |
| memory      | `scopes`                                                                                                   |
| tools       | `legacy`                                                                                                   |

Persistence `pg_*` is intentionally excluded from coverage in `pyproject.toml` (needs a live Postgres), so those three are expected. The agent-strategy stubs (§2.1) being untested is tautological — there's no code there. The rest are real gaps: `middleware/auth`, `middleware/tracing`, `warden/patterns`, and `memory/scopes` back hot-path security and request-pipeline behavior with no direct unit coverage.

### 3.1 Existing `xfail(strict=False)` tests (6)

These advertise coverage without enforcing it:

- `tests/api/test_agents_routes.py:203`
- `tests/integration/test_structured_request.py:26`
- `tests/integration/test_full_pipeline_e2e.py:171`
- `tests/integration/test_coverage_api.py:260, 418, 457`

`docs/test-quality-remediation-plan.md` (already in repo) lists each with an "unskip" action item. Reference, don't duplicate.

---

## 4. Code smells

### 4.1 God method: `Conduit.route_request`

`src/stronghold/conduit.py:186–735` — a single async method of **~550 lines** with radon cyclomatic complexity **99 (F grade)**. It covers classification, ambiguity handling, session stickiness, intent routing, warden scans, agent dispatch, tracing, learning extraction, and response assembly. This is the docstring-named "ONLY way requests reach an LLM" — which is also why the blast radius of any edit here is high.

### 4.2 Other radon hotspots (C / D / E / F grade)

| Grade | Location                                                     |
|-------|--------------------------------------------------------------|
| F(99) | `conduit.py:186` `Conduit.route_request`                     |
| E(33) | `skills/fixer.py:13` `fix_content`                           |
| D(29) | `config/loader.py:62` `load_config`                          |
| D(28) | `api/routes/admin.py:1307` `analyze_quota`                   |
| D(27) | `api/routes/admin.py:736` `get_quota`                        |
| C(20) | `conduit.py:134` class body; `memory/episodic/store.py:9` `_matches_scope`; `router/filter.py:14` `filter_candidates` |
| C(18) | `container.py:216` `create_container`; `api/routes/chat.py:25` `chat_completions`; `api/routes/mcp.py:153` `deploy_server` |

### 4.3 File-size outliers

- `src/stronghold/api/routes/admin.py` — **1,598 lines**, maintainability index C (the only C-rated MI in the tree). Covers learnings admin, user admin, quota, coins, strikes, appeals, coin pricing — at least seven distinct responsibilities in one file.
- `src/stronghold/skills/connectors.py` — 736 lines.
- `src/stronghold/conduit.py` — 766 lines, one class.

### 4.4 Broad `except Exception` with silent pass

96 `except Exception` blocks across the source tree. Bandit flags eight `B110 try/except/pass`:

| File:line                                                 | What gets swallowed                                    |
|-----------------------------------------------------------|--------------------------------------------------------|
| `agents/factory.py:330`                                   | Strategy registration (see §2.2)                       |
| `agents/strategies/tool_http.py:58`                       | Any failure during `list_tools()` → returns `[]`       |
| `api/routes/profile.py:100`                               | Token breakdown lookup → user sees 0 XP with no error  |
| `mcp/deployer.py:270,275`                                 | K8s `delete_namespaced_deployment/service` failures    |
| `memory/learnings/embeddings.py:178`                      | Embedding failure → silently skips that learning       |
| `security/auth_demo_cookie.py:62`                         | Cookie parse error → request falls through as unauth   |
| `triggers.py:317`                                         | GitHub webhook body parse                              |

Plus one `B112 try/except/continue` at `tools/workspace.py:211`.

Individually most are arguable. Together they describe a "when in doubt, swallow it" culture that makes production failures hard to diagnose. A standard like "log at WARNING, re-raise unless the docstring names the exception" would help.

### 4.5 Module-level mutable singletons

`global` writes at module scope — these make ordering/lifetime bugs hard to test:

- `cache/redis_pool.py:34,50` — `_pool`
- `persistence/__init__.py:16,30` — `_pool`
- `models/engine.py:29,76` — `_engine`, `_engine_url`
- `mcp/oauth/endpoints.py:41` — `_store`
- `skills/connectors.py:644` — `_claude_cache`, `_claude_cache_ts`
- `log_config.py:75` — `_CONFIGURED`

The protocol-driven DI container is the stated pattern; these are the leaks. `mcp/oauth/endpoints.py` holding a module-level `_store` is the most surprising one given OAuth is security-critical.

### 4.6 Lazy imports everywhere

**158** imports tagged `# noqa: PLC0415`. `src/stronghold/container.py` alone has 34. Some are legitimate (breaking circulars between `container.py` and `conduit.py`, optional `redis`/`kubernetes` deps), but this density is a signal that the import graph has too many cross-subsystem edges. Worth an audit targeting `container.py` and `api/routes/*` first.

### 4.7 `Any` density

139 `: Any` / `-> Any` annotations. Hot spots: `conduit.py` (`messages: list[dict[str, Any]]`, `auth: Any`, `agent: Any` — the public API of the router), `container.py`, `agents/base.py`. `conduit.py:186` typing `auth: Any` and then checking `isinstance(auth, AuthContext)` inside the function is a runtime-type-narrowing smell — the static type should just be `AuthContext`.

### 4.8 Bandit — low severity but worth triaging

| ID    | Count | Notes                                                                                          |
|-------|-------|------------------------------------------------------------------------------------------------|
| B101  | 2     | `assert` in production code (`events.py:100`, `memory/learnings/promoter.py:73`) — stripped under `python -O` |
| B105  | 6     | String literals like `"Bearer"`, `"refresh"` flagged as "possible hardcoded password" — false positives, but they mark real hot-path auth strings that could use an enum |
| B106  | 2     | Same idiom in `mcp/oauth/store.py:133,154` — false positive                                    |
| B107  | 1     | Default arg `token: str = ""` in `tools/github.py:191` — works with `os.environ.get(...)` fallback, still fragile |
| B110  | 8     | Swallowed exceptions (see §4.4)                                                                |
| B112  | 1     | `try/except/continue` in `tools/workspace.py:211`                                              |
| B311  | 2     | Non-cryptographic RNG for jitter (`events.py:204`) and canary routing (`skills/canary.py:116`) — low risk, but canary routing should at least be seeded deterministically per (skill, org_id) to avoid replay asymmetry |
| B404  | 1     | `subprocess` import in `tools/workspace.py:20`                                                 |
| B603  | 1     | `subprocess` call at `tools/workspace.py:220` — untrusted-input risk if `cmd` ever takes user text |
| B608  | 3     | SQL string-building in `persistence/pg_outcomes.py:114,173` and `api/routes/profile.py:175`. The persistence ones interpolate a trusted `group_by` literal from a whitelist; `profile.py` builds `UPDATE ... SET f=$n` from a hardcoded field tuple — both safe today but the pattern is fragile. |

No high-severity bandit findings.

### 4.9 Pre-existing test-quality backlog

`docs/test-quality-remediation-plan.md` has already cataloged 331 weak/bad tests:

- 118 trivial-type tests (`isinstance`/`hasattr` right after assignment)
- 65 status-only (`status_code == 200` with no body assert)
- 54 over-mock (mock determines outcome)
- 34 no-assert smoke tests
- 32 tautologies (setup equals outcome)
- 26 planned deletions across 10 files

Top offenders: `tests/test_types.py` (30), `tests/security/test_security_audit_2026_03_30.py` (20), `tests/mcp/test_registries_coverage.py` (18), `tests/api/test_admin_routes.py` (18). Defer to that plan — no need to re-audit here.

### 4.10 Coverage-padding test files

Four files at the `tests/` root whose names advertise the purpose rather than the subject:

| File                                       | LOC   |
|--------------------------------------------|-------|
| `tests/test_coverage_final.py`             | 1,630 |
| `tests/test_coverage_misc.py`              |   935 |
| `tests/test_new_modules.py`                |   717 |
| `tests/test_new_modules_2.py`              | 1,039 |

Total 4,321 LOC. Useful as a staging ground but they hide behavior under geography — a change to `skills/forge.py` has no obvious reason to hunt `test_coverage_final.py`. Worth redistributing to `tests/<subsystem>/`.

---

## 5. Production TODOs

Only two survive in `src/`:

- `src/stronghold/api/routes/admin.py:1244` — `update_coin_settings` needs superadmin gating once trust tiers are wired (§4.3 of the existing admin hotspot).
- `src/stronghold/agents/strategies/builders_learning.py:116` — orphan diagnostic artifact (§2.3).

---

## 6. Red-team / injection bait

`.easter.egg.hi` at the repo root is a prompt-injection honeypot (a file addressed to scanning LLMs with instructions). Not executed, not imported — leaving it alone is the right move. Worth flagging so reviewers know it's intentional.

---

## 7. Second-pass findings

### 7.1 Unawaited background tasks (concrete async bug)

`src/stronghold/api/routes/mason.py:70`

```python
asyncio.create_task(_dispatch_mason(issue))
```

The task reference is thrown away. Python docs explicitly warn: "Save a reference to the result of `create_task()`, to avoid a task disappearing mid-execution." Under GC pressure the dispatch can be collected. Fix: keep a module-level `set()` of running tasks and add/discard via `add_done_callback`.

Other `create_task` call sites are safe — `events.py:159` holds `task`, `agents_stream.py:113` polls `task.done()`, `mcp/registries.py:204–206` `gather`s the tasks, `orchestrator/engine.py:106` keeps a worker list, `api/app.py:58` holds `reactor_task`.

### 7.2 Deprecated `asyncio.get_event_loop()` in an async function

`src/stronghold/mcp/deployer.py:56, 215, 237, 259, 284`

Five copies of:

```python
return await asyncio.get_event_loop().run_in_executor(None, self._deploy_sync, server)
```

Inside an already-running coroutine `get_event_loop()` is deprecated for this purpose since 3.10 and may raise `DeprecationWarning` on 3.12. Correct: `asyncio.get_running_loop()` or simpler `asyncio.to_thread(self._deploy_sync, server)`.

### 7.3 Naive `datetime.now()` without tz

`src/stronghold/events.py:137` — `now = datetime.now()` inside the reactor tick. The reactor uses this for time-triggered firings (line 212 compares `now.strftime("%H:%M")` to `spec.at_time`). On a container running UTC this is fine; on any host/DST-aware timezone the trigger times drift. Make it `datetime.now(timezone.utc)` and document that `spec.at_time` is UTC.

### 7.4 Resource leak: `MCPDeployerClient._client` never closed

`src/stronghold/sandbox/deployer.py:37–40, 156–157`

```python
def __init__(self, base_url: str = "") -> None:
    ...
    self._client = httpx.AsyncClient(base_url=self._base_url, timeout=30.0)

async def close(self) -> None:
    pass
```

Constructor opens an `httpx.AsyncClient`; `close()` is a no-op. Connections and sockets leak for the lifetime of the DI container. Replace `close()` with `await self._client.aclose()` or switch to per-call `async with httpx.AsyncClient(...)`.

### 7.5 Two `httpx.AsyncClient()` calls with no timeout

`src/stronghold/api/routes/marketplace.py:136, 187` — both use `httpx.AsyncClient()` with defaults. Every other call site in the tree sets an explicit timeout (5–600s). A slow external registry hangs the request until the upstream ASGI timeout fires.

### 7.6 `inspect.signature().bind_partial` as a regression guard

`tests/security/test_security_audit_2026_03_30.py:74, 96, 179, 213, 233, 284, 972` and `tests/api/test_issue_620.py:57`, `tests/security/test_audit_regression.py:970`

These tests bind a call signature to assert that a parameter (e.g. `org_id`) is or isn't present. The `docs/test-quality-remediation-plan.md` flags this file's 20 tests as a rewrite target. These signature-shape tests pass even if the implementation body is a stub, so they guard the API contract but not the behavior.

### 7.7 Duplicated auth-header parsing across 17 route files

`auth_header = request.headers.get("authorization")` (or `"Authorization"`) is hand-rolled in **17 route modules** (33 occurrences): `tasks.py`, `schedules.py`, `models.py`, `traces.py`, `webhooks.py`, `agents_stream.py`, `status.py`, `mcp.py`, `admin.py`, `gate_endpoint.py`, `chat.py`, `skills.py`, `sessions.py`, `dashboard.py`, `profile.py`, `agents.py`, `marketplace.py`. Some use `"authorization"`, some use `"Authorization"` (HTTP headers are case-insensitive in Starlette so this works, but the style drift signals copy-paste rather than a shared helper). Bundle into a single dependency/middleware — it already exists as `api/middleware/auth.py` (which §3 notes has no test coverage).

### 7.8 Personal data in migration 011

`migrations/011_seed_admin.sql` hardcodes `blakematthews@agentstronghold.com` with `["admin", "org_admin", "team_admin", "user"]` roles. Every fresh Stronghold deployment — including third-party installs of an Apache-licensed OSS project — creates this specific user as an admin on first boot. Whether or not the `ON CONFLICT DO NOTHING` clause saves existing installs, this should be gated behind an env flag (`STRONGHOLD_DEV_SEED=1`) or moved into `deploy/` fixtures, not shipped as a forward migration.

### 7.9 Production Dockerfile runs as root and ships tests + dev deps

`Dockerfile`:

- No `USER` directive → runs as root. `Dockerfile.worker` correctly creates a `stronghold` user and drops to it; the main API image doesn't.
- `COPY tests/ tests/` and installs `.[dev]` (pytest, ruff, mypy, bandit) into the runtime image. The comment explains "Mason's workspace validation depends on the dev quality tools existing" — so this is intentional, but it means the attack surface of the API container includes the test suite and every dev dependency. Consider splitting Mason's quality-gate path into its own image or running Mason in a sibling pod.
- `RUN mkdir -p /workspace && chmod 777 /workspace` — world-writable workspace. Needed for Mason worktrees, but combined with root-as-default this lets any in-pod compromise rewrite Mason's work area.

### 7.10 docker-compose.yml uses static weak credentials

`docker-compose.yml` sets `POSTGRES_USER=stronghold`, `POSTGRES_PASSWORD=stronghold`. Intended for local dev, but `.env.example` doesn't call out that these must be changed, and the compose file binds Postgres ports (check full file before deploy). Add a banner comment and point at `deploy/` for hardened configs.

### 7.11 `unittest.mock` used in 34 test files despite CLAUDE.md rule

CLAUDE.md §Testing Rules §1 explicitly forbids `unittest.mock` — "All protocols have fakes in `tests/fakes.py` — use those, not `unittest.mock`." Yet 34 files import `MagicMock` / `AsyncMock` / `@patch` (107 raw occurrences). Representative offenders: `tests/test_new_modules_2.py`, `tests/test_coverage_final.py`, `tests/api/test_marketplace_coverage.py`, `tests/api/test_mason_routes.py`, `tests/persistence/test_pool.py`. This is the same cluster the test-quality plan calls out as "over-mock" — a linter rule (`ruff` custom rule or `grep` in CI) could prevent regression.

### 7.12 `assert resp.status_code == 200` with no body inspection

Grep for `assert.*is not None$` returns **211 matches** across the test tree, and the existing test-quality audit counts 65 "status-only" tests that check HTTP status but never look at the body. Same backlog, but worth quantifying: 211+65 = ~276 asserts that could pass against a completely broken implementation as long as it returned a 200 with *any* object.

### 7.13 Timeout constants scattered without a central config

25+ literal timeouts across the tree: `5.0`, `10.0`, `15.0`, `30.0`, `60.0`, `180.0`, `300.0`, `600.0`. `tools/github.py` alone uses `30.0` on eleven calls and `60.0` on one (comment-add), with no obvious reason for the split. Cache TTLs are also hardcoded: `_CLAUDE_CACHE_TTL = 300.0` (`skills/connectors.py:39`), `_CACHE_TTL_FULL = 900.0` (`api/routes/mason.py:193`), the Redis prompt-cache TTL `300` baked into `container.py:300`. Pull into `config/defaults.py` or typed config so operators can tune without code edits.

### 7.14 Hash choice: intentional MD5 with `usedforsecurity=False`

`src/stronghold/memory/learnings/embeddings.py:88` — `hashlib.md5(text.encode("utf-8"), usedforsecurity=False).digest()`. The `# noqa: S324` and the surrounding docstring justify it as a deterministic fake-embedding seed for tests. Not a bug, but worth flagging so a future refactor doesn't reach for a "more secure" hash and break reproducibility.

### 7.15 `asyncio.get_event_loop()` in `mcp/deployer.py` is also swallowed by try/except

Three of the five `get_event_loop()` sites (§7.2) are paired with the `B110` try/except/pass at lines 270 and 275 (§4.4). If the executor raises because the loop is mis-acquired, the exception is suppressed — double-layered silence.

### 7.16 `_FakeToolDispatcher`, `_FakeToolRegistry`, `_FakeToolDef` in tests

`tests/test_coverage_final.py:29, 43, 56` — three private fakes defined inline in a test file. CLAUDE.md §Testing Rules §1 says "All protocols have fakes in `tests/fakes.py` — use those." Either promote these fakes to `tests/fakes.py` or fold them into existing ones. Probable cause: the coverage push ran out of time to refactor.

### 7.17 Hash-based LLM classifier fail-open still warrants double-checking

§1.2 already covers the Warden L3 fail-open. Worth cross-referencing `src/stronghold/security/warden/llm_classifier.py` (the file that currently returns `label="safe"` on exception). A broken LLM endpoint turns the strongest warden layer into a no-op — and the tests confirm this is live behavior.

### 7.18 Duplicate `_check_csrf` between `admin.py` and `marketplace.py`

`src/stronghold/api/routes/admin.py:17–35` and `src/stronghold/api/routes/marketplace.py:79–97` are byte-for-byte identical (`diff` returns empty). A CSRF fix in one won't propagate to the other. Hoist into `api/middleware/` or `security/`. While there, check for other near-duplicates between these two files — they also share a `_require_admin` / auth-header-parse shape (§7.7).

### 7.19 Inline `os.environ.get()` in 12 spots bypasses the config layer

CLAUDE.md §Build Rule 4 requires config through env vars or K8s secrets, but those values should flow through `config/`. Direct `os.environ.get()` calls live in:

- `api/app.py:47, 53` — `STRONGHOLD_MAX_CONCURRENCY`, `STRONGHOLD_DISABLE_REACTOR_AUTOSTART`
- `api/routes/mason.py:369` — `GITHUB_WEBHOOK_SECRET` (security-critical!)
- `triggers.py:218`, `tools/github.py:129–134, 193`, `tools/workspace.py:29, 112` — GitHub auth material
- `sandbox/deployer.py:21, 126` — deployer URL + MCP namespace

The webhook-secret read is the most worrying: a deploy that sets the secret in `config/` (where operators expect it to live per the architecture doc) will still let every webhook through because `mason.py` only looks at `os.environ`. Centralize in `config/env.py` with typed accessors.

### 7.20 Docstring/implementation drift in `Conduit._apply_tenant_policy`

`src/stronghold/conduit.py:55–60` — function takes `_tenant_id: str | None = None` but is only called as `_apply_tenant_policy(current_tier)` at line 95 (no tenant ID passed, and the parameter is named with leading underscore to signal it's ignored anyway). Meanwhile, `determine_execution_tier`'s docstring (lines 67–77) lists "3. tenant policy" as part of the "override stack". The stack is advertised but not wired. Either delete step 3 from the docstring, or pass the tenant in and implement.

### 7.21 `asyncio.sleep(2)` and `asyncio.sleep(1)` hardcoded in Artificer

`src/stronghold/agents/artificer/strategy.py:80` and `:213`. No comment on why. Reviewing the file shows these are cooldowns between plan/execute/retry phases — legitimate, but they belong in config alongside §7.13's other timeout constants.

### 7.22 Module-level mutable caches in `mason.py`

`src/stronghold/api/routes/mason.py:192` — `_issues_cache: dict[str, Any] = {"data": None, "fetched_at": 0.0}` shared across requests with no lock. Lines 206–246 read, check TTL, and write back. Under concurrent requests from different users, two reads at `t_read` both see an expired entry, both fetch from GitHub, and the last writer wins. Usually benign for read caches (duplicated work, same data), but any field added later that needs read-modify-write will race.

Same pattern in `_state` at lines 40–48 for router/reactor/container handles, though those are write-once at startup.

### 7.23 `_DELIST_THRESHOLD` used inline at 4 sites

`src/stronghold/api/routes/marketplace.py:35, 49, 51, 74, 350` — five references to the same `= 3` constant. Fine today. Worth noting together with the other config-that-should-be-config items in §7.13. Same for `_MAX_TIMESTAMP_AGE_SECONDS = 300` in `api/routes/webhooks.py:26, 34`.

### 7.24 Inconsistent error-to-HTTP mapping across routes

Only `api/routes/agents.py:117–118` (and chat.py at 133) map `QuotaExhaustedError → 429`. `api/routes/admin.py`, `api/routes/marketplace.py`, and `api/routes/skills.py` hit the same code paths (they all go through `container.route_request` or similar) but don't catch the quota exception. A request at the quota wall returns 500 from those routes even though 429 is the correct answer. Shared middleware for business-error → HTTP mapping would fix this alongside §7.7 auth-header parsing.

### 7.25 No upper bound on user-text before Warden scan / LLM dispatch

`src/stronghold/api/routes/chat.py:58–69` reconstructs `user_text` from the message history and passes it into `route_request` → Warden scan → LLM. Warden's short-circuit heuristics cap certain windows (§1.2 H3 shows the gap bug) but the outer pipeline itself never rejects over-length content. A 5 MB `messages[0].content` fans out to Warden regex passes and then LiteLLM. Cap early (e.g. 100K chars) with a 413.

### 7.26 SSE stream leaks background task on client disconnect

`src/stronghold/api/routes/agents_stream.py:113–143` — the generator starts `task = asyncio.create_task(run_agent())` and polls `task.done()` in a loop. If the client disconnects mid-stream, the generator stops iterating but the task keeps running until agent completion — consuming LLM tokens, holding DB connections, and posting updates to an unread queue. Wrap the generator body in `try/finally: task.cancel()` or use `contextlib.aclosing`.

### 7.27 Response-body shape not validated after `status_code == 200`

`src/stronghold/api/routes/marketplace.py:246, 258` — code accepts any `200` and assumes the body is parseable. If the upstream registry returns HTML (503 page served with status 200, common behind proxies) or a malformed JSON, parsing crashes into the generic exception handler and the user sees a 500. Cheap fix: verify `Content-Type: application/json` before parsing.

### 7.28 Pagination boilerplate duplicated between admin and marketplace routes

`api/routes/admin.py` (learnings list, users list, strikes list) and `api/routes/marketplace.py` (GitHub issues fetch) share a query-limit-offset-cache-TTL shape with no abstraction. Low-priority consolidation target; flagged here so the next pagination change doesn't create a third variant.

### 7.29 Status callback may pass tokens through to the queue

`src/stronghold/api/routes/mason.py:95–136` — the `_log` helper forwards every status string to `queue.add_log(issue_num, msg)`. `msg` originates from `status_callback` calls inside `route_request` and agent strategies; any strategy that interpolates error detail from an HTTP client (e.g. 401 body, upstream auth header) would land raw in a durable queue. Audit callers of `status_callback` to ensure the string is sanitized first, or add a redaction pass in `add_log`.

### 7.30 Tautological loop-then-assert in `test_new_modules_2.py`

`tests/test_new_modules_2.py:179, 196, 218, 240, 254, 272, 287, 304, 317, 337, 353, 372, 390` — repeated pattern:

```python
found = None
for trigger in container.reactor._triggers:
    if trigger.spec.name == "foo":
        found = trigger
assert found is not None
```

The assertion only fires if the loop executed AND matched — but if trigger registration breaks silently, the dict is empty and `found` stays `None`, which would correctly fail. What doesn't fail: if the loop matches any random trigger, the assertion still passes without checking the trigger's content. The inverted pattern is the smell: rather than asserting a known name exists, iterate the reactor's public `get(name)` API.

---

## Suggested priority order for remediation

1. **Flip the seven `BUG CONFIRMED` security tests** (§1.2). These are active vulnerabilities with fixes pre-written as test contracts.
2. **Fix the `Intent.tier` type leak** (§1.1), the `Any`-return regressions (§1.4, §1.5), the unawaited-task bug (§7.1), and deprecated `get_event_loop()` (§7.2).
3. **Close resource leaks**: `MCPDeployerClient._client` (§7.4), SSE task on disconnect (§7.26).
4. **Un-swallow `ImportError` in `factory.py`** (§2.2) — silent agent-strategy failures will bite hard in production.
5. **Move `GITHUB_WEBHOOK_SECRET` (and the other 11 env reads) behind `config/`** (§7.19) — a webhook with no secret validation is a remote-execution backdoor.
6. **Remove the hardcoded admin email from migration 011** (§7.8) — this is cosmetic until someone forks, then it's surprising.
7. **Fix the root-user prod Dockerfile and the tests-in-prod bundling** (§7.9).
8. **Decompose `Conduit.route_request`** (§4.1) and split `api/routes/admin.py` (§4.3) before they accrete more logic.
9. **Hoist duplicated helpers**: `_check_csrf` (§7.18), auth-header parsing (§7.7), Warden scan pattern (§7.14 referenced by subagent), error-to-HTTP mapping (§7.24).
10. **Add an input-length cap on user text** (§7.25) — cheap DoS guard.
11. **Close the 28 untested modules** (§3) prioritizing `middleware/auth`, `middleware/tracing`, `warden/patterns`, `memory/scopes`.
12. **Execute the existing test-quality plan** (§4.9) — the work is scoped; this catalog just confirms it's still needed.
13. **Implement or delete the Forge / Scribe / Warden-at-Arms stubs** (§2.1). If they're near-term on the roadmap, promote to skeletons with failing tests; otherwise drop them so the architecture doc stops overselling.
14. **Centralize timeouts / TTLs / thresholds** (§7.13, §7.21, §7.23) as the maintainability base-rate improvement.
