# Issue 2: Add Coverage-First Execution for Mason

**Title:** Mason should execute coverage-first (85% on first pass)

**Description:**
Mason currently tries to achieve 95% coverage on first implementation. This is too aggressive
and causes unnecessary work and delays.

Instead, Mason should:
1. First pass: Target 85% coverage (happy path + basic error handling)
2. Second pass: Add edge cases (boundary conditions, adversarial inputs)
3. Third pass: Style tests (naming, docstrings, type safety)
4. Final pass: Achieve 95% with comprehensive coverage

This speeds up first-time implementations and reduces iteration cycles.

**Current Status:**
- ✅ Coverage-first policy documented in Mason's SOUL.md
- ✅ Diagnostic checks include coverage threshold
- ⚠️ Coverage check implementation is simulated (not real pytest)
- ⚠️ Need actual pytest integration
- ⚠️ Need coverage threshold enforcement
- ⚠️ Need configurable thresholds via agent.yaml

**Implementation Tasks:**

1. **Pytest Integration:**
   - [ ] Implement `_run_coverage_tests()` to run pytest with coverage
   - [ ] Parse coverage report and extract percentage
   - [ ] Return coverage result to strategy

2. **Threshold Enforcement:**
   - [ ] Add `coverage_threshold_first_pass` config to agent.yaml
   - [ ] Add `coverage_threshold_final` config to agent.yaml
   - [ ] Enforce thresholds in Mason workflow
   - [ ] If coverage < threshold, add edge case tests automatically

3. **Edge Case Test Generation:**
   - [ ] Implement `_add_edge_case_tests()` to generate additional tests
   - [ ] Use LLM to generate tests for gaps
   - [ ] Run tests again to verify coverage improvement

4. **Configuration:**
   - [ ] Update `agents/mason/agent.yaml` with coverage thresholds
   - [ ] Document coverage-first policy in SOUL.md
   - [ ] Add examples of coverage-first workflow

**Acceptance Criteria:**
- [ ] Mason uses 85% threshold on first implementation
- [ ] Mason can detect if code already exists (fix mode) vs new (implement mode)
- [ ] Mason adds edge case tests if coverage < 85%
- [ ] Mason runs quality gates only after coverage passes
- [ ] PR submission checks self-diagnosis before submitting
- [ ] Coverage threshold configurable via agent.yaml
- [ ] All tests pass

**Priority:** High
**Component:** Mason strategy
**Estimated Effort:** 6 hours
