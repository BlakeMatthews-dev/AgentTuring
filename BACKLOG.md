# Stronghold Backlog

**Last Updated:** 2026-03-31
**Status:** Pre-v1.0 — Phases 1-4 complete + 3 security audits + 1 live red team done

---

## What We Have (Completed)

### Phase 1: Security Backbone ✅
- Gate: sanitize + Warden scan + sufficiency check (3 execution modes)
- Warden: 4-layer detection:
  - L1: Regex (20+ patterns including emotion manipulation, indirect role hijacking, context stuffing)
  - L2: Heuristic (instruction density + base64 encoded + emotion/poisoning tokens)
  - L2.5: Semantic tool-poisoning (prescriptive+action/object, 62.5% detection, 0% FP on 12K real samples)
  - L3: Few-shot LLM classifier (10 examples, optional, non-blocking, flag-and-warn)
- Warden: Unicode NFKD normalization (homoglyph bypass defense)
- Warden: SIGALRM regex timeout (ReDoS protection)
- Warden: 10KB scan window
- Warden: blocks on ANY flag (L1), flag-and-warn (L2+)
- Flag-and-warn pattern: content preserved + warning banner + admin notification + user escalation email
- Sentinel: pre-call (schema validation + repair + permission check)
- Sentinel: post-call (Warden scan + PII filter + token optimizer + flag-and-warn)
- PII filter: 15 patterns + NFKD normalization (defeats Cyrillic lookalikes)
- JWT auth: IdP-agnostic (Keycloak/Entra ID/Auth0/Okta), JWKS non-blocking cache
- Identity: 5 kinds (User/Agent/ServiceAccount/InteractiveAgent/System)
- Identity: Org→Team→User hierarchy, SYSTEM_AUTH uses `__system__` sentinel
- Audit: every boundary crossing logged, org-scoped, error-resilient
- Auth: constant-time API key comparison (hmac.compare_digest)
- Auth: ALL endpoints authenticated (prompts, tasks, models, reactor, sessions, admin)
- SSRF: blocklist on tool executor (localhost, metadata, internal IPs, HTTPS-only)

### Phase 2: Memory Backbone ✅
- Embedding protocol: pluggable (Ollama/OpenAI/any), NoopEmbeddingClient for testing
- Hybrid learning store: keyword + cosine similarity (1:3 weighting)
- Learning store: org-scoped (strict filtering, no empty bypass), dedup with logging
- Learning store: 10K cap with FIFO eviction (OOM protection)
- Episodic retrieval: org-scoped, weight-based ranking, team isolation
- Session store: org-namespaced IDs, ownership validation, path traversal prevention
- Outcome store: org-scoped, FIFO cap (10K), per-model stats

### Phase 3: Skill System ✅
- Parser: YAML frontmatter + markdown body, strict validation, security scan
- Loader: filesystem + community, symlink rejection, merge into tools
- Registry: CRUD + trust tier filtering + T0/T1 overwrite protection
- Forge: LLM skill creation, T3 default, security scan, path traversal protection
- Forge: skill mutation from learnings, instruction density gate (0.08)
- Marketplace: HTTP install, security scan, trust tiers, SSRF blocklist

### Phase 4: Tool Framework + UI ✅
- InMemoryToolRegistry: register/get/list/list_for_task
- ToolDispatcher: timeout, HTTP endpoint fallback, SSRF protection
- ToolPlugin protocol
- 6 API route groups (chat, skills, sessions, admin, traces, dashboard)
- 6 castle-themed dashboard pages (Great Hall, Knights, Armory, Watchtower, Treasury, Scrolls)
- All dashboards XSS-free (DOM API, not innerHTML)

### Security Hardening ✅ (2 rounds)
- 30+ vulnerabilities fixed across 2 enterprise-grade audits + 42 findings in audit round 3
- OWASP mapped: Web 2021, LLM 2025, API 2023
- 213-sample bouncer training set benchmarked
- Tool result size cap (16KB), JSON bomb limit (32KB)
- PII filter on all code paths (not just Sentinel)

### Metrics
- **155+ source files, ~11,500 LOC**
- **2785 tests passing**
- **mypy --strict: 0 errors** (on new/modified files)
- **ruff check: clean**

---

## What's Left for v1.0

### Infrastructure Security (2026-03-31 red team — live attack on running stack)

These findings are from a live red team exercise against the running Stronghold stack.
They target the **deployment/infrastructure layer**, not application code — prior code
audits did not cover these. Many of these are the highest-severity findings because they
bypass all application-level security controls.

#### RED-CRITICAL — Container & Secrets (enables full host takeover)

- [ ] **R1: `privileged: true` on stronghold container** — grants full host access, device access, bypasses all Linux security modules. The Dockerfile correctly creates a non-root `stronghold` user (`USER stronghold`), but `privileged: true` in docker-compose overrides this to effective root. Comment says "Required for Kind K8s cluster access (MCP deployer)" — find an alternative. **Fix:** remove `privileged: true`, add only the specific capabilities needed (likely `NET_ADMIN` or `SYS_PTRACE`), or run Kind K8s cluster outside the app container. (`docker-compose.yml:11`)

- [ ] **R2: `privileged: true` on postgres container** — comment says "Required for pgvector extension setup" but pgvector works fine without privileged mode on standard pg17 images. **Fix:** remove `privileged: true`. If extension setup genuinely fails, use `--cap-add SYS_NICE` or init script with appropriate permissions. (`docker-compose.yml:39`)

- [ ] **R3: Kubeconfig with cluster-admin credentials mounted in app container** — `.kubeconfig-docker` contains full RSA private key + client certificate for `kind-stronghold` cluster-admin. Combined with R1, this grants full K8s cluster control from within the container. **Fix:** move MCP deployer to a separate sidecar container with minimal K8s RBAC (namespace-scoped, not cluster-admin). Remove kubeconfig mount from stronghold service. (`docker-compose.yml:17`, `.kubeconfig-docker`)

- [ ] **R4: Real API keys in `.env` on disk** — 6 production API keys (Cerebras, Mistral, Google, Perplexity, LiteLLM master, Router) in cleartext. `.gitignore` correctly excludes `.env`, and `.env` was never committed to git history, but the file is readable by any process on the host. **Fix:** use Docker secrets or a secrets manager (Vault, SOPS). For immediate mitigation: `chmod 600 .env`, rotate all keys. (`.env`)

- [ ] **R5: PostgreSQL weak password on `0.0.0.0:5432`** — user `stronghold`, password `stronghold`, port exposed on all interfaces. Any host on the network can connect and dump all 17 tables (users, sessions, agents, audit_log, learnings, permissions, etc.). During red team, successfully dumped all 6 user records including emails, roles, org IDs. **Fix:** generate strong random password (32+ chars), bind port to `127.0.0.1:5432:5432` or remove port binding entirely (stronghold service connects via Docker DNS `postgres:5432`). (`docker-compose.yml:42-44,49`)

- [ ] **R6: All API keys visible in container environment** — `docker exec stronghold env` reveals all 6 API keys. Any code execution inside the container (via tool dispatch, skill forge, agent creation) can read them. **Fix:** use Docker secrets (mounted as files), not env vars. Stronghold only needs `ROUTER_API_KEY` and `LITELLM_MASTER_KEY` — don't pass provider keys (Cerebras, Mistral, Google, Perplexity) to the app container; LiteLLM handles those. (`docker-compose.yml:15`, `.env`)

#### RED-HIGH — Exposure & Access Control

- [ ] **R7: OpenAPI schema exposed without auth** — `/docs`, `/redoc`, `/openapi.json` all return 200 with full API schema (100+ endpoints, request/response schemas, auth requirements). Gave the attacker a complete attack surface map. Rate limiter explicitly exempts these paths. **Fix:** in production, set `docs_url=None, redoc_url=None, openapi_url=None` in FastAPI constructor, or gate behind auth. Use env var toggle: `STRONGHOLD_DOCS_ENABLED=false`. (`api/app.py:55-60`, `middleware/rate_limit.py:29`)

- [ ] **R8: Static API key grants SYSTEM_AUTH (all admin roles)** — `ROUTER_API_KEY` maps to `SYSTEM_AUTH` with roles `{admin, org_admin, team_admin, user}`. During red team, this single key was used to: list all users with PII, create malicious agents, access audit logs, forge skills, invoke chat completions consuming provider credits. **Fix:** implement API key scoping — create read-only keys, user-level keys, and admin keys. SYSTEM_AUTH should only be used for internal service-to-service calls (pipelines → stronghold), not external API access. (`security/auth_static.py:50`, `types/auth.py:103-110`)

- [ ] **R9: Missing global security headers** — no HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy on any endpoint. CSP exists but only on dashboard routes. **Fix:** add `SecurityHeadersMiddleware` in `app.py` that sets these on ALL responses. (`api/app.py`)
    ```
    Strict-Transport-Security: max-age=63072000; includeSubDomains
    X-Frame-Options: DENY
    X-Content-Type-Options: nosniff
    Referrer-Policy: strict-origin-when-cross-origin
    Permissions-Policy: camera=(), microphone=(), geolocation=()
    ```

- [ ] **R10: CORS `Access-Control-Allow-Credentials: true` without origin restriction at runtime** — config defaults are safe (`localhost:3200`), but the running instance returned `allow-credentials: true` for any `Origin` header. Enables CSRF-via-CORS for any website to make authenticated requests using a user's browser session. **Fix:** verify CORS origins match the runtime config; ensure Starlette's `CORSMiddleware` isn't reflecting arbitrary origins when `allow_credentials=True`. Check if `cors_origins` in config is empty (which may cause the middleware to reflect any origin). (`api/app.py:66-80`, `types/config.py:52-69`)

- [ ] **R11: Agent creation accepts arbitrary tool names without validation** — during red team, created an agent with tools `[shell_exec, file_read, env_dump]` (none exist). No check against `tool_registry`. While non-existent tools would fail at execution time, the agent persists in DB and is visible to all users, polluting the agent namespace. **Fix:** validate tool names against `container.tool_registry` in the create endpoint. Reject unknown tools with 400. (`api/routes/agents.py:225`)

- [ ] **R12: LiteLLM AppArmor disabled** — `security_opt: apparmor:unconfined`. Required for async workers, but should be reviewed. **Fix:** create a custom AppArmor profile that allows async operations but restricts filesystem/network access. (`docker-compose.yml:88-89`)

- [ ] **R13: OpenWebUI auth disabled** — `WEBUI_AUTH=false` + `ENABLE_SIGNUP=true`. Anyone who can reach port 3000 can use OpenWebUI to access all LiteLLM models ungoverned (bypassing Stronghold entirely via the direct path). **Fix:** enable OpenWebUI auth in production, or restrict port 3000 to localhost only. (`docker-compose.yml:158-159`)

#### RED-MEDIUM — Defense Gaps

- [ ] **R14: `ROUTER_API_KEY` length only warned, not enforced** — keys shorter than 32 chars accepted with a log warning. The current key `sk-stronghold-prod-2026` is 24 chars. **Fix:** make 32-char minimum a hard error in `loader.py`. (`config/loader.py:91-97`)

- [ ] **R15: Warden sanitizer not applied to tool_result boundary** — `sanitize()` (which strips zero-width chars) runs before Warden scan on `user_input` boundary (`gate.py:106`), but tool results go directly to `warden.scan(content, "tool_result")` without sanitization. A malicious tool could inject zero-width chars to bypass L1 regex patterns. **Fix:** apply `sanitize()` to tool results before Warden scan, or have Warden strip zero-width chars internally. (`security/warden/detector.py:70`, `security/gate.py:106-109`)

- [ ] **R16: Health endpoint leaks internal state** — `/health` returns `{"db": "connected", "llm": "reachable"}` without auth. Useful for attackers to confirm service topology. **Fix:** return only `{"status": "ok"}` for unauthenticated requests; full details behind auth. (`api/routes/status.py`)

- [ ] **R17: Demo JWT signed with router API key (HS256)** — already tracked as H5 in code audit. Confirmed exploitable during red team: anyone with the API key can forge session cookies for any user. The key is only 24 chars (see R14). **Cross-ref:** H5 in code audit section below.

#### RED-CRITICAL (Wave 2-3 — deeper exploitation)

- [ ] **R18: Forged JWT cookie = full admin access to any org** — crafted an HS256 JWT signed with the leaked `ROUTER_API_KEY`, set it as `stronghold_session` cookie, and gained **full admin access**. Demonstrated: list users, create agents, invoke chat (consuming provider budget), read audit logs. No real user account needed — attacker forges JWT for any email/org/role combination. This is a **complete authentication bypass**. Requires only knowing the API key (see R4/R6). **Fix:** separate JWT signing key from API key; use RS256 with asymmetric keypair; or at minimum generate a dedicated 64+ char HS256 secret. (`api/routes/auth.py:342,402`, `api/middleware/demo_cookie.py:76`)

- [ ] **R19: Direct LiteLLM bypass (port 4000) — all governance bypassed** — LiteLLM proxy is accessible from the host on `localhost:4000` with the master key. Calls go directly to models with **zero Stronghold governance**: no Warden, no Gate, no classifier, no quota tracking, no audit log. Confirmed: sent prompt injection directly to Mistral-Large via LiteLLM, got unfiltered response. **Fix:** bind LiteLLM port to container network only (remove `ports: "4000:4000"` from docker-compose, or bind to `127.0.0.1`). If external access needed, gate behind Stronghold. (`docker-compose.yml:91`)

- [ ] **R20: Container reaches host SSH via Docker gateway** — from inside the stronghold container, `172.17.0.1:22` (Docker default gateway = host) is reachable. Combined with R1 (privileged mode), an attacker with code execution in the container can SSH to the host. **Fix:** R1 fix (remove privileged) eliminates the worst case; additionally consider Docker network isolation (`internal: true` on stronghold network). (`docker-compose.yml:176-180`)

- [ ] **R21: Forged JWT enables cross-tenant agent visibility** — a forged JWT for an arbitrary `org_id` could see ALL agents including T0 builtins from the `agent-stronghold` org. Confirms C1 from code audit is exploitable. The red team created a spoof-org admin agent via this path. **Cross-ref:** C1, C2, C3 in code audit. (`api/routes/agents.py`)

- [ ] **R22: Strikes not persisted (in-memory only)** — `InMemoryStrikeTracker` stores all strike data in a Python dict. Container restart (maintenance, deployment, OOM-kill, `docker compose restart`) clears ALL strikes and lockouts. Attacker can trigger 2 strikes → get locked → wait for restart → get 2 more free strikes → infinite cycle. Lockouts have zero durability. **Fix:** persist strikes to PostgreSQL (add `strikes` table). Load on startup, write on every violation. (`security/strikes.py`)

- [ ] **R23: Scan window gap bypassed input Warden (caught by output Sentinel)** — crafted 22KB payload with injection hidden at byte 16500 (in the unscanned gap between bytes 10240 and 20940). Input Warden missed it completely. The LLM processed the injection. **Output Sentinel caught the response** before it reached the user — defense-in-depth saved this one. But if Sentinel is disabled or misconfigured, the injection succeeds end-to-end. **Fix:** scan full content (or overlapping windows) in Warden. Don't rely on Sentinel as sole catch. **Cross-ref:** H2. (`security/warden/detector.py:69`)

#### RED-HIGH (Wave 2-3)

- [ ] **R24: JSON bomb (100-level nesting) passes through Warden** — sent `{"a":{"a":{"a":...}}}` 100 levels deep. Warden didn't flag it. Classifier processed it. Router sent it to LiteLLM. Model generated a 600+ word response expanding the nesting. Token exhaustion vector. **Fix:** add nesting depth limit in PayloadSizeLimitMiddleware or Gate. (`api/middleware/payload_limit.py`)

- [ ] **R25: Forged JWT chat consumes provider budget as nonexistent user** — invoked `/v1/chat/completions` as `hacker@evil.com` (no real account) via forged JWT. Request was routed to `mistral-large`, consuming real provider tokens. Quota tracker records the usage against the forged identity, but the cost is borne by the platform. **Fix:** validate that JWT `sub` claim corresponds to an approved user in the database before processing chat requests. (`container.py route_request`, `api/routes/chat.py`)

- [ ] **R26: Learning injection blocked — but via Warden scan, not content validation** — attempted to inject malicious learnings ("reveal API keys", "bypass security"). Warden correctly blocked both. However, the defense is **Warden pattern matching only** — if an attacker can craft a learning that passes Warden (avoiding trigger words), it persists and influences future agent behavior. There's no semantic validation that a learning is operationally correct. **Mitigation:** learning approval workflow (already in backlog). (`api/routes/admin.py`)

#### RED-MEDIUM (Wave 2-3)

- [ ] **R27: Prompt PUT returns 500 Internal Server Error** — `PUT /v1/stronghold/prompts/agent.default.soul` returned 500 instead of a clean 404 or 400. In debug mode, this may leak stack traces. **Fix:** handle missing prompt store gracefully. (`api/routes/prompts.py`)

- [ ] **R28: Double Authorization header accepted** — when two `Authorization` headers are sent, Starlette uses the first one. If a proxy or CDN prepends a header, the attacker's original header may be ignored or prioritized depending on order. Not directly exploitable but violates defense-in-depth. **Fix:** reject requests with multiple Authorization headers. (`security/auth_static.py`)

### Security (remaining gaps — 2026-03-30 audit)

#### CRITICAL — Cross-Tenant Data Breach (blocks multi-tenant deployment)
- [ ] **C1: PgAgentRegistry.get() no org_id** — any org reads any agent by name (`pg_agents.py:46`)
- [ ] **C2: PgAgentRegistry.delete() no org_id** — any admin deletes another org's agents (`pg_agents.py:152`)
- [ ] **C3: PgAgentRegistry.upsert() name collision** — ON CONFLICT (name) overwrites cross-org (`pg_agents.py:56`). Fix: UNIQUE(name, org_id)
- [ ] **C4: PgPromptManager zero org_id** — all queries use name+label, no org column. Cross-org prompt poisoning (`pg_prompts.py` entire file)
- [ ] **C5: Learning approve/reject by integer ID** — no org_id check on approve/reject. Admin Org-A approves Org-B's learnings (`admin.py:~270`)
- [ ] **C6: MCP server DELETE no auth/org check** — any authenticated user can delete any org's MCP server by name. No admin role required (`mcp.py:~350`)
- [ ] **C7: update_user_roles no org_id in SQL** — `UPDATE users SET roles WHERE id=$2`, no `AND org_id`. Cross-tenant privilege escalation (`admin.py:398`)

#### HIGH — Security Layer Bypasses
- [ ] **H1: ArtificerStrategy missing ALL security** — no Sentinel pre/post, no Warden scan on tool results, no PII filter, no 32KB arg limit, no 16KB truncation. Biggest runtime gap (`artificer/strategy.py:140-200`)
- [ ] **H2: Warden scan window gap** — bytes 10240..(len-2048) unscanned. Middle-content injection evades all layers (`detector.py:69`). Fix: scan full content or overlapping windows
- [ ] **H3: Warden L3 fail-open** — returns "safe" on any exception instead of "inconclusive" (`llm_classifier.py:167`)
- [ ] **H4: Semantic scanner code syntax bypass** — prepend `def foo():` in first 200 chars, entire content skipped (`semantic.py:118`)
- [ ] **H5: JWT signing key = API key** — demo_login uses router_api_key for HS256 signing. Anyone with API key can forge JWTs (`auth.py:342`)
- [ ] **H6: DemoCookieAuthProvider warns but doesn't reject short keys** — <32 byte keys accepted with warning only
- [ ] **H7: Agent create/import have no org_id** — created agents globally visible to all orgs (`agents.py:196-275`)
- [ ] **H8: InMemoryAgentStore.update() no org_id param** — any admin updates any org's agent (`store.py:143`)
- [ ] **H9: InMemoryAgentStore.get() empty org_id bypass** — empty caller org_id sees all org-scoped agents (`store.py:117`)
- [ ] **H10: Session prefix collision** — org_id containing `/` enables `startswith` prefix attack (`sessions/store.py:43`)
- [ ] **H11: Strike remove/unlock/enable no org_id** — cross-tenant strike manipulation (`admin.py:1485-1529`)
- [ ] **H12: MCP server start/stop no org_id** — any user starts/stops any org's MCP servers (`mcp.py:301-340`)
- [ ] **H13: PgQuotaTracker global** — no org_id dimension; one org exhausts all providers for all orgs (`pg_quota.py`)
- [ ] **H14: XSS via marked.parse()** — quota.html line 537: AI response rendered as raw HTML via innerHTML. CSP allows unsafe-inline
- [ ] **H15: Agent trust AI/admin review global** — trust tier mutations operate by name with no org_id (`admin.py:~1400`)

#### MEDIUM
- [ ] **Account enumeration** — /auth/login returns distinct errors per status (disabled/pending/rejected) (`auth.py:360-373`)
- [ ] **Registration status endpoint public** — GET /auth/registration-status leaks user existence (`auth.py:557-581`)
- [ ] **Passwordless registration** — empty password stored as "" (`auth.py:308`)
- [ ] **Community skills loader no symlink check** — main dir checks, community dir doesn't (`loader.py`)
- [ ] **Marketplace writes unsanitized content** — original content persisted, not parsed/sanitized version (`marketplace.py:203`)
- [ ] **PgAuditLog empty org_id returns all** — skips filter when org_id="" (`pg_audit.py:65`)
- [ ] **chip_config global** — banking rate affects all orgs, should be superadmin-only (`chips.py:381`)
- [ ] **PgLearningStore no per-org cap** — unlike InMemory's 10K FIFO, PG grows unbounded (`pg_learnings.py`)
- [ ] **Agent import no zip bomb protection** — decompressed size unchecked (`store.py:221`)
- [ ] **CSP unsafe-inline** — script-src allows inline scripts, negates XSS defense (`dashboard.py:23`)
- [ ] **Webhook nonce store unbounded** — no hard cap on _seen_nonces dict (`webhooks.py:32`)
- [ ] **No per-user login brute-force** — only global 300RPM rate limit, no per-user lockout
- [ ] **In-memory rate limiter not distributed** — each instance has own counters
- [ ] **Status endpoint exposes global internals** — any user sees all agent names + intent table (`agents.py /status`)
- [ ] **XSS: quota.html model names unescaped** — `m.model` in innerHTML without esc() (line 333)
- [ ] **XSS: quota.html wallet labels unescaped** — `w.label`, `w.owner_id` in innerHTML (lines 391-423)
- [ ] **XSS: quota.html breakdown r.group unescaped** — user_id/team_id in innerHTML (lines 465-488)
- [ ] **XSS: agents.html sigil unescaped** — `sigilDiv.innerHTML = sigil` (line 406)

#### LOW
- [ ] Sanitizer incomplete zero-width coverage (missing U+00AD, U+2060, U+180E, U+034F)
- [ ] Warden L2/L2.5 use `re` not `regex` (no timeout protection)
- [ ] Session history no pagination, list_users no pagination
- [ ] PII filter missing Azure, Google, Slack, Stripe, SSN patterns
- [ ] GET /auth/logout without CSRF protection
- [ ] Session decode missing issuer check for demo tokens
- [ ] Payload size middleware bypass without Content-Length header
- [ ] DNS rebinding gap in agent import URL (`agents.py:394`)
- [ ] login.html self-XSS via pendingEmail from localStorage (line 563)
- [ ] auth.js toast p.rank unescaped (line 812)
- [ ] cdn.jsdelivr.net in CSP script-src (known script gadget source)
- [ ] Profile SQL uses email without org_id (shared records if same email across orgs)

#### Supply Chain & Dependencies (2026-03-31 deep dive)
- [ ] **D1: `cryptography` 43.0.0 — 4 CVEs including TLS handshake bypass** — 3 major versions behind (current: 46.0.6). CVE-2024-12797 (HIGH: OpenSSL RFC7250 bypass), CVE-2026-26007 (HIGH), CVE-2026-34073 (HIGH), GHSA-h4gh-qq45-vh27 (MEDIUM: PKCS#12 DoS). Transitively affects ALL JWT operations. **Fix:** `pip install --upgrade cryptography>=46.0.6`
- [ ] **D2: No lock file — supply chain attack surface** — no requirements.txt, poetry.lock, or uv.lock. All deps use floor-only `>=` specifiers. Every build resolves fresh from PyPI. Dependency confusion and transitive drift are both possible. **Fix:** generate `requirements.txt` with `pip-compile --generate-hashes`, use `--require-hashes` in Dockerfile
- [ ] **D3: CDN scripts unpinned, no SRI hashes** — `cdn.tailwindcss.com` has NO version at all (dev-only CDN). Chart.js `@4` and marked.js `@15` pinned to major only. Zero `integrity=` attributes on any `<script>` tag. CDN compromise = arbitrary JS on every dashboard page. **Fix:** self-host Tailwind (production build), pin exact versions with SRI hashes, add `crossorigin="anonymous"`
- [ ] **D4: 18 known CVEs across 9 packages** — pip-audit found HIGH vulns in urllib3 (2.3.0→2.6.3), requests (2.32.3→2.33.0), h2 (4.2.0→4.3.0), pip (25.1.1→26.0), plus MEDIUM in pygments, markdown, wheel, jaraco-context. **Fix:** `pip install --upgrade urllib3 requests h2`
- [ ] **D5: MCP deployer accepts arbitrary env vars** — `body.get("env", {})` and `body.get("secrets", {})` passed directly to K8s pod spec. Any authenticated user (no admin required) can inject env vars or reference K8s secrets. **Fix:** whitelist env var names, restrict secret references, require admin role for MCP deploy
- [ ] **D6: `/greathall` and `/prompts` served without server-side auth** — served as static files in app.py lines 167-175 without `_check_auth()`. Other dashboard routes (skills, etc.) properly gate behind auth. **Fix:** move to dashboard router with auth check

#### Confirmed Non-Issues (bandit false positives)
- ~~profile.py:175 SQL injection~~ — column names from hardcoded 4-element tuple
- ~~pg_outcomes.py:114/:173 SQL injection~~ — double allowlist (route + persistence layer)
- ~~pg_audit.py:81 SQL injection~~ — column names hardcoded + frozenset guard

#### Pre-existing (from prior audits, check if already fixed)
- [x] ~~**Rate limiting**~~ — FIXED: per-user sliding window with burst limits
- [x] ~~**Payload size limit**~~ — FIXED: 1MB PayloadSizeLimitMiddleware
- [x] ~~**CORS configuration**~~ — FIXED: CORSMiddleware configured
- [ ] **DNS rebinding** — marketplace has defense, tool executor doesn't
- [ ] **No token pre-check** — quota tracker records but doesn't reject pre-call

### Architecture (remaining gaps)
- [ ] **Reactor never started** — created in container but no triggers registered
- [ ] **Skill registry global** — not per-org
- [ ] **AgentIdentity has no org_id** — agents are org-agnostic
- [ ] **No skill versioning/rollback**
- [ ] **No canary deployment for skills**

### Testing (remaining gaps)
- [ ] **Property-based cross-tenant isolation test** — should run on every commit
- [ ] **Adversarial prompt injection test suite** — systematic OWASP LLM01 coverage
- [ ] **Load/performance tests** — unknown behavior under concurrent load

### Integrations (pre-v1.0 — required for demo/pitch)

#### OpenWebUI Integration (HIGH)
- [ ] **OpenWebUI pipe plugin** — relay /v1/chat/completions through Stronghold governance
- [ ] **OIDC bridge** — OpenWebUI user → Stronghold AuthContext (org/team/user mapping)
- [ ] **Function calling relay** — OpenWebUI tools → Stronghold tool registry → Sentinel
- [ ] **Model list sync** — /v1/models proxied through so OpenWebUI sees governed models
- [ ] Docs: deployment guide (OpenWebUI + Stronghold side-by-side)

#### Agent Creator UI (HIGH)
- [ ] **POST /v1/stronghold/agents** — create agent from config (name, strategy, tools, soul prompt)
- [ ] **PUT /v1/stronghold/agents/{name}** — update agent config
- [ ] **DELETE /v1/stronghold/agents/{name}** — deregister agent
- [ ] **Dashboard: Knights create/edit wizard** — form-based agent builder with strategy picker, tool selector, soul prompt editor, trust tier assignment
- [ ] Agent templates (code agent, search agent, custom) as starting points

#### Skills Creator UI (MEDIUM-HIGH)
- [ ] **Visual skill builder** — structured form: name, description, parameters (JSON Schema editor), trust tier, groups
- [ ] **Skill test runner** — test a skill against sample input before deploying
- [ ] **Parameter schema editor** — drag-and-drop JSON Schema builder (not raw textarea)
- [ ] **Skill import from URL/GitHub** — pull community skills from repos

#### n8n Workflow Integration (MEDIUM)
- [ ] **Webhook trigger endpoint** — POST /v1/stronghold/webhooks/{hook_id} for n8n to call
- [ ] **Stronghold n8n node** — custom node: send prompt → get response (with auth, model selection)
- [ ] **Workflow templates** — common patterns: approval flow, scheduled digest, alert→action
- [ ] **Reactor → n8n bridge** — reactor events can trigger n8n webhooks
- [ ] Docs: n8n + Stronghold integration guide

#### Prompt Management + Git Integration (MEDIUM)
- [ ] **Git-backed prompt store** — prompts versioned in git repo (not just in-memory)
- [ ] **Diff viewer** — compare prompt versions side-by-side in dashboard
- [ ] **Approval workflow** — staging → review → promote to production (requires admin approval)
- [ ] **Git agent** — Artificer agent can clone repos, read files, create PRs
- [ ] **GitHub/GitLab webhook** — trigger agent on PR events, issue creation
- [ ] Prompt templates library (importable starter prompts)

#### Great Hall UX (HIGH — demo-critical)
- [ ] **Mission history sidebar** — list of previous sessions with first message preview, click to resume
- [ ] **Illustration options** — creative agent offers image generation (DALL-E/Stable Diffusion) as a follow-up after writing content (e.g., "Want me to generate a header image for this blog post?")
- [ ] **Streaming text** — stream response tokens into the conversation bubble as they arrive (currently dumps full response at end)

#### WebUI Form Enhancement (LOW)
- [ ] **Guided wizard** — step-by-step form: intent → details → constraints → expected output
- [ ] **Form templates** — pre-built forms per task type (code request, search, automation)
- [ ] **File upload** — attach files to requests (code review, document analysis)
- [ ] **Conversation history sidebar** — browse past sessions from dashboard

### Persistence + Infrastructure (HIGH — blocks scale)

#### SQLModel Migration (HIGH)
- [ ] **Add `sqlmodel` + `alembic` dependencies** — replace raw asyncpg with typed ORM
- [ ] **`AgentDefinition` model** — backed by existing `agents` table (001_initial.sql). Fields: name, version, description, soul, rules, reasoning_strategy, model, tools (ARRAY), trust_tier, preamble (bool), org_id, provenance, active. Replaces JSONB `config` blob with typed columns.
- [ ] **`PgAgentRegistry`** — async CRUD for agent definitions. Factory checks DB first, seeds from filesystem if empty. Replaces filesystem-on-every-boot pattern.
- [ ] **Migrate existing pg_* modules** — incrementally replace raw asyncpg in: pg_prompts, pg_learnings, pg_sessions, pg_quota, pg_audit, pg_outcomes with SQLModel equivalents.
- [ ] **Alembic setup** — `alembic init`, configure async engine, auto-generate migrations from model changes. Replace hand-rolled `run_migrations()` with Alembic.
- [ ] **Skill persistence** — `SkillDefinition` model in DB. 165 skills loaded from DB, not parsed from SKILL.md files on every boot. Filesystem is seed data only.

#### Redis (HIGH — blocks multi-instance)
- [ ] **Add `redis[hiredis]` dependency** — async Redis client
- [ ] **`RedisSessionStore`** — implements `SessionStore` protocol. TTL-based session expiry. Shared across instances.
- [ ] **`RedisRateLimiter`** — implements `RateLimiter` protocol. Sliding window via Redis sorted sets. Shared across instances.
- [ ] **`RedisCache`** — prompt cache, agent registry cache, skill cache. Sub-ms reads, TTL invalidation.
- [ ] **Pub/Sub event bus** — reactor events published to Redis channel. Multi-instance agents can subscribe. Replaces in-process-only Reactor for distributed deployment.
- [ ] **DI wiring** — `InMemory` | `Pg` | `Redis` per protocol, selected by config. Pattern: `session_backend: redis` in YAML.

#### Search Intelligence + Feedback Loop (HIGH)
- [ ] **Add `feedback` field to Learning/Outcome** — thumbs_up/thumbs_down/null on every response. New `POST /v1/stronghold/feedback` endpoint. Stored in outcomes table.
- [ ] **Search knowledge cache** — new `search_cache` table: query_hash, query_text, result_summary, source_urls, feedback_score (running average of thumbs), hit_count, created_at, expires_at. Redis for hot cache, PostgreSQL for persistence.
- [ ] **Ranger instant-answer path** — before hitting any search backend, Ranger checks the search cache by semantic similarity (pgvector embedding match). If a high-scoring cached answer exists (feedback_score > 0.7, hit_count > 3), return it immediately with a "cached answer" flag.
- [ ] **Feedback-weighted promotion** — thumbs_up increments a quality score, thumbs_down decrements it. Answers below threshold (-3) are evicted from cache. Answers above threshold (+5) are promoted to "trusted" and get longer TTL.
- [ ] **Search backend tiering** — Ranger tries backends in order: (1) instant cache hit, (2) Brave API for factual/structured queries, (3) Perplexity API for deep research/synthesis, (4) Google CSE as fallback. No SearXNG — clean APIs only, no scraping gray areas.
- [ ] **Brave Search API integration** — add `BRAVE_API_KEY` to config, implement `brave_search` tool executor. "Data for AI" tier ($3/1K queries, AI use explicitly permitted). Primary search backend.
- [ ] **Perplexity API integration** — add `PERPLEXITY_API_KEY` to config, implement `perplexity_search` tool executor. Deep research only — complex/synthesis queries where Brave returns shallow results.
- [ ] **Google Custom Search API** — add `GOOGLE_CSE_KEY` + `GOOGLE_CSE_CX` to config. Fallback when Brave is down or for domain-specific searches. ($5/1K queries after free 100/day).
- [ ] **Feedback UI** — thumbs up/down buttons on every response in the Great Hall dashboard. Maps to `POST /v1/stronghold/feedback`.

#### Da Vinci + Canvas Tool (image generation) (MEDIUM)
- [ ] **Wire Da Vinci agent into container** — register in factory, add `image` task type to classifier + intent registry. Preamble template already handles capabilities/boundaries.
- [ ] **Canvas tool executor** — single tool with 5 actions (generate, refine, reference, composite, text). Calls LiteLLM `/images/generations` for generate/refine, canvas compositor for composite/text.
- [ ] **Draft/proof model selection** — tool tier parameter selects from model priority lists (free Google models first, paid Together models as fallback).
- [ ] **Canvas compositor service** — layer assembly (background + characters + objects + text), position/scale/rotate per layer, PNG/WebP output.
- [ ] **Wire Fabulist agent** — children's storybook creator, uses canvas tool, add `storybook` task type to classifier.

### Documentation
- [ ] Update SECURITY.md with L2.5/L3 descriptions
- [ ] API documentation (OpenAPI spec review)

---

## Roadmap

### v1.0: Ship It
- Fix remaining security gaps (rate limiting, payload size, CORS, session validation)
- OpenWebUI integration (pipe plugin + OIDC bridge)
- Agent creator (API + dashboard wizard)
- Skills creator enhancement (visual builder + test runner)
- **SQLModel + Alembic migration** (typed persistence, proper migrations)
- **Redis** (sessions + rate limiting for multi-instance)
- Property-based isolation tests
- Tag and push to GitHub
- Docker image + Helm chart skeleton

### v1.1: Blue Team + Workflows + Local Identity
- **Local user management** — Stronghold-native user/team/org store (argon2 passwords, CRUD endpoints, admin UI). Replaces LiteLLM dependency for identity. Email+password login via same BFF HttpOnly cookie flow.
- Warden L3: fine-tuned classifier (use bouncer training set + generate more)
- Output classifier: detect jailbreak in responses
- n8n integration (webhook triggers + custom node)
- Git-backed prompt store + approval workflow
- Git agent (clone, read, PR creation)
- Canary tokens in system prompts
- Multi-turn intent tracking
- Episodic memory retrieval scanning

### v1.2: Self-Evolution Security
- Skill versioning with rollback
- Canary deployment for skills
- Tournament-based skill promotion
- Learning promotion requires approval gate
- Automated security re-scan via reactor triggers

### v2.0: Enterprise GA
- Per-tenant security policy configuration
- Compliance reporting (EU AI Act, SOC 2)
- Multi-turn adversarial tracking
- Adversarial fine-tuning feedback loop
- Full Helm chart + Terraform modules

---

## Session Log

### 2026-03-28: Initial Build Sprint
- Built Phases 1-3.5, 4 deep reviews, 1 red team, 1 OWASP audit
- 819 → 1043 tests, ~25 bugs fixed

### 2026-03-28: Security Hardening + Tooling
- 2 enterprise security audits (30+ findings)
- Built Warden L2.5 (semantic tool-poisoning, 62.5% detection, 0% FP)
- Built Warden L3 (few-shot LLM classifier, flag-and-warn pattern)
- Fixed all unauthenticated endpoints, XSS, SSRF, IDOR, org isolation
- Added bouncer training data (213 samples) for L3 development
- 1043 → 1112 tests
- Optimized Claude Code setup: CLAUDE.md boundaries, hooks, skills, feedback memories

### 2026-03-29: Login Page + BFF Authentication
- Built dedicated login page (`/login`) with Oz/fortress gate theme
- BFF (Backend-for-Frontend) pattern: server-side OIDC token exchange, HttpOnly cookies
- `CookieAuthProvider` — extracts JWT from HttpOnly cookie, delegates to JWTAuthProvider
- `POST /auth/token` — server-side code exchange with CSRF protection (X-Stronghold-Request)
- `POST /auth/login` — demo login with user/org/team context (HS256 self-signed JWT)
- `POST /auth/logout` — clears session cookie
- `GET /auth/session` — returns user info from cookie (no token exposed to JS)
- `GET /auth/config` — non-sensitive OIDC config for frontend
- Shared `auth.js` guard — auto-redirect to /login, supports both cookie + API key auth
- Cloudflare Access JWT pre-fill on login page
- Updated all 6 dashboard pages: removed prompt()-based auth, added auth guard + logout
- Added OIDC config fields: client_id, client_secret, authorization_url, token_url
- Env vars: STRONGHOLD_AUTH_CLIENT_ID, STRONGHOLD_AUTH_CLIENT_SECRET, etc.
- Backlogged local user management (argon2 passwords, CRUD) for v1.1 — LiteLLM covers identity for now
- 1112 → 2029 tests, mypy --strict clean on all new files

### 2026-03-30: Enterprise Security Audit Round 3
- Full-scope audit: multi-tenant isolation, auth, injection, input validation, DoS, secrets
- 3 parallel deep-dives: SQL injection trace, innerHTML/XSS inventory, admin route org_id coverage
- **42 total findings**: 7 CRITICAL, 15 HIGH, 18 MEDIUM, 12 LOW
- CRITICAL: PgAgentRegistry (3 cross-tenant), PgPromptManager (1), learning approve/reject (1), MCP delete (1), user roles (1)
- HIGH: ArtificerStrategy missing all security checks, Warden scan window gap, L3 fail-open, semantic bypass, JWT key reuse, agent CRUD unscoped, strike management unscoped
- Bandit SQL injection findings: all 3 confirmed FALSE POSITIVES (hardcoded allowlists + parameterized values)
- innerHTML audit: 3 DANGEROUS (marked.parse XSS, unescaped model names, self-XSS), 4 RISKY, rest SAFE
- Admin route audit: 56 routes catalogued, 15 cross-tenant gaps found
- 41 regression tests written (`tests/security/test_security_audit_2026_03_30.py`), all pass
- 2029 → 2785 tests passing (41 new + test expansion from other work), 0 regressions

### 2026-03-31: Live Red Team Exercise
- Multi-vector attack against running Stronghold stack (17 attack vectors)
- **17 new infrastructure findings** (R1-R17) — deployment/container layer, not covered by prior code audits
- 6 CRITICAL: privileged containers (2), kubeconfig mounted, real API keys on disk, weak PG password, env var secrets
- 5 HIGH: OpenAPI exposed, SYSTEM_AUTH privilege escalation, missing security headers, CORS misconfiguration, unvalidated agent tools, LiteLLM AppArmor, OpenWebUI auth disabled
- 4 MEDIUM: short API key accepted, tool_result sanitizer gap, health endpoint info leak, JWT key reuse (confirmed H5)
- **Defenses that held:** Warden caught 3/3 injection attempts (account locked after 2 strikes), SSRF blocked all bypass attempts (IPv6, decimal IP, DNS resolution), trust tiers correctly server-side, self-registration disabled, MCP registry allowlist, CSRF protection
- All findings added to backlog as R1-R28 with exact file:line references and fix descriptions
- Evil agent created during test was cleaned up post-exercise
- **Wave 2** (deeper exploitation): JWT forgery → full admin via cookie, cross-tenant agent visibility, direct LiteLLM governance bypass, container→host SSH, JSON bomb token exhaustion, supply chain audit (all deps current, alg:none correctly rejected)
- **Wave 3** (advanced evasion): scan window gap bypass confirmed (input Warden missed, output Sentinel caught), learning poisoning blocked by Warden scan, strike persistence gap (in-memory = lost on restart), forged JWT budget consumption, prompt PUT 500 error
- **Total: 28 infrastructure/deployment findings** (R1-R28): 11 CRITICAL, 9 HIGH, 8 MEDIUM
- **Combined with code audit: 70 security findings** across 4 audit rounds
