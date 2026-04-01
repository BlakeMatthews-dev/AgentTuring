# Mason Rules

## MUST-ALWAYS

- Read stored learnings before starting any work session
- Write tests BEFORE implementation (TDD)
- Update ARCHITECTURE.md when adding new modules
- Add protocols to `src/stronghold/protocols/` for new interfaces
- Add fakes to `tests/fakes.py` for new protocols
- Use real classes in tests, never `unittest.mock` for internal code
- Run ALL quality gates before PR submission
- Create one PR per issue with focused scope
- Reference the issue number in PR title and description

## MUST-NEVER

- Modify ARCHITECTURE.md design decisions (only add new sections)
- Skip quality gates for any reason
- Use `unittest.mock`, `MagicMock`, `AsyncMock`, or `patch` for internal classes
- Hardcode secrets, API keys, or credentials
- Import concrete implementations in business logic (use protocols)
- Bundle unrelated changes in one PR
- Create PRs without corresponding tests
- Ignore or dismiss review feedback from Auditor
- Access private fields (`_field`) on classes you don't own
- Use `Any` in business logic type annotations
