# Issue 1: Implement Builders Learning Strategy

**Title:** Implement `builders_learning` strategy for Frank/Mason

**Description:**
Frank and Mason need to learn from failures and get smarter over time. Currently using
`strategy: react` which provides tool-use loops but lacks:
- Repository reconnaissance (check existing code/tests)
- Failure pattern analysis (analyze rejected PRs)
- Learning loop (store findings for next time)
- Coverage-first execution (85% first pass, 95% final)
- Self-diagnosis (check PR will be rejected before submitting)

**Current Status:**
- ✅ Basic `BuildersLearningStrategy` class created
- ✅ Registered in factory
- ✅ Basic tests written
- ⚠️ GitHub service integration needed (repo recon, failure analysis)
- ⚠️ Memory store integration needed (learning storage)
- ⚠️ Diagnostic artifact storage needed (orchestrator integration)

**Implementation Tasks:**

1. **GitHub Service Integration:**
   - [ ] Implement `_check_repository_state()` to call `GitHubService`
   - [ ] Implement `_analyze_failure_patterns()` to search similar issues
   - [ ] Implement PR rejection analysis (extract reasons from comments)

2. **Memory Store Integration:**
   - [ ] Implement `_store_frank_learning()` to store in `MemoryStore`
   - [ ] Implement `_store_mason_learning()` to store in `MemoryStore`
   - [ ] Add learning retrieval in subsequent runs

3. **Orchestrator Integration:**
   - [ ] Store diagnostic artifacts in `BuildersOrchestrator`
   - [ ] Read diagnostic artifacts in subsequent worker stages
   - [ ] Pass diagnostic context through `RunRequest`

4. **Enhanced Tests:**
   - [ ] Integration tests with real `GitHubService`
   - [ ] Integration tests with real `MemoryStore`
   - [ ] End-to-end tests with `BuildersOrchestrator`

**Acceptance Criteria:**
- [ ] Frank checks existing code before planning
- [ ] Frank analyzes failure patterns from similar issues
- [ ] Frank provides diagnostic artifact
- [ ] Mason uses diagnostic to determine execution mode
- [ ] Mason runs 85% coverage threshold on first pass
- [ ] Mason self-diagnoses PR before submitting
- [ ] All diagnostic checks implemented (coverage, type, lint, security, docs, error handling, naming, architecture)
- [ ] Both agents store learning in memory
- [ ] Learning retrieval works in subsequent runs
- [ ] Full test coverage for learning features

**Priority:** High
**Component:** Builders 2.0
**Estimated Effort:** 8 hours
