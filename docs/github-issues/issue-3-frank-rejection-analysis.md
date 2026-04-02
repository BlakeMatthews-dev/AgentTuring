# Issue 3: Frank Should Analyze Rejection Patterns

**Title:** Frank should analyze why previous PRs were rejected

**Description:**
When Frank decomposes an issue, it should check:
1. Have similar issues been submitted before?
2. Were those PRs rejected?
3. What were the rejection reasons?
   - Missing error handling?
   - Incomplete test coverage?
   - Type errors?
   - Lint errors?
   - Security issues?
   - Missing docstrings?
   - Naming violations?
   - Architecture violations?
4. What lessons were learned?

Frank should provide this diagnostic artifact to Mason so Mason can:
- Avoid repeating mistakes
- Use correct execution mode (fix vs implement)
- Know what quality gates to focus on

**Current Status:**
- ✅ `_analyze_failure_patterns()` method exists (simulated)
- ✅ Failure pattern concept documented in SOUL.md
- ⚠️ GitHub search not implemented (returns empty list)
- ⚠️ PR rejection analysis not implemented
- ⚠️ Pattern extraction from comments not implemented
- ⚠️ Recurrence detection not implemented

**Implementation Tasks:**

1. **GitHub Search Integration:**
   - [ ] Search GitHub for similar issues by title/keywords
   - [ ] Limit search results (top 5 similar issues)
   - [ ] Cache results to avoid redundant searches

2. **PR Rejection Analysis:**
   - [ ] List all PRs for similar issues
   - [ ] Filter for rejected/closed PRs
   - [ ] Extract review comments from rejected PRs
   - [ ] Parse comments for rejection reasons

3. **Pattern Extraction:**
   - [ ] Categorize rejection reasons (predefined categories)
   - [ ] Detect common patterns across rejections
   - [ ] Extract specific code that caused failures
   - [ ] Extract fixes that resolved issues

4. **Recurrence Detection:**
   - [ ] Track how many times each pattern occurs
   - [ ] Prioritize recurring patterns
   - [ ] Flag recurring patterns in diagnostic

5. **Diagnostic Artifact:**
   - [ ] Build structured diagnostic with all findings
   - [ ] Store diagnostic in orchestrator
   - [ ] Make diagnostic available to Mason

**Acceptance Criteria:**
- [ ] Frank searches GitHub for similar issues
- [ ] Frank lists all PRs for similar issues
- [ ] Frank analyzes rejection comments for patterns
- [ ] Frank builds diagnostic artifact with:
  - [ ] Previous failure patterns
  - [ ] Rejection reasons
  - [ ] Lessons learned
  - [ ] Recurrence counts
- [ ] Mason reads diagnostic artifact before starting
- [ ] Mason adjusts behavior based on diagnostic
- [ ] All tests pass

**Priority:** High
**Component:** Frank strategy
**Estimated Effort:** 8 hours
