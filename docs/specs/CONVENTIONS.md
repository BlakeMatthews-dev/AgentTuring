# Spec Conventions

Rules for authoring stories, acceptance criteria, tests, and rollout plans.

## User Story Template

```markdown
# Story N.M: <short verb-led title>

## User Story
As a <role>, I want <capability>, so that <outcome>.

## Background / Motivation
<2-4 sentences. Cite evidence tags from EVIDENCE-INDEX.md.>

## Acceptance Criteria
- AC1: Given <precondition>, When <action>, Then <observable outcome>.
- AC2: ...

## Test Mapping (TDD Stubs)
| AC  | Test path                          | Test function                      | Tier     |
|-----|------------------------------------|------------------------------------|----------|
| AC1 | tests/<domain>/test_<module>.py    | test_<what_it_verifies>            | critical |
| AC2 | tests/<domain>/test_<module>.py    | test_<what_it_verifies>            | happy    |

## Files to Touch
- New: src/stronghold/<path>
- Modify: src/stronghold/<path> (one-line reason)

## Evidence References
- [EV-TAG-##] — one sentence on what was borrowed

## Open Questions
- OQ-<EPIC>-##: <question> → OPEN-QUESTIONS.md
```

## Roles

| Role | Perspective |
|------|-------------|
| Platform operator | Deploys, configures, monitors Stronghold |
| Tenant admin | Manages agents, permissions, budgets for their org |
| Agent author | Creates or imports agents (light or heavy) |
| End user | Sends requests through the API |
| Security auditor | Reviews trust boundaries, permission enforcement, audit trails |

## Test Path Rules

- One AC = one row in the test-mapping table = one test function
- Tier must be one of: `critical`, `happy`, `perf`, `e2e`
- Test files live under existing `tests/` structure; new directories per plan
- Every test-manifest.md in an epic folder aggregates all test paths for that epic
- Test function names start with `test_` and describe the verified behavior
- Tests use fakes from `tests/fakes.py`; extend fakes as needed per epic

## Feature Flag Naming

`STRONGHOLD_<EPIC_SLUG>_ENABLED` (e.g., `STRONGHOLD_EVAL_SUBSTRATE_ENABLED`).
Default: `False`. Operator activates explicitly.

## Epic README Mandatory Sections

Every `epic-XX/README.md` must contain:
1. Epic summary (1 paragraph)
2. Why now — which dependencies opened the door
3. Depends on — epic numbers
4. Blocks — which later epics wait on this
5. Ship gate — single behavioral signal that says "done"
6. Roles affected
7. Evidence references
8. Files touched (new + modified with one-line reason)
9. Incremental rollout plan (feature flag, canary cohort, rollback plan)
10. Open questions (local list, also in OPEN-QUESTIONS.md)

## Release-Train Rule

No two behavioral-change epics ship in the same release. See SEQUENCING.md.

## Evidence Citations

Use short-codes from EVIDENCE-INDEX.md: `[EV-<SOURCE>-<##>]`. Every AC that
embeds an external pattern cites at least one tag.
