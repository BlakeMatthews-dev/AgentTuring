# Spec: `src/stronghold/tools/github.py`

**Purpose:** REST-API client implementing the ToolExecutor protocol for Mason's GitHub operations (issues, branches, PRs, comments, reviews, labels, merges), authenticating as a GitHub App installation token or a PAT.

**Coverage:** 70% (155/222). Missing: 122-124, 137, 142-144, 193, 263, 419-447, 456-468, 472-486, 494-507, 511-525, 529-541.

## Test strategy

Handlers import `httpx` lazily inside each method. Use `httpx.MockTransport` installed via monkeypatching `httpx.AsyncClient.__init__` to inject `transport=`, or use `respx` if already a test dep. All network paths must be mocked; no real GitHub calls.

---

## `_get_app_installation_token(bot: str = "gatekeeper") -> str`

**Contract:**
- Input: bot name (gatekeeper|archie|mason|quartermaster).
- Output: installation token string or `""` on any failure (never raises).
- Side effects: reads PEM from disk, POSTs to `https://api.github.com/app/installations/{id}/access_tokens`.
- Invariants: never raises; returns str; unknown bot name silently falls back to `gatekeeper` registry entry; env vars `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_APP_INSTALLATION_ID` override registry values.

**Uncovered branches:**
- **122-124** — PyJWT ImportError path. Returns `""` with debug log "PyJWT not installed".
- **137** — empty `app_id` or `installation_id` after env override. Returns `""` without I/O.
- **142-144** — FileNotFoundError on PEM path. Returns `""` with debug log containing the path.

**Test cases:**

1. `test_token_returns_empty_when_pyjwt_missing`
   - Setup: `monkeypatch.setitem(sys.modules, "jwt", None)`.
   - Action: `_get_app_installation_token("gatekeeper")`.
   - Expect: returns `""`; `caplog` at DEBUG contains "PyJWT not installed".

2. `test_token_returns_empty_when_env_override_blanks_app_id`
   - Setup: `monkeypatch.setenv("GITHUB_APP_ID", "")`.
   - Action: call with any bot.
   - Expect: `""`; no file read attempted (spy on `open`).

3. `test_token_returns_empty_when_key_file_missing`
   - Setup: `monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "/does/not/exist.pem")`, valid app_id/install_id.
   - Action: call.
   - Expect: `""`; debug log mentions "private key not found"; no HTTP attempt.

4. `test_token_returns_empty_on_http_exception`
   - Setup: valid PEM in tmp_path, mock `httpx.post` to raise `httpx.ConnectError`.
   - Action: call.
   - Expect: `""`; warning log with `exc_info=True`.

5. `test_token_success_returns_token_string`
   - Setup: tmp PEM; mock `httpx.post` returning 200 with `{"token": "ghs_abc"}`.
   - Action: call with `bot="mason"`.
   - Expect: returns `"ghs_abc"`; info log `"GitHub App token generated for bot=mason"`; POST URL used `mason`'s installation_id (123362160).

6. `test_token_unknown_bot_falls_back_to_gatekeeper`
   - Action: `_get_app_installation_token("nonexistent")`.
   - Expect: uses `gatekeeper` registry entry (installation_id 123359098 in POST URL).

---

## `GitHubToolExecutor.__init__(token="", bot="gatekeeper")`

**Contract:** Resolves `self._token` via: App token → explicit param → `GITHUB_TOKEN` env → `""`. Stores `bot`, `_base_url = "https://api.github.com"`.

**Test cases:**

1. `test_init_prefers_app_token_over_param` — patch helper → `"app_tok"`; pass `token="pat"`; assert `_headers()["Authorization"] == "Bearer app_tok"`.
2. `test_init_falls_back_to_param_when_app_token_empty` — helper returns `""`; pass `token="pat"`; `Authorization == "Bearer pat"`.
3. `test_init_falls_back_to_env_var` — helper `""`, no param, `GITHUB_TOKEN="envtok"`; `Authorization == "Bearer envtok"`.
4. `test_headers_omit_authorization_when_no_token` — all sources empty; `_headers()` lacks `Authorization` key; still has `Accept` and `X-GitHub-Api-Version`.
5. `test_name_property_is_github` — `exec.name == "github"`.

---

## `execute(arguments)` — dispatcher (line 193 + 263)

**Contract:**
- Unknown or missing `action` → `ToolResult(success=False, error="Unknown GitHub action: <action>")`.
- Handler exception → `ToolResult(success=False, error=str(e))`; warning log emitted.
- Success → `ToolResult(content=json.dumps(handler_result), success=True)`.

**Test cases:**

1. `test_execute_unknown_action_returns_error` — `action="nope"` → `.success False`, `.error == "Unknown GitHub action: nope"`.
2. `test_execute_missing_action_key_returns_error` — no `action` key → `.error == "Unknown GitHub action: "`.
3. `test_execute_handler_exception_becomes_error_result` — mock transport raises; `.success False`; `.error` non-empty; warning logged.
4. `test_execute_success_serializes_json` — mock get_issue returns full issue; assert `json.loads(result.content)["number"] == 42` and `.success True`.

---

## `_submit_review` (lines 419-447)

**Contract:** POST `/repos/{o}/{r}/pulls/{n}/reviews`. Validates `event ∈ {APPROVE, REQUEST_CHANGES, COMMENT}` (case-insensitive, normalized via `.upper()`). `REQUEST_CHANGES` requires non-empty `body`. Returns `{id, state, user, submitted_at}` or `{error: ...}` for validation failure. Body is included in POST JSON only when non-empty.

**Test cases:**

1. `test_submit_review_rejects_invalid_event` — `event="LGTM"` → returned dict has `"error"` mentioning "Invalid review event: LGTM".
2. `test_submit_review_rejects_request_changes_without_body` — `event="REQUEST_CHANGES", body=""` → `error == "body is required for REQUEST_CHANGES reviews"`.
3. `test_submit_review_approve_omits_body_when_empty` — `event="APPROVE"`, no body; capture outbound JSON → has `event` but no `body` key; returns dict with `id, state, user, submitted_at` keys.
4. `test_submit_review_comment_with_body` — `event="COMMENT", body="nit"`; outbound JSON == `{"event":"COMMENT","body":"nit"}`.
5. `test_submit_review_normalizes_lowercase_event` — `event="approve"` → POST body sends `"APPROVE"`.
6. `test_submit_review_missing_submitted_at_returns_empty_string` — API response lacks `submitted_at` → returned `submitted_at == ""`.

---

## `_close_pr` (lines 456-468)

**Contract:** PATCH `/repos/{o}/{r}/pulls/{n}` with `{"state":"closed"}`. Returns `{"state":"closed","number": str(n)}`.

**Test cases:**

1. `test_close_pr_sends_patch_with_closed_state` — capture request; assert method=PATCH, URL ends `/pulls/7`, body `{"state":"closed"}`; returns `{"state":"closed","number":"7"}`.
2. `test_close_pr_propagates_404` — transport returns 404 → via `execute()`, `.success is False` and error contains status info.

---

## `_merge_pr` (lines 472-486)

**Contract:** PUT `/repos/{o}/{r}/pulls/{n}/merge` with `{merge_method}`. Default `merge_method="squash"`. Returns `{merged, sha, message}` with defaults if API omits fields.

**Test cases:**

1. `test_merge_pr_default_method_is_squash` — omit `merge_method`; outbound JSON `{"merge_method":"squash"}`.
2. `test_merge_pr_honors_explicit_merge_method` — `merge_method="rebase"` → PUT body carries `rebase`.
3. `test_merge_pr_defaults_when_response_fields_missing` — API returns `{}` → returned dict `== {"merged": False, "sha": "", "message": ""}`.
4. `test_merge_pr_passes_through_sha_and_message` — API returns `{"merged": true, "sha": "abc", "message": "Merged"}` → all three passed through.

---

## `_add_labels` (lines 494-507)

**Contract:** POST `/repos/{o}/{r}/issues/{n}/labels` with `{"labels": [...]}`. Returns **only names** extracted from response `[{name, color, ...}]`.

**Test cases:**

1. `test_add_labels_returns_names_only` — API returns `[{"name":"bug","color":"red"},{"name":"p1"}]` → returns `["bug","p1"]`.
2. `test_add_labels_empty_input` — `labels=[]` (or absent) → POST body `{"labels": []}`; returns `[]`.
3. `test_add_labels_propagates_422_validation_error` — API 422 → `execute()` yields `.success False`.

---

## `_remove_label` (lines 511-525)

**Contract:** DELETE `/repos/{o}/{r}/issues/{n}/labels/{label}`. 404 → `{"status":"not_found","label":<label>}` (no raise). Other non-2xx raises via `raise_for_status()`. 200/204 → `{"status":"removed","label":<label>}`.

**Test cases:**

1. `test_remove_label_success` — 200 response → `{"status":"removed","label":"wip"}`.
2. `test_remove_label_404_is_soft_ok` — 404 response → returns `{"status":"not_found","label":"wip"}`; `execute()` result `.success is True` (no exception).
3. `test_remove_label_500_propagates` — 500 → `.success False`, error mentions HTTP 500.

---

## `_close_issue` (lines 529-541)

**Contract:** PATCH `/repos/{o}/{r}/issues/{n}` with `{"state":"closed"}`. Returns `{"state":"closed","number": str(n)}`.

**Test cases:**

1. `test_close_issue_sends_patch` — PATCH `/issues/5`, body `{"state":"closed"}`, return `{"state":"closed","number":"5"}`.
2. `test_close_issue_propagates_422` — 422 → `.success False`.

---

## Intentionally uncovered

None — every listed missing line is reachable through the public `execute()` dispatcher.

## Contract gaps flagged

- `_add_labels` has no documented behavior for a label name collision (API returns 422). Test asserts error propagates but doesn't assert a specific message.
- The module registers handlers dict-keyed by action name, but `create_issue` is in `_handlers` yet not in the `parameters.action.enum` list — mild inconsistency. Spec doesn't test `create_issue` via the enum (caller would bypass enum validation).

## Estimated tests: **~27 tests** across token helper (6), constructor (5), dispatcher (4), and 6 handlers (12).
