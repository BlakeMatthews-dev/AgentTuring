# Issue 4: Mason Should Self-Diagnose Before PR Submission

**Title:** Mason should run self-diagnosis before submitting PR

**Description:**
Mason should not submit PRs that will be rejected. Before creating the PR,
Mason should run diagnostic checks:
1. Coverage >= 85% (first pass) or >= 95% (final)
2. Type checks pass (mypy --strict)
3. Lint checks pass (ruff)
4. Security checks pass (bandit)
5. Docstrings exist on all functions
6. Error handling present (try/except)
7. Naming conventions followed
8. Architecture violations none

If any check fails, Mason should:
- Fix the issue
- Re-run diagnostics
- Only submit when all pass

This reduces PR rejection cycles and speeds up delivery.

**Current Status:**
- ✅ `_run_pr_diagnostics()` method exists (simulated)
- ✅ All 8 diagnostic checks documented
- ✅ Self-diagnosis concept documented in SOUL.md
- ⚠️ All diagnostic checks are simulated (return hardcoded results)
- ⚠️ Real pytest coverage check not implemented
- ⚠️ Real mypy check not implemented
- ⚠️ Real ruff check not implemented
- ⚠️ Real bandit check not implemented
- ⚠️ Docstring check not implemented
- ⚠️ Error handling check not implemented
- ⚠️ Naming convention check not implemented
- ⚠️ Architecture violation check not implemented

**Implementation Tasks:**

1. **Coverage Check:**
   - [ ] Run `pytest --cov=stronghold --cov-report=term-missing`
   - [ ] Parse coverage output for percentage
   - [ ] Check against threshold (85% or 95%)
   - [ ] Return result with specific files needing coverage

2. **Type Check:**
   - [ ] Run `mypy src/stronghold/ --strict`
   - [ ] Parse output for errors
   - [ ] Return list of type errors

3. **Lint Check:**
   - [ ] Run `ruff check src/stronghold/`
   - [ ] Parse output for errors
   - [ ] Return list of lint errors

4. **Security Check:**
   - [ ] Run `bandit -r src/stronghold/ -ll`
   - [ ] Parse output for issues
   - [ ] Return list of security issues

5. **Docstring Check:**
   - [ ] Use AST to find all public functions
   - [ ] Check each function has a docstring
   - [ ] Return list of missing docstrings

6. **Error Handling Check:**
   - [ ] Use AST to find external API calls
   - [ ] Check each call is wrapped in try/except
   - [ ] Return list of missing error handling

7. **Naming Convention Check:**
   - [ ] Use ruff's naming rules
   - [ ] Check function/class/variable names
   - [ ] Return list of naming violations

8. **Architecture Violation Check:**
   - [ ] Check for DI violations (importing concrete classes)
   - [ ] Check for bundled concerns (module complexity)
   - [ ] Return list of architecture violations

9. **Fix Loop:**
   - [ ] If any check fails, run auto-fix where possible
   - [ ] Re-run diagnostics
   - [ ] Only submit PR when all pass

**Acceptance Criteria:**
- [ ] Mason runs diagnostic suite before PR creation
- [ ] Diagnostic checks include: coverage, type, lint, security, docs, error handling, naming, architecture
- [ ] Mason only submits PR when all diagnostics pass
- [ ] If diagnostics fail, Mason fixes issues and re-runs
- [ ] Diagnostic results stored in memory for learning
- [ ] All tests pass

**Priority:** High
**Component:** Mason strategy
**Estimated Effort:** 10 hours
