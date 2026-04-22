# Stronghold Test Quality — Final Audit & Plan

**Cataloged:** 3,775 tests across 278 files  
**Baseline coverage:** 94% (12,466 stmts, 787 uncovered)  
**Running suite:** 3,833 pass / 2 skip / 6 xfail (on main)

## Top-line

| | Count | % |
|---|---|---|
| GOOD | 3,444 | 91.2% |
| WEAK | 299 | 7.9% |
| BAD | 32 | 0.85% |
| **Problem total** | **331** | **8.8%** |

The 34% BAD from the initial 200-sample audit overshot. Real rate is **~9%** — still worth fixing, but the suite is mostly honest.

## By severity (problem tests only)

- **high** (security/auth/isolation): 163
- **med** (business logic): 317 ← wait, this is the GOOD+problem split, not problem-only
- **low** (utilities): 301

## By issue type

| Issue | Count | Meaning |
|---|---|---|
| trivial-type | 118 | `isinstance/hasattr` right after assignment |
| status-only | 65 | `resp.status_code == 200` with no body check |
| over-mock | 54 | Mock determines outcome; SUT barely exercised |
| no-assert | 34 | Calls function, no assert (smoke dressed as test) |
| tautology | 32 | Setup equals outcome / test computes its own expected |
| skip-marker | 13 | Skipped tests worth auditing for rot |
| flaky-ext | 12 | Depends on external service reachability |
| dead-code | 6 | Test is `xfail(strict=False)` or checks unreachable |
| call-count | 4 | Remaining mock-call-count asserts |
| duplicate | 1 | |

## By fix action

- `keep`: 3,603
- `rewrite`: 104
- `mark-skip-if-no-ext`: 29
- `delete`: 26
- `parametrize`: 7
- `unskip`: 6

## Top 10 problem files

| File | Bad+Weak | Primary issue | Fix |
|---|---|---|---|
| `tests/test_types.py` | 30 | trivial-type (dataclass round-trips) | rewrite or mark as smoke |
| `tests/security/test_security_audit_2026_03_30.py` | 20 | inspect.getsource substring | rewrite to behavior |
| `tests/mcp/test_registries_coverage.py` | 18 | over-mock httpx | use real transport/respx |
| `tests/api/test_admin_routes.py` | 18 | status-only | assert response body |
| `tests/tracing/test_phoenix_backend.py` | 14 | no-assert smoke (8 deletable) | delete 8, rewrite 6 |
| `tests/agents/test_tool_http_extended.py` | 13 | mock reimplements prod code | rewrite against real executor |
| `tests/security/test_security_audit_round3.py` | 12 | inspect.getsource + locally-duped regex | rewrite to behavior |
| `tests/conduit/test_execution_tier.py` | 9 | implementation-mirroring expectations | rewrite |
| `tests/security/test_audit_regression.py` | 8 | inspect.getsource string match | rewrite |
| `tests/security/test_security_hardening.py` | 8 | status-only on limit clamps | assert the clamp value |

## Delete list (26 tests in 10 files)

- `tests/api/test_issue_440.py` (4 tests) — runs `ruff check` via subprocess
- `tests/api/test_issue_438.py` (3 tests) — ditto, lint-as-test
- `tests/api/test_issue_451.py` (1 test) — hardcoded src line numbers
- `tests/tracing/test_phoenix_backend.py` (8 tests) — pure no-assert smoke
- `tests/types/test_prompt_types.py` (3 tests) — setup=outcome tautologies
- `tests/api/test_middleware.py` (2 tests) — tests a stub has no classes
- `tests/conduit/test_execution_tier.py` (2 tests) — constant-equals-constant
- `tests/protocols/test_all_protocols.py` (1 test)
- `tests/mcp/test_deployer_client.py` (1 test) — duplicate
- `tests/builders/evidence/test_learning_target_attribution.py` (1 test) — tautology

## Skip-if-no-external list (29 tests)

Mostly `tests/e2e/test_full_stack.py` (already done by Wave 2D retry — 14 now cleanly skip), plus a few in `tests/integration/test_tracing.py` and `tests/tools/test_executor.py` that hit external hosts.

## Unskip list (6 tests)

`xfail(strict=False)` tests that rot silently — each needs the underlying code fixed or the test deleted:
- `tests/api/test_agents_routes.py::test_*_injection_xfail` (2)
- `tests/integration/test_structured_request.py::*_xfail` (2)
- `tests/integration/test_full_pipeline_e2e.py::test_code_request_routes_to_artificer`
- `tests/integration/test_coverage_api.py` container-lifespan xfails (2)

## Plan — 5 waves

**Wave A (high-severity first, ~30 tests):** Rewrite the 163 high-severity problem tests in security files. Start with the inspect.getsource cluster (audit_2026_03_30, round3, audit_regression) — 40 tests total. These currently claim to guard auth/isolation invariants but only substring-match source text. Rewrite to behavioral asserts against real `Warden`, `Gate`, `StrikeTracker`.

**Wave B (over-mock cluster, ~50 tests):** `test_registries_coverage.py`, `test_engine.py`, `test_pool.py`, `test_tool_http_extended.py`. Replace `patch("httpx.AsyncClient")` / `MagicMock(AsyncSession)` with real `respx.mock` transports or real asyncpg fixtures.

**Wave C (status-only in API routes, ~65 tests):** `test_admin_routes.py`, `test_dashboard_routes.py`, `test_security_hardening.py`. Add response-body asserts or remove the test where behavior is already covered elsewhere.

**Wave D (smoke/tautology cleanup, ~52 tests):** Delete the 26 deletion candidates; rewrite the 32 tautologies; collapse 7 parametrize candidates.

**Wave E (trivial-type bulk, ~118 tests):** `test_types.py` (30), `test_container_coverage.py` (8), `test_new_modules.py` (7), `test_tool_definitions.py` (7), and tail. Most are low-severity dataclass round-trips — judgment call whether to rewrite to meaningful behavior or re-label as smoke tests and leave them. Recommend: rewrite the ones backing public API contracts, delete the rest.

**After all waves:** re-run full coverage, expect ~95-95.5% raw with +164 tests from the spec pass on the 7 low-coverage modules (`tools/github.py`, `tools/executor.py`, `tools/workspace.py`, `triggers.py`, `skills/forge.py`, `skills/loader.py`, `skills/marketplace.py`).

## Effort estimate

- Wave A: ~4 hours (deep security invariant thinking)
- Wave B: ~3 hours (mostly mechanical: swap mock for respx/fake)
- Wave C: ~3 hours (read routes, assert response bodies)
- Wave D: ~1 hour (deletes + rewrites are small)
- Wave E: ~2 hours (bulk, low-value-per-test)
- Spec-driven new tests (164): ~6 hours

Total: ~19 hours of focused work, or 5-6 parallel agent waves of ~2-4 hours wall time.

## What we already did (context for this plan)

Before this audit, we ran:
- Wave 1 (coverage files, 976 tests): rewrote ~55, deleted ~22
- Wave 2A-D (non-coverage bad-pattern files, ~370 tests): rewrote ~60, deleted ~30, marked ~14 skip-if-no-ext
- Security gate DI test fixed (was passing when Warden was ignored)
- e2e test_full_stack.py: 13 failing → 0 failing (env-gated skips)

The 8.8% problem rate above is the state AFTER those waves. More cleanup is still worthwhile but the suite is no longer in crisis.
