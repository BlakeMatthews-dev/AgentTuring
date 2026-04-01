# Mason Rules

## PHASE DISCIPLINE

- MUST-ALWAYS complete all 8 phases in order for every issue
- MUST-ALWAYS pass the exit gate before advancing to the next phase
- MUST-NEVER write implementation code before Phase 7
- MUST-NEVER skip the test review loop (Phase 6)
- MUST-NEVER move from Phase 2 to Phase 7 (skipping 3-6)

## ACCEPTANCE CRITERIA (Phase 1)

- MUST-ALWAYS derive criteria from the issue AND ARCHITECTURE.md
- MUST-ALWAYS include criteria for: happy path, error cases, multi-tenant, security
- MUST-ALWAYS verify each criterion is falsifiable (can be tested)
- MUST-NEVER accept vague criteria ("it should work well")

## TEST VALIDATION (Phases 2-6)

- MUST-ALWAYS ask "can a bad implementation pass this test?" for every test
- MUST-ALWAYS tighten tests that can be passed with bad code
- MUST-ALWAYS write tests using real classes from `src/stronghold/`
- MUST-ALWAYS use fakes from `tests/fakes.py` for protocol dependencies
- MUST-NEVER use `unittest.mock`, `MagicMock`, `AsyncMock`, or `patch`
- MUST-NEVER write tests that only assert "no crash" (assert values)
- MUST-NEVER couple tests to implementation details (test behavior)

## IMPLEMENTATION (Phase 7)

- MUST-ALWAYS write minimum code to pass all tests
- MUST-ALWAYS add protocols to `src/stronghold/protocols/` for new interfaces
- MUST-ALWAYS add fakes to `tests/fakes.py` for new protocols
- MUST-ALWAYS update ARCHITECTURE.md for new modules
- MUST-ALWAYS run ALL quality gates before considering Phase 7 complete

## POST-REVIEW (Phase 8)

- MUST-ALWAYS re-read the original issue before creating the PR
- MUST-ALWAYS verify no unrelated changes were smuggled in
- MUST-ALWAYS create one PR per issue with focused scope
- MUST-NEVER ignore review feedback from Auditor

## GENERAL

- MUST-ALWAYS read stored learnings before starting any work session
- MUST-NEVER hardcode secrets, API keys, or credentials
- MUST-NEVER import concrete implementations in business logic (use protocols)
- MUST-NEVER access private fields (`_field`) on classes you don't own
- MUST-NEVER use `Any` in business logic type annotations
- MUST-NEVER add `Co-Authored-By` trailers to commits
