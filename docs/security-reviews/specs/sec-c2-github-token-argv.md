# SEC-C2: `GITHUB_TOKEN` leaked through subprocess argv

## User Story

As a **platform operator**, I want the GitHub token kept out of process
argv, so that `/proc/<pid>/cmdline`, `ps`, and container log exporters
cannot capture it.

## Background

`src/stronghold/tools/workspace.py:112–119` embeds the token directly in
the clone URL:

```python
url = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
self._run(["git", "clone", "--depth=1", url, str(repo_dir)])
```

`subprocess.run` places the full URL in argv, visible to anything with
`ptrace_scope=0` or that reads `/proc`. Also, `owner` / `repo` are
unvalidated — an attacker-chosen `owner/repo` clones anywhere on github.

## Acceptance Criteria

- AC1: Given a `GITHUB_TOKEN`, When `_ensure_clone` runs, Then argv to `git clone` does not contain the token (use `GIT_ASKPASS` or `git -c credential.helper=…` via stdin).
- AC2: Given a clone operation, When `ps -o args` is observed during execution, Then the URL shown is `https://github.com/<owner>/<repo>.git` (no credential).
- AC3: Given `owner` not in the configured allowlist, When `_ensure_clone` runs, Then it raises `ValueError("owner not in allowlist")` before subprocess invocation.
- AC4: Given `GITHUB_OWNERS_ALLOWLIST` is unset, When `_ensure_clone` runs, Then it defaults to a single-element list derived from `config.github.owner` (fail-closed on absence).
- AC5: Given the credential helper script, When invoked, Then it reads the token from an env var passed only to the git subprocess (not the parent env).

## Test Mapping

| AC  | Test path                                 | Test function                              | Tier     |
|-----|-------------------------------------------|--------------------------------------------|----------|
| AC1 | tests/tools/test_workspace.py             | test_clone_argv_has_no_token               | critical |
| AC2 | tests/tools/test_workspace.py             | test_clone_uses_askpass_env                | critical |
| AC3 | tests/tools/test_workspace.py             | test_owner_not_in_allowlist_raises         | critical |
| AC4 | tests/tools/test_workspace.py             | test_empty_allowlist_is_fail_closed        | critical |
| AC5 | tests/tools/test_workspace.py             | test_askpass_env_isolated_from_parent      | happy    |

## Files to Touch

- Modify: `src/stronghold/tools/workspace.py` — replace URL-embedded token with `GIT_ASKPASS` helper; add owner/repo allowlist check.
- New: `scripts/git-askpass-stronghold.sh` — reads token from `STRONGHOLD_GH_TOKEN` env only.
- Modify: `src/stronghold/types/config.py` — add `github.owners_allowlist: list[str]`.
- New: `tests/tools/test_workspace.py` — ACs above, using a fake `_run` that captures argv+env.

## Rollback

Single-commit revert. `git-askpass` is widely supported; no external deps.
