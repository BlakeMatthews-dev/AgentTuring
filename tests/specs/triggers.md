# Spec: `src/stronghold/triggers.py`

**Purpose:** Registers the 10 core reactor triggers (learning promotion, rate-limit eviction, outcome stats, security rescan, post-tool learning, tournament, canary, RLHF feedback, issue-backlog scanner, Mason PR review) that run on the container's reactor loop.

**Coverage:** 90% (143/159). Missing: 50, 211-212, 244-246, 317-318, 337-348, 394-395.

## Test strategy

- Build a fake `Container` with only the attributes each trigger reads (no real services).
- Call `register_core_triggers(fake_container)` then invoke the registered handlers directly by looking them up in `reactor._triggers` (or by capturing them as `register()` is called).
- Each async handler takes an `Event`; construct `Event(name=..., data={...})` with the expected keys.
- Mock `httpx.AsyncClient` for the issue-backlog scanner; patch `stronghold.tools.github._get_app_installation_token` for the token branch.

All tests call the inner handlers directly — this gives unit-level coverage of branch points without running the reactor loop.

---

## `register_core_triggers(container)` — entry point

**Contract:** Registers exactly 10 triggers on `container.reactor`, emits an info log `"Registered <n> core triggers"`.

**Invariants:**
- Trigger names are unique.
- Interval-mode triggers have `interval_secs` set; event-mode triggers have an `event_pattern` regex.
- All handlers are async and return a dict.

**Test cases:**

1. `test_registers_all_ten_triggers` — after call, `reactor._triggers` has entries for exactly these names: `learning_promotion_check, rate_limit_eviction, outcome_stats_snapshot, security_rescan, post_tool_learning, tournament_evaluation, canary_deployment_check, rlhf_feedback, issue_backlog_scanner, mason_pr_review`.

2. `test_registers_log_count_matches` — caplog at INFO has message `"Registered 10 core triggers"`.

3. `test_trigger_modes_and_patterns_correct` — `security_rescan` and `post_tool_learning` and `rlhf_feedback` and `mason_pr_review` are EVENT mode with non-empty `event_pattern`; the other six are INTERVAL mode.

---

## `_check_learning_promotions` (line 50 uncovered)

**Contract:** If container has `learning_promoter` attr and truthy → awaits `.check_and_promote()` and returns `{"promoted_count": len(returned list)}`. Else `{"skipped": True}`.

**Uncovered:**
- **50** — the `return {"skipped": True}` branch when the attribute is absent/None.

**Test cases:**

1. `test_learning_promotion_happy_path` — `container.learning_promoter.check_and_promote` returns `[..., ...]` (3 items) → handler returns `{"promoted_count": 3}`.
2. `test_learning_promotion_skipped_when_missing` — container has no `learning_promoter` attr → `{"skipped": True}`.
3. `test_learning_promotion_skipped_when_none` — `container.learning_promoter = None` → `{"skipped": True}`.

---

## `_evict_stale_rate_keys` (already well covered)

**Contract:** reads `container.rate_limiter._windows` before/after `._evict_stale_keys(monotonic_now)`; returns `{"evicted": delta}`. Logs debug when `evicted > 0`.

**Test cases:**

1. `test_eviction_counts_removed_keys` — fake rate_limiter with `_windows={"a":..., "b":...}` and `_evict_stale_keys` that clears one key → returns `{"evicted": 1}`.
2. `test_eviction_zero_when_no_stale_keys` — `_evict_stale_keys` no-op → `{"evicted": 0}`.

---

## `_snapshot_outcome_stats`

**Contract:** Awaits `container.outcome_store.get_task_completion_rate()`; returns its dict; debug log.

**Test cases:**

1. `test_snapshot_returns_store_dict` — fake returns `{"total": 20, "rate": 0.85}` → handler returns same.

---

## `_security_rescan` (lines 211-212 uncovered)

**Contract:**
- Reads `event.data["content"]` and `event.data.get("boundary","tool_result")`.
- If content empty → `{"skipped": True}`.
- Else awaits `container.warden.scan(content, boundary)`; returns `{"clean": verdict.clean, "flags": list(verdict.flags)}`.
- Logs warning when `not verdict.clean`.

**Uncovered:**
- **211-212** — the `if not verdict.clean` warning branch.

**Test cases:**

1. `test_security_rescan_empty_content_skipped` — `event.data={}` → `{"skipped": True}`.
2. `test_security_rescan_clean` — warden returns `clean=True, flags=()` → `{"clean": True, "flags": []}`; no warning log.
3. `test_security_rescan_dirty_logs_warning` — warden returns `clean=False, flags=("prompt_injection",)` → `{"clean": False, "flags": ["prompt_injection"]}`; warning log includes `"Security rescan flagged"`.
4. `test_security_rescan_custom_boundary` — pass `boundary="user_msg"`; assert warden.scan called with that string.

---

## `_post_tool_learning` (lines 244-246 uncovered)

**Contract:** Reads `tool_name` and `success` from event.data. If `success is False` and `tool_name` truthy → debug log "learning extraction opportunity". Always returns `{"tool_name": ..., "success": ...}`.

**Uncovered:**
- **244-246** — the failure branch that emits the debug log.

**Test cases:**

1. `test_post_tool_success_no_log` — `success=True, tool_name="x"` → no "learning extraction" log.
2. `test_post_tool_failure_logs_debug` — `success=False, tool_name="github"` → caplog DEBUG contains `"Tool failure on github"`.
3. `test_post_tool_failure_without_name_no_log` — `success=False, tool_name=""` → no log.

---

## `_tournament_check`

**Test cases:**

1. `test_tournament_happy_path` — `container.tournament.get_stats → {"wins":3}` → handler returns same dict.
2. `test_tournament_skipped_when_missing` — no attr → `{"skipped": True}`.

---

## `_canary_check` (lines 317-318 uncovered)

**Contract:** Iterates `container.canary_manager.list_active()`; for each deploy, calls `check_promotion_or_rollback(skill_name)`; logs info when result in `{rollback, advance, complete}`; returns `{"active_canaries": count}`. Skipped when manager missing.

**Uncovered:**
- **317-318** — the info-log branch for advance/rollback/complete results.

**Test cases:**

1. `test_canary_skipped_when_no_manager` → `{"skipped": True}`.
2. `test_canary_logs_on_advance` — list_active returns 1 deploy; `check_promotion_or_rollback → "advance"` → INFO log matches `"Canary .* → advance"`; returns `{"active_canaries": 1}`.
3. `test_canary_no_log_on_noop` — result `"ok"` → no INFO log; still `{"active_canaries": N}`.

---

## `_rlhf_feedback`

**Contract:** If `event.data["review_result"]` missing → `{"skipped": True}`. Else lazily creates `container._feedback_loop` (singleton) and awaits `.process_review(review_result)`; returns `{"stored_learnings": <count>}`.

**Test cases:**

1. `test_rlhf_no_review_skipped` — empty data → `{"skipped": True}`.
2. `test_rlhf_happy_path` — review_result dict; patch `FeedbackLoop` class to return a fake; first call creates `_feedback_loop`; returns `{"stored_learnings": 2}`.
3. `test_rlhf_reuses_existing_loop_instance` — two sequential calls; `_feedback_loop` attr is the same object the second call; FeedbackLoop constructor invoked exactly once.

---

## `_scan_issue_backlog` (lines 337-348 uncovered)

**Contract:** Uses `_get_app_installation_token("gatekeeper")`, falls back to `GITHUB_TOKEN` env. If no token → `{"skipped": True, "reason": "no github token"}`. GETs `/repos/Agent-StrongHold/stronghold/issues?labels=builders&state=open`. Filters: drops PRs (has `pull_request`), drops issues with any of `in-progress, blocked, wontfix, duplicate`. Caps concurrency at 3 (or `max_concurrent - in_progress` from `container.mason_queue`). For each surviving issue: triage (atomic vs needs-decomposition) via labels or body heuristic; POSTs triage labels (best-effort); dispatches to `BuilderPipeline` or emits `pipeline.issue_ready` if no orchestrator.

**Uncovered:**
- **337-348** — the fallback path when the `_get_app_installation_token` import fails (`ImportError`) AND the env var GITHUB_TOKEN is set. Test must force ImportError via monkeypatching module lookup, then assert env token path taken.

**Test cases:**

1. `test_backlog_skipped_without_token` — patch helper → `""`, unset env → `{"skipped": True, "reason":"no github token"}`.

2. `test_backlog_import_error_falls_back_to_env_token`
   - Setup: monkeypatch `stronghold.tools.github._get_app_installation_token` to trigger ImportError on its import (e.g., remove the submodule in `sys.modules`).
   - `GITHUB_TOKEN="envtok"`; mock httpx to return empty list.
   - Expect: handler returns `{"scanned":0, "dispatched":0}`; no raise.

3. `test_backlog_api_error_returns_error_dict` — mock httpx → 500 → `{"error":"GitHub API returned 500"}`.

4. `test_backlog_exception_returns_error_dict` — mock httpx → raises → `{"error": <str>}`; warning log.

5. `test_backlog_filters_out_prs` — issue list includes one with `pull_request` key → actionable list excludes it; `dispatched == 0` when only PR present.

6. `test_backlog_filters_skip_labels` — issues labeled `in-progress` → skipped.

7. `test_backlog_atomic_heuristic_selects_small_body` — issue with 100-char body, no checkboxes/sections → triage sends `"atomic"` label.

8. `test_backlog_decomposable_heuristic_on_long_body` — 600-char body → triage sends `"needs-decomposition"`.

9. `test_backlog_respects_mason_queue_concurrency` — `mason_queue.list_all` returns 2 in-progress; issues list has 5 actionable → dispatched ≤ 1.

10. `test_backlog_emits_pipeline_event_when_no_orchestrator` — no `orchestrator` attr on container → `reactor.emit` called with `pipeline.issue_ready` event.

11. `test_backlog_calls_builder_pipeline_when_orchestrator_present`
    - Setup: patch `BuilderPipeline` constructor to return a fake; `container.orchestrator = object()`.
    - Expect: pipeline.execute awaited once per actionable issue with `skip_decompose=is_atomic`.

---

## `_mason_pr_review` (lines 394-395 uncovered)

**Contract:** Missing `pr_number` → `{"skipped": True}`. Else awaits `container.route_request(...)` with system auth and `intent_hint="code_gen"`. Exception → returns `{"pr_number", "status":"failed", "error": str(e)}`; warning log.

**Uncovered:**
- **394-395** — the exception-wrapping branch.

**Test cases:**

1. `test_mason_review_skipped_without_pr_number` — `event.data={}` → `{"skipped": True}`.

2. `test_mason_review_success` — `container.route_request` awaited successfully → returns `{"pr_number":7, "status":"completed"}`; info log `"Mason completed PR review #7"`.

3. `test_mason_review_failure_wraps_error`
   - Setup: `container.route_request` raises `RuntimeError("llm down")`.
   - Action: await handler with `event.data={"pr_number":7,"owner":"o","repo":"r"}`.
   - Expect: returns `{"pr_number":7, "status":"failed", "error":"llm down"}`; warning log.

4. `test_mason_review_prompt_includes_pr_number` — assert `messages[0]["content"]` contains `"PR #7"` and `"o/r"`.

---

## Intentionally uncovered

None — every listed missing line is reachable with the right event + container fake.

## Contract gaps

- The ImportError branch (337-348) is defensive-coding for a scenario that can't happen under normal packaging (since the import is literal `from stronghold.tools.github import ...`). Arguably dead code, but the test harness can force it by deleting from `sys.modules`. If the team decides it's dead code, remove rather than test.
- `_scan_issue_backlog` labeling POST is swallowed with bare `except Exception: pass` — tests confirm behavior but can't assert log since there isn't one. Flag for future: log the swallowed label-POST failure.

## Estimated tests: **~30 tests** across 10 triggers + registration entry-point (3).
