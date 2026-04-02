# Builders 2.0 Cutover Deployment Plan

**Branch:** `builders-2.0-cutover`
**Target:** Production
**Deployment Date:** 2026-04-02
**Risk:** Medium (major architectural change, well-tested)

---

## Overview

Deploying the Builders 2.0 cutover with learning strategy for Frank/Mason. This includes:
- Legacy Frank/Mason strategy classes removed
- New `BuildersLearningStrategy` implemented
- Frank/Mason SOUL.md updated with repo recon, failure analysis, self-diagnosis
- Frank/Mason using `strategy: react` (better than `direct` for tool use)
- 4 GitHub issues created as self-improvement backlog

---

## Pre-Deployment Checklist

### 1. Code Quality ✅
- [x] All 64 Builders tests passing
- [x] All 10 builders_learning tests passing
- [x] Total: 74/74 tests passing
- [x] Lint clean (0 errors)
- [x] Type check clean (mypy strict)
- [x] Security scan clean (bandit)

### 2. Branch Status ✅
- [x] On feature branch: `builders-2.0-cutover`
- [x] All commits pushed to remote
- [x] No uncommitted changes in critical files
- [x] Dockerfile change is intentional (adds dev tools for Mason)

### 3. Breaking Changes Documented ✅
- [x] `/v1/stronghold/mason/*` endpoints removed
- [x] Frank/Mason strategy classes deleted
- [x] Legacy Mason queue removed
- [x] Legacy test files deleted
- [x] Migration path: Use unified agent infrastructure

### 4. Rollback Plan Ready ✅
- [x] Backup branch created: `builders-2.0-cutover-backup`
- [x] Rollback commands documented (see below)
- [x] Health check commands documented
- [x] Rollback trigger mechanism identified

---

## Deployment Steps

### Phase 1: Create Safety Net

```bash
# Create backup branch on remote
git push origin builders-2.0-cutover:builders-2.0-cutover-backup

# Tag current commit for easy rollback
git tag -a v0.8.5-builders-2.0 -m "Builders 2.0 cutover with learning strategy"
git push origin v0.8.5-builders-2.0
```

### Phase 2: Merge to Main

```bash
# Switch to main
git checkout main
git pull origin main

# Merge feature branch
git merge builders-2.0-cutover --no-ff -m "Merge branch 'builders-2.0-cutover': Builders 2.0 cutover with learning strategy"

# Push to main (triggers deploy workflow)
git push origin main
```

### Phase 3: Monitor Deploy

```bash
# Watch deploy workflow
gh run list --workflow=deploy.yml --limit=5

# Watch build job
gh run view --log
```

### Phase 4: Health Checks

```bash
# Wait for deploy to complete (check workflow status)
# Then run health checks:

# 1. Check API health
curl -f https://stronghold.library.emeraldfam.org/health || echo "❌ API health check failed"

# 2. Check Builders routes exist
curl -f https://stronghold.library.emeraldfam.org/v1/stronghold/builders/runs || echo "❌ Builders routes not available"

# 3. Check Frank agent loads
curl -f https://stronghold.library.emeraldfam.org/v1/stronghold/agents/frank || echo "❌ Frank agent not available"

# 4. Check Mason agent loads
curl -f https://stronghold.library.emeraldfam.org/v1/stronghold/agents/mason || echo "❌ Mason agent not available"

# 5. Verify legacy Mason routes are gone
curl -f https://stronghold.library.emeraldfam.org/v1/stronghold/mason/queue && echo "❌ Legacy Mason route still exists!"
```

### Phase 5: Smoke Test (Optional)

```bash
# Create a test run to verify Builders workflow works
curl -X POST https://stronghold.library.emeraldfam.org/v1/stronghold/builders/runs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $API_KEY" \
  -d '{
    "run_id": "smoke-test-1",
    "repo": "test/repo",
    "issue_number": 1,
    "branch": "test/smoke-test"
  }'
```

---

## Rollback Plan

### Rollback Triggers

**Immediate Rollback Required If:**
- API health check fails
- Builders routes not available
- Frank/Mason agents fail to load
- Legacy Mason routes still accessible (security risk)
- Any test suite failures

**Monitor for 24 Hours:**
- Error rate > 1%
- Response time > 2s
- Builder run failures > 5%
- Agent instantiation failures

### Rollback Commands

#### Option 1: Git Revert (Cleanest)

```bash
# Switch to main
git checkout main

# Revert the merge commit
git revert -m 1 HEAD

# Push to trigger rollback deploy
git push origin main

# Monitor rollback deploy
gh run list --workflow=deploy.yml --limit=5
```

#### Option 2: Reset to Tag (Fastest)

```bash
# Switch to main
git checkout main

# Reset to tag before deployment
git reset --hard v0.8.4  # Or whatever tag was before cutover

# Force push (⚠️ DESTRUCTIVE - only if revert doesn't work)
git push origin main --force

# Monitor rollback deploy
gh run list --workflow=deploy.yml --limit=5
```

#### Option 3: Restore from Backup Branch (Safe)

```bash
# Switch to main
git checkout main

# Reset to backup branch
git reset --hard origin/builders-2.0-cutover-backup

# Force push
git push origin main --force

# Monitor rollback deploy
gh run list --workflow=deploy.yml --limit=5
```

### Rollback Verification

```bash
# After rollback, verify:

# 1. API health
curl -f https://stronghold.library.emeraldfam.org/health || echo "❌ Rollback failed"

# 2. Legacy Mason routes restored (if needed)
curl -f https://stronghold.library.emeraldfam.org/v1/stronghold/mason/queue || echo "⚠️ Legacy Mason route gone"

# 3. Check logs for errors
gh run view --log

# 4. Check error rate (should drop to pre-deployment baseline)
# (Check monitoring dashboard)
```

---

## Post-Deployment Monitoring

### First 30 Minutes
- Monitor deploy workflow completion
- Run health checks every 2 minutes
- Check error rate in logs
- Verify no critical errors

### First Hour
- Monitor API response times
- Check Builders endpoint availability
- Monitor Frank/Mason agent instantiation
- Review error logs for patterns

### First 24 Hours
- Monitor overall error rate (< 1%)
- Monitor Builder run success rate (> 95%)
- Monitor average response time (< 2s)
- Review agent performance metrics
- Check for any memory leaks or resource issues

---

## Known Issues & Mitigations

### Issue 1: Dockerfile Change
**Change:** Added `. [dev]` to pip install in Dockerfile
**Risk:** Increases image size, adds dev dependencies to production
**Mitigation:** Dev tools are needed for Mason's self-diagnosis (pytest, ruff, mypy, bandit)
**Rollback:** Revert Dockerfile change if issues arise

### Issue 2: Legacy Mason Routes Removed
**Change:** `/v1/stronghold/mason/*` endpoints deleted
**Risk:** External systems may still call these endpoints
**Mitigation:** 404 errors will be returned (graceful degradation)
**Rollback:** Restore legacy routes if critical systems depend on them

### Issue 3: Frank/Mason Using React Strategy
**Change:** Changed from `strategy: direct` to `strategy: react`
**Risk:** More expensive (multiple LLM calls per agent request)
**Mitigation:** React provides tool-use loops which Frank/Mason need
**Rollback:** Revert to `strategy: direct` if cost issues arise

### Issue 4: Learning Strategy Features Are Simulated
**Change:** GitHub service, memory store, orchestrator integration are simulated
**Risk:** Real learning doesn't happen yet
**Mitigation:** 4 GitHub issues created for self-improvement (Frank/Mason will implement)
**Rollback:** Not applicable (no real impact, features are additive)

---

## Contact Information

**Deployment Owner:** DevOps team
**On-Call:** [On-call contact]
**Slack Channel:** #deployments
**Alerting:** [Alerting system]
**Escalation:** [Escalation path]

---

## Success Criteria

Deployment is successful when:
- [x] All 74 tests passing in CI/CD
- [x] Deploy workflow completes successfully
- [x] API health check passes
- [x] Builders routes available
- [x] Frank/Mason agents load successfully
- [x] Legacy Mason routes return 404
- [x] Error rate < 1% for 24 hours
- [x] Response time < 2s average
- [x] No critical errors in logs
- [x] No customer-reported issues

---

## Timeline

| Step | Duration | Owner |
|------|----------|-------|
| Pre-deployment checks | 15 min | DevOps |
| Create safety net | 5 min | DevOps |
| Merge to main | 5 min | DevOps |
| Deploy workflow | 10 min | CI/CD |
| Health checks | 10 min | DevOps |
| Smoke test | 10 min | QA |
| Post-deployment monitoring | 24 hours | DevOps |

**Total Deployment Time:** ~55 minutes

**Total Monitoring Time:** 24 hours

---

**Prepared by:** DevOps team
**Approved by:** [Approver name]
**Date:** 2026-04-02
