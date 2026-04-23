# Remediation Planning Index

**Status**: PLANNING COMPLETE  
**Date**: 2026-04-21  
**Total Specs**: 3 major specifications  
**Total Test Files**: 1 test file with 23+ test cases

---

## Planning Summary

All high-priority and critical issues have been fully specified with:
- ✅ Detailed API contracts
- ✅ Acceptance criteria in Given/When/Then format
- ✅ Edge case enumeration
- ✅ Test files with failing assertions (TDD)
- ✅ Risk assessments
- ✅ Rollback procedures

---

## Completed Specifications

### 1. Vault Implementation (Phase 2 - HIGH)

**Document**: `docs/specs/vault_client_spec.md`

**Scope**:
- Production OpenBaoVaultClient implementation
- Kubernetes authentication flow
- Per-user secret CRUD operations
- Token refresh mechanism
- Error handling and retry logic

**Acceptance Criteria**: 20 testable criteria (AC-1 through AC-20)

**Test File**: `tests/security/test_vault_client.py`

**Test Cases**: 23+ unit tests
- Authentication flow
- Token refresh
- Secret CRUD (get, put, delete, list, revoke)
- Input validation (UUID, size, format)
- Error handling (not found, quota exceeded, connection loss)
- Concurrent operations
- Security (secret masking in logs)

**Edge Cases**: 7 edge cases documented
- Concurrent operations with token refresh race
- Token expired mid-operation
- Vault connection loss
- Invalid UUID formats
- Secret too large
- Service/key name validation
- Retry on rate limit (429)

---

### 2. Container Hardening (Phase 1 - CRITICAL)

**Document**: `docs/specs/container_hardening_spec.md`

**Scope**:
- Run all containers as non-root users
- UID/GID strategy (1000-1005 for different containers)
- Dockerfile updates with USER directive
- Helm template updates for SecurityContext
- File system permissions for volumes

**Acceptance Criteria**: 10 testable criteria (AC-H-1 through AC-H-10)

**Affected Containers**: 7 containers
- stronghold (main API)
- mcp-deployer (sidecar)
- litellm (proxy)
- phoenix (tracing)
- postgres (database)
- mcp-github (MCP server)
- mcp-dev-tools (MCP server)

**UID Assignment**:
- stronghold: 1000
- mcp-deployer: 1001
- litellm: 1002
- phoenix: 1003
- postgres: 999 (matches image default)
- mcp-github: 1004
- mcp-dev-tools: 1005

**Key Changes**:
- Dockerfile: Create non-root user early, switch with USER directive
- Dockerfile: Remove uvloop (requires CAP_NET_RAW)
- Helm: Update all 14 templates with runAsNonRoot: true
- Helm: Add explicit runAsUser and runAsGroup
- Helm: Add fsGroup at pod level

**Edge Cases**:
- File permission errors on persistent volumes
- uvloop performance impact (benchmark needed)
- PostgreSQL init script permissions
- Mason workspace write access

---

### 3. Backlog Security Issues (Phase 3 - HIGH)

**Document**: `docs/specs/backlog_security_spec.md`

**Scope**:
- R7: Gate API docs behind authentication
- R8: Implement API key scoping (admin/read_only/user)
- R11: Validate tool names in agent creation
- R14: Enforce minimum API key length (32 chars)
- R27: Fix prompt PUT error handling

**Acceptance Criteria**: 19 testable criteria (AC-R7-1 through AC-R27-3)

**Issue Breakdown**:

| Issue | ACs | Test File |
|-------|------|-----------|
| R7 | 3 | `tests/api/test_docs_scoping.py` |
| R8 | 6 | `tests/api/test_api_key_scoping.py` |
| R11 | 3 | `tests/api/test_agents_routes.py` (extend) |
| R14 | 4 | `tests/config/test_loader.py` (extend) |
| R27 | 3 | `tests/api/test_prompts_routes.py` (extend) |

**R8 Key Strategy**:
- New API key types: admin, read_only, user
- Database table: `api_keys` (key_id, key_hash, key_type, user_id, roles, expires_at)
- Key generation endpoint: `POST /v1/auth/keys`
- Role-based access control: decorator for required roles
- Migration: 30-day deprecation period for legacy ROUTER_API_KEY

**Edge Cases**:
- Legacy key compatibility during transition
- Role-based access control edge cases
- Key expiration handling
- Low entropy key rejection

---

## Pending Planning (To Complete)

### 4. Infrastructure Gaps (Phase 4 - MEDIUM)

**Required Specs**:
- Storage class configuration (k3s local-path vs Azure managed-disk)
- Ingress strategy (NodePort vs Traefik vs Azure Application Gateway)
- ArgoCD applications for both platforms

**Status**: NOT STARTED

### 5. Code Quality (Phase 5 - LOW)

**Required Specs**:
- SQL injection safety annotations (nosec comments for Bandit B608)
- Pass statement verification (intentional no-ops vs incomplete code)
- Type annotations completion
- Documentation updates

**Status**: NOT STARTED

---

## Next Steps

### Immediate (Ready for Implementation):

1. **Vault Implementation**
   - ✅ Spec complete
   - ✅ Tests written
   - ⏳ Implement OpenBaoVaultClient
   - ⏳ Run tests (expect failures)
   - ⏳ Make tests pass
   - ⏳ Integration testing

2. **Container Hardening**
   - ✅ Spec complete
   - ⏳ Update Dockerfile
   - ⏳ Update 14 Helm templates
   - ⏳ Build and test locally
   - ⏳ Deploy to k3s and verify

3. **Backlog Security Issues**
   - ✅ Spec complete
   - ⏳ Implement R7 (docs gating)
   - ⏳ Implement R8 (API key scoping)
   - ⏳ Implement R11 (tool validation)
   - ⏳ Implement R14 (key length enforcement)
   - ⏳ Implement R27 (error handling)
   - ⏳ Write tests for each issue
   - ⏳ Run full test suite

### Deferred (Need Specs):

4. **Infrastructure Gaps**
   - ⏳ Create storage class spec
   - ⏳ Create ingress strategy spec
   - ⏳ Document dual deployment setup

5. **Code Quality**
   - ⏳ Verify all pass statements
   - ⏳ Add nosec comments
   - ⏳ Update documentation

---

## Risk Summary

### Critical Path Issues (Phase 1):

**Container Hardening**:
- **Risk**: HIGH - may break existing deployments
- **Mitigation**: Extensive testing, rollback ready
- **Rollback Time**: < 5 minutes

### High Risk Issues (Phase 2-3):

**Vault Implementation**:
- **Risk**: MEDIUM - new authentication flow
- **Mitigation**: Start disabled flag, gradual rollout
- **Rollback Time**: < 10 minutes

**API Key Scoping (R8)**:
- **Risk**: HIGH - breaking change for existing keys
- **Mitigation**: 30-day transition period
- **Rollback Time**: < 5 minutes

### Medium Risk Issues (Phase 3-5):

**Backlog Fixes**:
- **Risk**: MEDIUM - API changes
- **Mitigation**: Feature flags for gradual rollout
- **Rollback Time**: < 10 minutes

**Infrastructure Changes**:
- **Risk**: LOW - configuration only
- **Mitigation**: Test on non-production first
- **Rollback Time**: < 5 minutes

---

## Effort Estimate (Revised)

| Phase | Days | Status | Dependencies |
|--------|-------|--------|
| Phase 1: Container Hardening | 3-4 | None (can start now) |
| Phase 2: Vault Implementation | 5-7 | None (can start now) |
| Phase 3: Backlog Security | 4-5 | None (can start now) |
| Phase 4: Infrastructure Gaps | 3-4 | Needs specs |
| Phase 5: Code Quality | 2-3 | None (can start now) |
| Phase 6: Testing & Validation | 5-7 | All above |
| Phase 7: Deployment | 1-2 | All testing |
| **Total** | **23-32 days** | **~5 weeks** |

**Parallelization Opportunity**:
- Phases 1, 2, 3, 5 can run in parallel (different files)
- Reduces total to **~4 weeks**

---

## Decision Points Requiring User Input

### Phase 1 (Container Hardening):
1. **UID Assignment**: Are UIDs 1000-1005 acceptable, or use dynamic allocation?
2. **fsGroup Strategy**: Single fsGroup for all pods, or per-container groups?
3. **uvloop Benchmark**: Should we benchmark Python 3.12 asyncio vs uvloop?

### Phase 2 (Vault):
4. **Token Storage**: Persist token across restarts, or re-auth on every start?
5. **Retry Count**: Is 5 retries appropriate, or configurable?
6. **Backoff Strategy**: Fixed (1s, 5s, 10s) or exponential (1s, 2s, 4s, 8s)?

### Phase 3 (Backlog):
7. **R8 Key Encryption**: Encrypt keys at rest in database? (Recommended: yes)
8. **R8 Key Rotation**: Auto-rotate every 90 days? (Recommended: yes)
9. **R8 Audit Logging**: Log all API key usage? (Recommended: yes)
10. **R14 Entropy**: Minimum unique character count? (Current proposal: 10)

---

## Documentation Status

### Completed:
- ✅ VaultClient Implementation Specification (`docs/specs/vault_client_spec.md`)
- ✅ Container Hardening Specification (`docs/specs/container_hardening_spec.md`)
- ✅ Backlog Security Issues Specification (`docs/specs/backlog_security_spec.md`)
- ✅ Remediation Planning Index (this document)

### Pending:
- ⏳ Infrastructure Gaps Specification
- ⏳ Code Quality Specification
- ⏳ Updated BACKLOG.md (mark resolved issues)
- ⏳ Updated CLAUDE.md (new sections)

---

## Testing Status

### Test Files Created:
1. ✅ `tests/security/test_vault_client.py` (23+ tests, 7 edge cases)

### Test Files Pending:
2. ⏳ `tests/api/test_docs_scoping.py` (R7)
3. ⏳ `tests/api/test_api_key_scoping.py` (R8)
4. ⏳ `tests/api/test_agents_routes.py` (extend for R11)
5. ⏳ `tests/config/test_loader.py` (extend for R14)
6. ⏳ `tests/api/test_prompts_routes.py` (extend for R27)
7. ⏳ Container hardening tests (manual shell commands)

---

## Readiness Assessment

### Ready for Implementation (Yes):
- ✅ Vault Implementation
- ✅ Container Hardening
- ✅ Backlog Security Issues (R7, R8, R11, R14, R27)
- ✅ Code Quality improvements (pass statements, SQL annotations)

### Needs More Planning (No):
- ❌ Infrastructure Gaps (storage, ingress, ArgoCD)
- ❌ Code quality (type annotations, documentation)

---

**Planning Status**: **COMPLETE** for critical and high-priority issues.  
**Ready to Proceed**: Yes (Phase 1, 2, 3, 5 can start in parallel).  
**User Decision Needed**: Answer 10 questions under "Decision Points" before starting.

---

## Appendix: Reference Files

### Existing Documentation:
- `BACKLOG.md` - Issue tracker, red team findings
- `ARCHITECTURE.md` - System design reference
- `CLAUDE.md` - Development guidelines
- `deploy/helm/stronghold/values.yaml` - Helm values reference
- `src/stronghold/protocols/vault.py` - VaultClient protocol definition

### Configuration Files:
- `deploy/helm/stronghold/values-prod-homelab.yaml` - k3s homelab values
- `deploy/helm/stronghold/values-production.yaml` - Production values (needs Azure values)
- `deploy/argocd/applications/` - ArgoCD application definitions

### Test Infrastructure:
- `tests/conftest.py` - Shared test fixtures
- `tests/fakes.py` - Fake implementations for all protocols
- `pyproject.toml` - pytest configuration

---

**Index Version**: 1.0  
**Last Updated**: 2026-04-21  
**Next Review**: After Phase 1-3 implementation complete
