# Container Hardening Specification

**Status**: DRAFT  
**Phase**: 1 - CRITICAL Priority  
**Impact**: All Stronghold containers must run as non-root users  
**Platform**: Both k3s homelab and Azure AKS

---

## 1. Purpose

Eliminate root privileges from all Stronghold containers to comply with Kubernetes Pod Security Standards and reduce attack surface. Running containers as non-root users limits damage if a container is compromised.

**Current State**: All 14 deployment templates have `runAsNonRoot: false` with TODO comments.

---

## 2. Scope

### 2.1 Affected Containers

**Primary Application**:
- `stronghold` (main API container)

**Sidecars**:
- `mcp-deployer` (Kubernetes deployment sidecar)

**Supporting Services**:
- `litellm` (LiteLLM proxy)
- `phoenix` (Arize Phoenix tracing)
- `postgres` (PostgreSQL database)
- `mcp-github` (GitHub MCP server)
- `mcp-dev-tools` (Dev tools MCP server)

### 2.2 Affected Files

**Helm Templates** (14 locations):
1. `deployment-stronghold.yaml` (3 instances: pod spec, main container, sidecar container)
2. `deployment-litellm.yaml` (2 instances: pod spec, container)
3. `deployment-phoenix.yaml` (2 instances: pod spec, container)
4. `deployment-mcp-github.yaml` (2 instances: pod spec, container)
5. `deployment-mcp-dev-tools.yaml` (2 instances: pod spec, container)
6. `statefulset-postgres.yaml` (2 instances: pod spec, container)

**Dockerfiles**:
- `Dockerfile` (main stronghold image)
- Sidecar images (if separate builds needed)

---

## 3. UID/GID Strategy

### 3.1 UID Assignment

| Container | UID | GID | Rationale |
|-----------|------|------|-----------|
| stronghold | 1000 | 1000 | Standard non-root user ID |
| mcp-deployer | 1001 | 1001 | Unique from stronghold |
| litellm | 1002 | 1002 | Unique from others |
| phoenix | 1003 | 1003 | Unique from others |
| postgres | 999 | 999 | Matches PostgreSQL image default |
| mcp-github | 1004 | 1004 | Unique from others |
| mcp-dev-tools | 1005 | 1005 | Unique from others |

### 3.2 Consistent Strategy

All containers:
- Use UID > 0 (non-root)
- Use GID matching UID (primary group)
- Add supplementary groups if needed (e.g., docker group for mcp-deployer)
- Set `fsGroup` in pod spec for file system permissions

### 3.3 Platform Considerations

**k3s Homelab**:
- UID 1000+ works with local-path storage
- No issues with file permissions on host volumes
- Compatible with standard Linux permission model

**Azure AKS**:
- UID 1000+ works with managed disks
- Compatible with Azure Pod Identity
- No issues with Azure-specific storage classes

---

## 4. Dockerfile Changes

### 4.1 Main Stronghold Dockerfile

**Current Issues**:
```dockerfile
FROM python:3.12-slim
# No USER directive - runs as root by default
WORKDIR /app
# ...
CMD ["uvicorn", "stronghold.api.app:create_app", ...]
```

**Required Changes**:
```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install ".[dev]"

FROM python:3.12-slim

# Create non-root user early
RUN groupadd -r stronghold && \
    useradd -r -g stronghold stronghold && \
    mkdir -p /app /workspace && \
    chown -R stronghold:stronghold /app /workspace && \
    chmod 755 /workspace

# Install git as root before switching user
RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    rm -rf /var/lib/apt/lists/*

USER stronghold
WORKDIR /app

COPY --from=builder --chown=stronghold:stronghold /install /usr/local
COPY --chown=stronghold:stronghold src/ src/
COPY --chown=stronghold:stronghold agents/ agents/
COPY --chown=stronghold:stronghold tests/ tests/
COPY --chown=stronghold:stronghold migrations/ migrations/
COPY --chown=stronghold:stronghold config/ config/
COPY --chown=stronghold:stronghold pyproject.toml .

# Fix uvloop issue (run as non-root)
# uvloop requires socketpair() which fails without CAP_NET_RAW
RUN pip uninstall -y uvloop 2>/dev/null; true

EXPOSE 8100

# Verify non-root at container startup
USER stronghold
CMD ["uvicorn", "stronghold.api.app:create_app", "--host", "0.0.0.0", "--port", "8100", "--factory"]
```

**Key Changes**:
1. Create `stronghold` user with group before any RUN commands
2. Set `USER stronghold` early in Dockerfile
3. Use `--chown=stronghold:stronghold` for COPY commands
4. Change ownership of `/workspace` directory (Mason worktrees)
5. Remove `uvloop` (requires CAP_NET_RAW, incompatible with non-root)
6. Add healthcheck to verify non-root user

### 4.2 uvloop Dependency

**Current Workaround**:
```dockerfile
# Remove uvloop — it requires socketpair() which fails in unprivileged containers
RUN pip uninstall -y uvloop 2>/dev/null; true
```

**Root Cause**: `uvloop` requires Linux capabilities (CAP_NET_RAW) not available to non-root containers.

**Long-term Solution**: Replace uvloop with native asyncio (Python 3.12 has excellent async performance).

**Acceptance**: For now, uninstall uvloop. Performance impact is minimal on modern Python 3.12.

### 4.3 Sidecar Dockerfiles

If sidecars have separate Dockerfiles (not currently the case), apply same pattern:
- Create unique UID/GID for each
- Set USER early
- Use --chown for COPY
- Verify permissions at startup

---

## 5. Helm Template Changes

### 5.1 Template Updates

**Pattern for all deployments**:
```yaml
spec:
  serviceAccountName: {{ include "stronghold.serviceAccountName.strongholdApi" . }}
  securityContext:
    runAsNonRoot: true
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: stronghold
      image: {{ include "stronghold.image" (dict "image" .Values.strongholdApi.image "root" .) }}
      imagePullPolicy: {{ include "stronghold.imagePullPolicy" (dict "image" .Values.strongholdApi.image) }}
      securityContext:
        allowPrivilegeEscalation: false
        readOnlyRootFilesystem: true
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        capabilities:
          drop: ["ALL"]
```

**Template Changes**:
- Remove `runAsNonRoot: false` TODO comments
- Add explicit `runAsUser` and `runAsGroup`
- Add `fsGroup` at pod level for volume permissions
- Keep `allowPrivilegeEscalation: false` (already correct)
- Keep `readOnlyRootFilesystem: true` (already correct)
- Keep `capabilities.drop: ["ALL"]` (already correct)

### 5.2 UID Configuration in Values

**Add to `values.yaml`**:
```yaml
securityContext:
  runAsNonRoot: true
  runAsUser: 1000
  runAsGroup: 1000
  fsGroup: 1000
```

**Platform Overrides**:
```yaml
# values-prod-homelab.yaml
strongholdApi:
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000

# values-production-azure.yaml
strongholdApi:
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
```

### 5.3 PostgreSQL Special Case

**Issue**: PostgreSQL image runs as UID 999 by default. Changing to 1000 breaks init scripts.

**Solution**: Keep UID 999 for postgres, but ensure `runAsNonRoot: true`.

```yaml
# statefulset-postgres.yaml
spec:
  securityContext:
    runAsNonRoot: true  # postgres runs as UID 999, not root
    fsGroup: 999
    seccompProfile:
      type: RuntimeDefault
  containers:
    - name: postgres
      securityContext:
        runAsNonRoot: true
        allowPrivilegeEscalation: false
        capabilities:
          drop: ["ALL"]
          add: ["CHOWN", "DAC_OVERRIDE", "FOWNER", "SETUID", "SETGID"]  # Required by postgres
```

---

## 6. File System Permissions

### 6.1 Application Data Directories

**Directories** (owned by stronghold:1000):
- `/app` - Application code
- `/tmp` - Temporary files
- `/workspace` - Mason worktrees (git repos)

**Permissions**:
- Owner: `stronghold:stronghold`
- Mode: `755` (rwxr-xr-x)
- Group: `stronghold`

### 6.2 Volume Mounts

**EmptyDir Volumes**:
- `tmp` - `/tmp` (shared emptyDir)
- `mcp-deployer-socket` - `/run/stronghold` (shared emptyDir, mode 0777)

**Persistent Volumes**:
- `postgres-data` - `/var/lib/postgresql/data` (owned by postgres:999)

**Volume Permissions**:
```yaml
volumes:
  - name: mcp-deployer-socket
    emptyDir:
      medium: Memory
      sizeLimit: 16Mi
  - name: tmp
    emptyDir:
      sizeLimit: 64Mi
```

**Mount Permissions**:
- EmptyDir automatically has correct permissions with `fsGroup` set
- Persistent volumes require `fsGroup` at pod level

### 6.3 Mason Workspace Permissions

**Issue**: Mason worktrees require write access to `/workspace`

**Solution**:
```dockerfile
RUN mkdir -p /workspace && \
    chown -R stronghold:stronghold /workspace && \
    chmod 755 /workspace
```

**Runtime**: Mason process runs as `stronghold:1000`, has write access to `/workspace`

---

## 7. Pod Security Standards Compliance

### 7.1 Kubernetes Pod Security Standards (PSS)

**Target Profile**: `restricted` (most secure)

**Requirements**:
- ✅ Containers must run as non-root
- ✅ Containers must drop all capabilities (or minimal required set)
- ✅ `readOnlyRootFilesystem: true` (except where needed)
- ✅ `allowPrivilegeEscalation: false`
- ✅ No `privileged: true`
- ✅ No hostNetwork, hostPID, hostIPC

### 7.2 Compliance Matrix

| Requirement | stronghold | litellm | phoenix | postgres | mcp-github | mcp-dev-tools |
|-------------|-------------|-----------|----------|-----------|--------------|-----------------|
| runAsNonRoot: true | ✅ | ✅ | ✅ | ✅ | ✅ |
| runAsUser > 0 | ✅ | ✅ | ✅ | ✅ | ✅ |
| drop: ["ALL"] | ✅ | ✅ | ✅ | ✅ | ✅ |
| readOnlyRootFS | ✅ | ✅ | ✅ | ⚠️ | ✅ |
| allowPrivilegeEscalation: false | ✅ | ✅ | ✅ | ✅ | ✅ |
| No privileged | ✅ | ✅ | ✅ | ✅ | ✅ |

**Notes**:
- `postgres` requires minimal capabilities (`CHOWN`, `DAC_OVERRIDE`, `FOWNER`, `SETUID`, `SETGID`) for initdb
- `mcp-dev-tools` may need write access for certain tools (reviewed case-by-case)

---

## 8. Testing Strategy

### 8.1 Docker Build Tests

**Test**: Build Dockerfile
```bash
docker build -t stronghold:test .
```

**Acceptance**: Build succeeds without warnings.

### 8.2 Container Permission Tests

**Test 1: Verify Non-Root User**
```bash
docker run --rm stronghold:test whoami
# Expected output: stronghold (not root)

docker run --rm stronghold:test id
# Expected output: uid=1000(stronghold) gid=1000(stronghold)
```

**Test 2: Verify File Ownership**
```bash
docker run --rm stronghold:test ls -la /app
# Expected: files owned by stronghold:stronghold

docker run --rm stronghold:test ls -la /workspace
# Expected: directory owned by stronghold:stronghold, mode 755
```

**Test 3: Verify Write Access**
```bash
docker run --rm stronghold:test bash -c "touch /workspace/test && ls -la /workspace/test"
# Expected: test file created, owned by stronghold:stronghold
```

### 8.3 Kubernetes Pod Tests

**Test 1: Verify runAsNonRoot**
```bash
kubectl exec -it stronghold-api-xxx -- whoami
# Expected: stronghold (not root)

kubectl exec -it postgres-0 -- whoami
# Expected: postgres (UID 999, not root)
```

**Test 2: Verify SecurityContext**
```bash
kubectl get pod stronghold-api-xxx -o yaml | grep -A 5 securityContext
# Expected: runAsNonRoot: true, runAsUser: 1000, etc.
```

**Test 3: Verify Volume Permissions**
```bash
kubectl exec -it stronghold-api-xxx -- ls -la /tmp
# Expected: /tmp writable by stronghold:1000
```

### 8.4 Functional Tests

**Test**: Run application health checks
```bash
# k3s homelab
curl http://10.10.42.31:30443/health
# Expected: 200 OK response

# Azure AKS
curl https://stronghold.prod.example.com/health
# Expected: 200 OK response
```

### 8.5 Integration Tests

**Test**: Verify Mason can create worktrees
```bash
# Trigger Mason workflow
curl -X POST http://localhost:8100/v1/stronghold/mason/tasks \
  -H "Authorization: Bearer $KEY" \
  -d '{"title":"test","content":"Create repo"}'

# Verify Mason completed without permission errors
kubectl logs stronghold-api-xxx | grep "mason" | grep -i "error"
# Expected: No permission errors
```

---

## 9. Rollback Plan

### 9.1 Immediate Rollback

If pods fail to start after changes:
```bash
# Quick rollback to previous image
helm rollback stronghold -n stronghold-platform

# Or restore from backup
helm upgrade --install stronghold deploy/helm/stronghold \
  --namespace stronghold-platform \
  -f stronghold-backup.yaml
```

### 9.2 Rollback Indicators

**Symptoms**:
- Pods in `CrashLoopBackOff` state
- Logs show "Permission denied"
- Logs show "Operation not permitted"
- Health checks fail

**Diagnosis**:
```bash
kubectl describe pod stronghold-api-xxx
# Look for: "permission denied", "operation not permitted"

kubectl logs stronghold-api-xxx
# Look for: OSError, PermissionError
```

---

## 10. Acceptance Criteria

### AC-H-1: Docker Build Success

**Given** Modified Dockerfile with non-root user
**When** `docker build -t stronghold:test .` is executed
**Then**:
- Build completes successfully
- No warnings about privileged operations
- Final image has non-root user

### AC-H-2: Container Runs as Non-Root

**Given** Deployed Stronghold pod
**When** `kubectl exec -- whoami` is run
**Then**:
- Output is `stronghold` (not `root`)
- UID is 1000 (not 0)

### AC-H-3: File Ownership Correct

**Given** Running Stronghold container
**When** `ls -la /app` is run
**Then**:
- Files are owned by `stronghold:stronghold`
- No files owned by `root`

### AC-H-4: Workspace Writable

**Given** Running Stronghold container
**When** Mason creates worktree in `/workspace`
**Then**:
- Worktree is created successfully
- No permission errors in logs
- Git operations complete

### AC-H-5: PostgreSQL Non-Root

**Given** Deployed PostgreSQL StatefulSet
**When** `kubectl exec -- whoami` is run
**Then**:
- Output is `postgres` (UID 999, not root)
- Database initializes successfully

### AC-H-6: All Pods Running

**Given** Helm chart deployed with hardened settings
**When** `kubectl get pods -n stronghold-platform` is run
**Then**:
- All pods in `Running` state
- No pods in `CrashLoopBackOff`
- No pods in `Error` state

### AC-H-7: Health Endpoint Responds

**Given** Running Stronghold API
**When** `curl http://<ip>:<port>/health` is called
**Then**:
- Returns HTTP 200
- Response includes `"status": "ok"`
- Response time < 1 second

### AC-H-8: SecurityContext Correct

**Given** Stronghold pod
**When** Pod spec is inspected
**Then**:
- `runAsNonRoot: true`
- `runAsUser: 1000` (or other non-zero UID)
- `fsGroup: 1000` (or appropriate group)
- `allowPrivilegeEscalation: false`

### AC-H-9: No Privileged Containers

**Given** Helm chart values
**When** Chart is deployed
**Then**:
- No containers have `privileged: true`
- No containers have host networking
- No containers mount host paths

### AC-H-10: uvloop Removed

**Given** Built Stronghold image
**When** Container runs Python code
**Then**:
- `uvloop` is not imported
- Native asyncio is used
- No capability errors in logs

---

## 11. Risk Assessment

### 11.1 High Risk

**Permission Errors**: Changing user ID may break existing file permissions on persistent volumes.
- **Mitigation**: Test on clean volumes first, set `fsGroup` to force ownership
- **Rollback**: Revert to `runAsUser: 0` if critical

**uvloop Performance Loss**: Removing uvloop may degrade async performance.
- **Mitigation**: Benchmark before/after, Python 3.12 has improved asyncio
- **Fallback**: Add minimal capabilities (`CAP_NET_RAW`) if performance is unacceptable

### 11.2 Medium Risk

**Database Init Failure**: PostgreSQL UID change may break initdb.
- **Mitigation**: Keep PostgreSQL at UID 999 (its default), only enforce `runAsNonRoot: true`
- **Test**: Verify PostgreSQL starts with new settings before deploying

**MCP Deployer Permissions**: Sidecar may not have permissions to deploy pods.
- **Mitigation**: Ensure RBAC is correct for mcp-deployer ServiceAccount
- **Test**: Verify mcp-deployer can create deployments in test namespace

### 11.3 Low Risk

**Build Time Increase**: `--chown` operations add ~10-20 seconds to build.
- **Acceptable**: Security benefit outweighs minor build time increase

---

## 12. Open Questions

1. **uid Assignment**: Are the proposed UID values (1000-1005) acceptable, or should we use dynamic UIDs?
2. **fsGroup Strategy**: Should we use a single `fsGroup` for all pods, or per-container groups?
3. **uvloop Alternative**: Should we benchmark Python 3.12 asyncio vs uvloop to quantify performance impact?
4. **PostgreSQL Capabilities**: Is the `CHOWN, DAC_OVERRIDE, FOWNER, SETUID, SETGID` list minimal for PostgreSQL?
5. **Mason Workspace**: Is `/workspace` writable with `fsGroup: 1000`, or do we need `mode: 0777`?

---

**Document Version**: 1.0  
**Last Updated**: 2026-04-21  
**Status**: Ready for Dockerfile and template updates
