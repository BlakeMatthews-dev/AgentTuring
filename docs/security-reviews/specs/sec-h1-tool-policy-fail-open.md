# SEC-H1: Tool-policy load failure must be fatal

## User Story

As a **security auditor**, I want a missing or broken Casbin policy file
to abort startup, so that tool-call authorization cannot be silently
disabled.

## Background

`src/stronghold/container.py:323–329` catches any exception from
`create_tool_policy()` and sets `tool_policy = None`. The dispatch gate at
line 407 (`if tool_policy is not None and auth is not None:`) is then
skipped, and every tool call proceeds unauthorized. The failure is visible
only as a single `WARNING` log line.

## Acceptance Criteria

- AC1: Given the policy model or CSV file is missing, When the container builds, Then startup raises `ConfigError("tool policy load failed")` unless `STRONGHOLD_DISABLE_TOOL_POLICY=1`.
- AC2: Given `STRONGHOLD_DISABLE_TOOL_POLICY=1` is set, When the container builds, Then startup logs `CRITICAL: tool policy disabled via override` and continues.
- AC3: Given an empty but syntactically valid policy CSV, When a tool call is dispatched, Then the call is denied (default-deny), not allowed.
- AC4: Given a readiness probe call, When `tool_policy` is `None` and the override is not set, Then the `/readyz` endpoint returns 503.
- AC5: Given a test suite, When integration tests run with the override set, Then they must pass without the override so CI catches accidental disabling.

## Test Mapping

| AC  | Test path                                         | Test function                                | Tier     |
|-----|---------------------------------------------------|----------------------------------------------|----------|
| AC1 | tests/security/test_tool_policy_wiring.py         | test_missing_policy_file_aborts_startup      | critical |
| AC2 | tests/security/test_tool_policy_wiring.py         | test_override_allows_startup_with_critical   | critical |
| AC3 | tests/security/test_tool_policy.py                | test_empty_policy_denies_tool_call           | critical |
| AC4 | tests/api/test_health.py                          | test_readyz_503_when_policy_missing          | critical |
| AC5 | tests/security/test_tool_policy_wiring.py         | test_ci_does_not_set_override                | happy    |

## Files to Touch

- Modify: `src/stronghold/container.py` — replace `tool_policy = None` fallback with a `ConfigError` unless override env is set; log CRITICAL on override.
- Modify: `src/stronghold/security/tool_policy.py` — confirm Casbin model is `!some(where (p.eft == allow))` or equivalent default-deny; document the model file.
- Modify: `src/stronghold/api/routes/status.py` (or wherever `/readyz` lives) — assert `container.tool_policy is not None or override_set`.
- New: `tests/security/test_tool_policy_wiring.py`.

## Rollback

Revert the container.py change. The override flag exists so operators can
re-enable the old fail-open behavior in emergencies without a code change.
