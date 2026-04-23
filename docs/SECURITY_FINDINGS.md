# Security Findings — Edge-Case Review Log

Running log of security findings uncovered via mutation-testing / edge-case
review. Each finding has a `SEC-NNN` identifier, a backing regression test
in `tests/test_security_regressions.py` or `tests/test_deep_edge_cases.py`,
and a commit that ships the fix.

**Methodology.** For each module, ask:

1. What's the minimal broken implementation that passes the existing tests?
2. What inputs would a security researcher try?
3. What invariants could be violated through state machine edges?
4. Where does the code implicitly trust its inputs?

**Rule:** no finding is closed until there's a named regression test whose
failure message points directly back at this log.

---

## Findings

### SEC-001 — file_ops prefix collision sandbox escape
- **Severity:** HIGH
- **File:** `src/stronghold/tools/file_ops.py`
- **Bug:** `str(target).startswith(str(ws.resolve()))` matched
  `/tmp/work-evil/secret.txt` when the workspace was `/tmp/work`, because
  `"/tmp/work-evil/..."` is a string-prefix of `"/tmp/work"`.
- **Impact:** A user could read files in a sibling directory that happens to
  share a prefix with their workspace.
- **Fix:** Use `Path.relative_to(ws_resolved)` instead of string `startswith`.
- **Regression test:** `test_sec001_prefix_collision_sandbox_escape`
- **Commit:** `cd99425`

### SEC-002 — file_ops symlink escape
- **Severity:** HIGH
- **File:** `src/stronghold/tools/file_ops.py`
- **Bug:** `resolve()` followed symlinks inside the workspace. A symlink
  `<workspace>/escape -> /tmp` made `target.startswith(workspace)` false,
  which happened to look correct — but the code could still `list()` the
  symlink's contents before the prefix check fired for the outer call.
- **Impact:** Sandbox escape via user-planted symlinks.
- **Fix:** Same `relative_to` fix as SEC-001; the resolved real path is
  compared against the resolved workspace, so symlinks pointing outside
  are rejected by containment check.
- **Regression test:** `test_sec002_symlink_escape_via_workspace`
- **Commit:** `cd99425`

### SEC-003 — shell_exec command injection via semicolon
- **Severity:** CRITICAL
- **File:** `src/stronghold/tools/shell_exec.py`
- **Bug:** Allowlist only checked `cmd.startswith("echo")` etc. A command
  like `echo hi; rm -rf victim.txt` passed the allowlist, then the shell
  executed the `rm` part.
- **Impact:** Arbitrary command execution bounded only by the sandbox
  container permissions. In dev, full host access.
- **Fix:** Reject a set of shell metacharacters (`; | & \` $( ${ > < \n \r`)
  *before* the allowlist check.
- **Regression test:** `test_sec003_shell_injection_via_semicolon` plus
  `test_shell_metacharacter_variants_all_rejected` as a sweep.
- **Commit:** `cd99425`

### SEC-004 — shell_exec injection via `$(...)` command substitution
- **Severity:** CRITICAL
- **File:** `src/stronghold/tools/shell_exec.py`
- **Bug:** `echo $(rm victim.txt)` passed the allowlist.
- **Fix:** Same metachar reject as SEC-003 (`$(` is in the block list).
- **Regression test:** `test_sec004_shell_injection_via_command_substitution`
- **Commit:** `cd99425`

### SEC-005 — shell_exec injection via pipe to disallowed command
- **Severity:** CRITICAL
- **File:** `src/stronghold/tools/shell_exec.py`
- **Bug:** `ls | xargs rm` passed because `ls` is allowed.
- **Fix:** Pipe `|` rejected by metachar check.
- **Regression test:** `test_sec005_shell_injection_via_pipe`
- **Commit:** `cd99425`

### SEC-006 — session_store crash on poisoned JSON
- **Severity:** MEDIUM
- **File:** `src/stronghold/cache/session_store.py`
- **Bug:** `json.loads(item)` ran inside a loop without a try/except.
  One corrupt entry (from a legacy format, a partial write, or a malicious
  inject) raised `JSONDecodeError` and killed the whole `get_history` call
  — meaning one bad entry effectively denial-of-services the entire session.
- **Fix:** Per-entry try/except; log and skip poisoned entries, return
  whatever is valid.
- **Regression test:** `test_sec006_session_store_poisoned_json_does_not_crash`
- **Commit:** `cd99425`

### SEC-007 — file_ops null byte in path raises ValueError
- **Severity:** MEDIUM
- **File:** `src/stronghold/tools/file_ops.py`
- **Bug:** `resolve()` raised on an embedded NUL before the sandbox check
  ran, propagating an unhandled exception to the caller.
- **Impact:** Pollutes logs with tracebacks; a clever attacker could use
  exception content to fingerprint behavior; minor DoS vector.
- **Fix:** Wrap `resolve()` in try/except, return clean `ToolResult(error=...)`.
- **Regression test:** `test_sec007_null_byte_in_path`
- **Commit:** `cd99425`

### SEC-008 — coins `_decimal` accepts NaN / Infinity
- **Severity:** MEDIUM
- **File:** `src/stronghold/quota/coins.py`
- **Bug:** `Decimal("NaN")` constructs a NaN value. Any comparison against
  NaN (`budget > limit`) returns `False`. A user submitting `"NaN"` as a
  budget amount would silently bypass *all* budget enforcement.
- **Impact:** Budget bypass. User could run unlimited requests.
- **Fix:** After parsing, check `is_nan() or is_infinite()` and return
  the default value.
- **Regression tests:** `test_sec008_decimal_rejects_nan`,
  `test_sec008_coin_budget_nan_does_not_bypass`
- **Commit:** `cd99425`

### SEC-009 — session_store `append_messages` crashes on non-dict entries
- **Severity:** MEDIUM
- **File:** `src/stronghold/cache/session_store.py`
- **Bug:** `msg.get("role", "")` raised `AttributeError: 'str' object has
  no attribute 'get'` when messages contained anything other than a dict
  (e.g., a malformed LLM response, an upstream serialization bug).
- **Impact:** One malformed message takes down session writes for that user.
- **Fix:** `isinstance(msg, dict)` guard before `.get()` calls.
- **Regression test:** `test_sec009_non_dict_message_skipped`
- **Commit:** `e817043`

### SEC-011 — agents/factory crashes on `tools: null` in YAML
- **Severity:** MEDIUM
- **File:** `src/stronghold/agents/factory.py`
- **Bug:** `tuple(manifest.get("tools", ()))` raised `TypeError: 'NoneType'
  object is not iterable` when YAML had `tools: null` or `tools:` with no
  value. Same bug affected `skills`, `rules`, `model_fallbacks`, `phases`.
- **Impact:** Any agent.yaml with an empty list field crashes loader.
- **Fix:** `_safe_tuple` helper that returns `()` for None, wraps single
  strings in a 1-tuple, and handles list/tuple/other correctly. Applied
  to all five fields.
- **Regression test:** `test_sec011_manifest_with_none_tools`,
  `test_sec011_all_list_fields_none_safe`
- **Commit:** (next)

### SEC-012 — agents/factory iterates `tools: "shell"` as characters
- **Severity:** MEDIUM
- **File:** `src/stronghold/agents/factory.py`
- **Bug:** `tuple("shell")` returns `('s','h','e','l','l')`. A common YAML
  mistake (`tools: "shell"` instead of `tools: [shell]`) silently produced
  an agent with 5 single-character "tools". The loader would then fail at
  runtime when none of those "tools" resolve to real tools, but the
  failure would be confusing.
- **Fix:** `_safe_tuple` detects strings and wraps them in a 1-tuple
  (lenient interpretation).
- **Regression test:** `test_sec012_manifest_with_string_tools`
- **Commit:** (next)

### SEC-013 — conduit consent maps grow without bound
- **Severity:** MEDIUM (memory exhaustion / DoS)
- **File:** `src/stronghold/conduit.py`
- **Bug:** `_session_agents` had a cap of `_MAX_STICKY_SESSIONS = 10_000`
  with eviction. `_session_consents` and `_consent_pending` were also
  populated on every consent-related request but had NO cap — an attacker
  that can trigger the consent path across many session IDs could exhaust
  memory.
- **Fix:** Add `_MAX_CONSENT_ENTRIES = 10_000` constant and evict oldest
  entries on every write to either consent map.
- **Regression test:** `test_sec013_consent_maps_have_eviction_cap_constant`,
  `test_sec013_eviction_code_present`
- **Commit:** (next)

### SEC-014 — `/admin/coins/convert` crashes on non-numeric `copper_amount`
- **Severity:** MEDIUM
- **File:** `src/stronghold/api/routes/admin.py`
- **Bug:** `int(body.get("copper_amount", 0))` raised uncaught `ValueError`
  on `"not-a-number"`, `"10.5"`, or any non-integer string, returning a
  500 instead of a 400. Leaked stack trace in response body (FastAPI default).
- **Impact:** Clear 500 vs 400 is a soundness issue; no auth bypass.
- **Fix:** Wrap `int()` in try/except, return `HTTPException(400)`.
- **Regression test:** `test_convert_non_numeric_copper_amount`
- **Commit:** (next)

### SEC-010 — scanner `detect_todo_fixme` crashes on non-UTF-8 files
- **Severity:** MEDIUM
- **File:** `src/stronghold/tools/scanner.py`
- **Bug:** `read_text(encoding="utf-8")` raised `UnicodeDecodeError` on
  non-UTF-8 `.py` files. Would take down the `/v1/stronghold/mason/scan`
  endpoint for any repo containing a binary-ish file named `*.py`.
- **Impact:** API endpoint crashes; DoS via repo content.
- **Fix:** try/except around `read_text`; skip unreadable files.
  `detect_untested_modules` already had this guard; `detect_todo_fixme`
  did not.
- **Regression test:** `test_sec010_binary_file_does_not_crash`
- **Commit:** `e817043`

---

## Documented Limitations (Not Bugs)

These came out of the same reviews but are intentional / acceptable:

- **LIM-001** — `RedisPromptCache.set(key, None)` is indistinguishable from
  "key missing" on subsequent `get`. Callers should not store `None` as a
  valid value. Documented via test.

- **LIM-002** — `_find_model` is case-sensitive. `"GPT-4"` does not match
  `"gpt-4"`. Callers are expected to normalize before lookup.

- **LIM-003** — `shell_exec` rejects shell metacharacters inside quotes
  (`echo "hi; done"`). The shell would treat `;` as literal, but our check
  is conservative and rejects it anyway to avoid parsing quote state.
  Tradeoff: conservative false positive, safer.

- **LIM-004** — `triggers.canary_deployment_check` propagates exceptions
  from `canary_manager.check_promotion_or_rollback` instead of swallowing
  them. The reactor is expected to isolate trigger failures at its layer.
  Verified by regression test.

- **LIM-005** — `config/loader._validate_url_not_private` resolves DNS at
  config-load time. A DNS rebinding attacker (control over the hostname's
  A record) could return a public IP during validation, then a private IP
  during the actual HTTP request. The code falls back to "warn only" when
  DNS fails (container startup case), which widens the window. Mitigation:
  the HTTP client layer should re-check resolved IPs at connect time.
  Documented by `test_dns_failure_logs_warning_not_error`.

- **LIM-006** — `conduit.determine_execution_tier` allows an agent to
  downgrade a user-classified P0 request to P5. Test documents this as
  current behavior; whether it's intended is a product decision (operator
  agents may legitimately process critical requests in batch). Not a
  security bug unless paired with a compromised agent definition.

- **LIM-007** — `workspace._ensure_clone` embeds `owner` and `repo` into
  a URL string. An owner like `--upload-pack=/bin/sh` is embedded as a
  URL path segment (not a separate argv), so git URL parsing rejects it.
  However, `repo=../other` could produce a URL like
  `https://github.com/owner/../other.git` — git treats this as a URL
  segment, not a local path. The generated local destination
  (`self._base / "repos" / repo`) contains `..` which could escape the
  base directory. Callers (Mason assign route) validate owner/repo via
  GitHub webhook payload, so untrusted input is not currently a path,
  but the code does no explicit validation.

- **LIM-008** — `agents/factory._safe_tuple` uses lenient interpretation
  for strings (wraps `"shell"` as `("shell",)`). A stricter implementation
  would reject strings entirely and require lists. Tradeoff: lenient is
  friendlier to YAML writers but silently accepts the wrong schema.

---

## Review Coverage

| Module | Reviewed | Bugs found |
|--------|---------|-----------|
| `tools/file_ops.py` | ✅ | 3 (SEC-001, 002, 007) |
| `tools/shell_exec.py` | ✅ | 3 (SEC-003, 004, 005) |
| `tools/scanner.py` | ✅ | 1 (SEC-010) |
| `cache/session_store.py` | ✅ | 2 (SEC-006, 009) |
| `cache/rate_limiter.py` | ✅ | 0 |
| `cache/prompt_cache.py` | ✅ | 0 |
| `quota/coins.py` | ✅ | 1 (SEC-008) |
| `triggers.py` | ✅ | 0 |
| `api/routes/mason.py` | ✅ | 0 (HMAC verified) |
| `conduit.py` | ✅ | 1 (SEC-013) |
| `tools/workspace.py` | ✅ | 0 (git subprocess safe via list args; URL-path injection documented) |
| `agents/factory.py` | ✅ | 2 (SEC-011, SEC-012) |
| `config/loader.py` | ✅ | 0 (IP checks solid; DNS rebinding documented as LIM-005) |
| `api/routes/admin.py` (coins) | ✅ | 1 (SEC-014) |
