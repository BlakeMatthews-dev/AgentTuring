# SEC-H6: Route every tool-result scan through Sentinel

## User Story

As a **security auditor**, I want every tool-result scan to flow through
the Sentinel post-call path, so that PII redaction and structured audit
logging are never silently skipped when Sentinel is unconfigured.

## Background

`src/stronghold/agents/strategies/react.py` falls back to a direct Warden
scan when `sentinel is None`, missing PII redaction and audit logging.
Direct Warden calls also exist in `triggers.py` and `skills.py`. The
Warden fallback is weaker than the Sentinel path by design, but it is
reachable in default deployments where Sentinel has not been wired.

## Acceptance Criteria

- AC1: Given `sentinel is None`, When `ReactStrategy` processes a tool result, Then it instantiates a `NoopSentinel` that internally calls Warden + PII redactor, not a bespoke fallback.
- AC2: Given `NoopSentinel.post_call` runs, When called, Then it emits the same audit-log event shape as the real Sentinel (with `sentinel_backend="noop"`).
- AC3: Given a grep of `src/stronghold/`, When searching for direct `Warden.scan(...,  "tool_result")` calls outside `security/`, Then results are empty (enforced by a ruff custom rule or a test that greps the source tree).
- AC4: Given an existing caller in `triggers.py` / `skills.py`, When migrated, Then behavior is unchanged on the happy path (no regressions in their test suites).

## Test Mapping

| AC  | Test path                                       | Test function                               | Tier     |
|-----|-------------------------------------------------|---------------------------------------------|----------|
| AC1 | tests/agents/test_react_strategy.py             | test_noop_sentinel_used_when_none           | critical |
| AC2 | tests/security/test_noop_sentinel.py            | test_noop_sentinel_audit_shape              | critical |
| AC3 | tests/security/test_no_direct_warden_calls.py   | test_no_direct_warden_tool_result_calls     | critical |
| AC4 | tests/triggers/test_triggers.py                 | test_trigger_scan_unchanged_after_migration | happy    |

## Files to Touch

- New: `src/stronghold/security/sentinel/noop.py` — `NoopSentinel` wrapping Warden + redactor.
- Modify: `src/stronghold/agents/strategies/react.py` — replace the fallback block with `sentinel or NoopSentinel(warden, redactor)`.
- Modify: `src/stronghold/triggers.py`, `src/stronghold/skills.py` — route via sentinel.
- Modify: `src/stronghold/container.py` — default `sentinel` to `NoopSentinel(...)` if none configured.
- New: `tests/security/test_no_direct_warden_calls.py` — source-tree grep assertion.

## Rollback

Per-caller commits; if the noop introduces a regression, revert per-file.
