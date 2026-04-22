# Spec: `src/stronghold/tools/workspace.py`

**Purpose:** Manages git clones and per-issue worktrees on disk so Mason can edit, commit, push, and clean up in isolation for each issue.

**Coverage:** 86% (104/121). Missing: 80-81, 105, 138-154, 193-195, 205-212.

## Test strategy

- Use `tmp_path` as `STRONGHOLD_WORKSPACE` to isolate from real filesystem.
- Initialize a bare git repo locally (`git init --bare`) to serve as the "remote" and clone from `file://` URL; avoids touching network.
- Monkeypatch `_run` to a recording fake for error-path tests; use real `_run` for happy-path tests against the temp repo.
- `WorkspaceManager` reads `STRONGHOLD_WORKSPACE` at import time via `DEFAULT_WORKSPACE_ROOT` — set env var before import, or monkeypatch the module constant.

---

## `_resolve_base_dir()` (static, lines 79-89)

**Contract:** Tries `DEFAULT_WORKSPACE_ROOT` first; on `OSError`, falls back to `tempfile.gettempdir()/"stronghold-workspace"`. If neither works, raises `RuntimeError("No writable workspace root available")`.

**Uncovered:**
- **80-81** — the `except OSError` branch for the first candidate (unusable primary → fallback taken).

**Test cases:**

1. `test_resolve_base_uses_configured_root_when_writable`
   - Setup: `monkeypatch.setattr(workspace, "DEFAULT_WORKSPACE_ROOT", tmp_path/"wsroot")`.
   - Action: `WorkspaceManager._resolve_base_dir()`.
   - Expect: returns `tmp_path/"wsroot"`; dir exists.

2. `test_resolve_base_falls_back_to_tempdir_on_oserror`
   - Setup: `monkeypatch.setattr(workspace, "DEFAULT_WORKSPACE_ROOT", Path("/proc/1/definitely-not-writable"))` OR monkeypatch `Path.mkdir` to raise `OSError` on the first path only.
   - Action: call resolver.
   - Expect: returns `Path(tempfile.gettempdir())/"stronghold-workspace"`; warning log `"Workspace root unavailable"`.

3. `test_resolve_base_raises_when_all_candidates_unwritable`
   - Setup: monkeypatch both candidates to raise OSError on mkdir.
   - Action: `_resolve_base_dir()`.
   - Expect: `pytest.raises(RuntimeError, match="No writable workspace root available")`.

---

## `WorkspaceManager.execute(arguments)` — dispatcher (lines 101-114)

**Contract:** Unknown/missing action → `ToolResult(success=False, error="Unknown action: <action>")`. Handler exception → `ToolResult(success=False, error=str(e))`; warning log. Success → `ToolResult(content=json.dumps(result), success=True)`.

**Uncovered branches:**
- **105** — empty/unknown action branch `if not handler`.

**Test cases:**

1. `test_execute_unknown_action_returns_error` — `action="spin"` → `.success False`, `.error == "Unknown action: spin"`.
2. `test_execute_missing_action_returns_error` — no `action` key → `.error == "Unknown action: "`.
3. `test_execute_handler_exception_wraps_as_error_result` — monkeypatch `_create` to raise → `.success False`; warning log emitted.
4. `test_execute_success_serializes_json` — stub `_status` to return `{"status":"active"}` → `json.loads(result.content) == {"status":"active"}`.

---

## `_ensure_clone` (lines 116-134)

**Contract:** Clones `https://[x-access-token:{GITHUB_TOKEN}@]github.com/{owner}/{repo}.git` shallow into `<base>/repos/<repo>` unless already cloned. Caches by `owner/repo` key. Configures commit identity `mason@stronghold.local` / `Mason`. Returns the repo dir path.

**Test cases:**

1. `test_ensure_clone_uses_token_url_when_env_set`
   - Setup: `GITHUB_TOKEN="gh_abc"`; spy on `_run`.
   - Action: `manager._ensure_clone("o","r")`.
   - Expect: first `_run` call args contain `https://x-access-token:gh_abc@github.com/o/r.git`.

2. `test_ensure_clone_no_token_uses_anonymous_url` — `GITHUB_TOKEN` unset → URL `https://github.com/o/r.git`.

3. `test_ensure_clone_caches_by_owner_repo` — call twice; second call does not re-invoke `git clone` (spy records 0 additional calls for second invocation).

4. `test_ensure_clone_picks_up_preexisting_dir_without_clone`
   - Setup: pre-create `<base>/repos/r` directory.
   - Action: `_ensure_clone("o","r")`.
   - Expect: returned path == that dir; no `git clone` invocation.

5. `test_ensure_clone_configures_git_identity` — on real local bare-repo clone, verify `user.email == "mason@stronghold.local"` and `user.name == "Mason"` via `git config --get` in the cloned dir.

---

## `_create` (lines 136-167)

**Contract:** Creates worktree `<base>/worktrees/mason-{issue}` branched from `origin/main`. Default branch name `mason/{issue}`. If worktree dir already exists → returns `{"status":"exists",...}` (no re-add). Fetches origin/main before creating.

**Uncovered branches:**
- **138-154** — the full happy path of branch creation and `git worktree add`, including the "exists" early return (140-144).

**Test cases:**

1. `test_create_new_worktree_returns_created`
   - Setup: local bare repo as origin; `_ensure_clone` seeds it with a main branch.
   - Action: execute `{"action":"create","owner":"o","repo":"r","issue_number":7}`.
   - Expect: response JSON `{"status":"created","path": <worktrees/mason-7>,"branch":"mason/7"}`; worktree dir exists on disk; `git rev-parse --abbrev-ref HEAD` inside worktree == `mason/7`.

2. `test_create_honors_explicit_branch_name`
   - Action: pass `branch="feature/xyz"`.
   - Expect: `response.branch == "feature/xyz"`; HEAD inside worktree == that branch.

3. `test_create_existing_worktree_returns_exists_without_reinit`
   - Setup: create worktree once; spy on `_run`.
   - Action: second `create` with same `issue_number`.
   - Expect: JSON `{"status":"exists",...}`; no `git worktree add` invocation on second call.

4. `test_create_fetches_origin_main_first`
   - Setup: spy on `_run`.
   - Action: `create` on fresh repo.
   - Expect: call sequence includes `["git","fetch","origin","main"]` before the `worktree add`.

---

## `_status` (lines 169-180)

**Contract:** If worktree missing → `{"status":"not_found"}`. Else returns `{status:"active", path, branch, changes:[]}`. `changes` is split porcelain output (lines) or empty list when clean.

**Test cases:**

1. `test_status_returns_not_found_when_no_worktree` — call for `issue_number=999` → `{"status":"not_found"}`.
2. `test_status_clean_worktree_has_empty_changes` — freshly created → `changes == []`.
3. `test_status_lists_modified_files` — write a file inside worktree → `status` call returns `changes` list containing the porcelain line `"?? somefile.txt"` (or similar).

---

## `_commit` (lines 182-192)

**Contract:** Missing worktree → `{"status":"error","error":"worktree not found"}`. Else `git add -A` + `git commit --allow-empty -m <msg>` + `git rev-parse HEAD`, returns `{"status":"committed","sha":<40hex>}`. Default message `"mason: work on issue #<n>"`.

**Test cases:**

1. `test_commit_missing_worktree_returns_error` → `{"status":"error","error":"worktree not found"}`.
2. `test_commit_with_no_changes_allows_empty` — call on clean worktree → returns `status=committed`, SHA differs from the base commit SHA.
3. `test_commit_honors_custom_message` — pass `message="custom msg"`; `git log -1 --format=%s` == `"custom msg"`.
4. `test_commit_default_message_contains_issue_number` — omit `message` for `issue_number=42` → `git log -1 --format=%s` contains `"#42"`.
5. `test_commit_returns_40_char_sha` — returned `sha` length 40, hex chars only.

---

## `_push` (lines 193-201) — uncovered 193-195

**Contract:** Missing worktree → `{"status":"error","error":"worktree not found"}`. Else resolves current branch, runs `git push -u origin <branch>`, returns `{"status":"pushed","branch":<name>}`.

**Test cases:**

1. `test_push_missing_worktree_returns_error` — call with an issue_number that has no worktree → `{"status":"error","error":"worktree not found"}`.
2. `test_push_invokes_upstream_tracking` — spy on `_run`; assert call `["git","push","-u","origin","mason/7"]`.
3. `test_push_returns_current_branch`
   - Setup: create worktree on branch `mason/5`.
   - Action: push.
   - Expect: response `{"status":"pushed","branch":"mason/5"}`.
4. `test_push_failure_propagates_as_error_result`
   - Setup: bare repo on non-writable location, or mock `_run` to raise on push.
   - Expect: `execute()` → `.success False`, error contains push failure.

---

## `_cleanup` (lines 203-216) — uncovered 205-212

**Contract:** Missing worktree → `{"status":"not_found"}`. Else attempts `git worktree remove --force` in each cached repo; on failure (Exception) tries next repo; as last resort `shutil.rmtree`. Returns `{"status":"cleaned"}`.

**Test cases:**

1. `test_cleanup_missing_worktree_returns_not_found` — no worktree yet → `{"status":"not_found"}`.
2. `test_cleanup_removes_existing_worktree`
   - Setup: create worktree first.
   - Action: cleanup.
   - Expect: response `{"status":"cleaned"}`; directory no longer exists.
3. `test_cleanup_fallback_rmtree_when_git_worktree_fails`
   - Setup: create worktree dir, clear `_repos` cache (no repos known); only directory on disk.
   - Action: cleanup.
   - Expect: returns `cleaned`; directory deleted via `shutil.rmtree` fallback.
4. `test_cleanup_tries_each_cached_repo_until_one_succeeds`
   - Setup: populate `_repos` with two keys, first repo_dir is invalid path (raises), second is the real parent repo.
   - Action: cleanup.
   - Expect: the `break` taken after second repo succeeds; directory gone.

---

## `_run` (static helper)

**Contract:** `subprocess.run(..., capture_output=True, text=True, timeout=120)`. Non-zero exit → `RuntimeError(f"{' '.join(cmd[:3])}: {stderr|stdout}")`. Zero exit → returns stdout string.

**Test cases:**

1. `test_run_returns_stdout_on_success` — `_run(["echo","hi"])` returns `"hi\n"`.
2. `test_run_raises_runtime_error_on_nonzero` — `_run(["false"])` → `RuntimeError` whose message starts with `"false: "`.
3. `test_run_raises_when_stderr_present` — `_run(["sh","-c","echo boom 1>&2; exit 3"])` → error contains `"boom"`.

---

## Intentionally uncovered

None. All listed lines are reachable via public actions.

## Contract gaps

- `_cleanup` swallows all `Exception`s in the per-repo loop; if every repo errors and the dir also can't be `rmtree`'d, the method still returns `{"status":"cleaned"}` despite the dir still existing. Spec doesn't add a test for this gap; flag for future contract tightening.
- `_ensure_clone` has no lock — two concurrent `create` calls for different issues on the same repo could race. Out of scope for unit tests.

## Estimated tests: **~28 tests** across resolver (3), dispatcher (4), clone (5), create (4), status (3), commit (5), push (4), cleanup (4), _run (3) — minus overlap ≈ 28.
