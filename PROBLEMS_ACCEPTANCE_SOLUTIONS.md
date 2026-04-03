# Stronghold Per-User Agent Pods - Problems, Acceptance Criteria, and Solutions

---

## Problem Statement Overview

**Current State:**
- Single monolithic Python process runs all agents
- No per-user isolation or scaling
- Request latency = LLM time only (no pod management overhead, but also no per-user state)

**Desired State:**
- Each user gets their own agent pod
- Generic pods: hot-swappable prompts/tools, <50ms latency
- Premium pods: dedicated resources (Davinci, Mason)
- Router discovers, spawns, and manages pods automatically

---

## Architecture Problems

### P-1: Router-to-Pod Communication Contract

**PROBLEM:**
No defined contract between router and agent pods. This means:
- Router doesn't know what data to send
- Pods don't know what data to receive
- No guaranteed compatibility between different implementations
- Can't add new fields without breaking existing code

**ACCEPTANCE CRITERIA:**
- [ ] Router can create AgentTask object and serialize to JSON
- [ ] Agent pods can deserialize AgentTask and process it
- [ ] Both sides can handle new optional fields (backwards compatible)
- [ ] Type errors caught at serialization time, not runtime
- [ ] All fields have explicit types and validation

**SOLUTION:**
Define `AgentPodProtocol`, `AgentTask`, `AgentResult` dataclasses with `dataclasses_json` serialization. Add tests that verify round-trip serialization maintains data integrity.

**HOW THIS SOLVES THE PROBLEM:**
- Clear contract eliminates ambiguity
- Type safety prevents runtime errors
- Backwards compatible field addition allows evolution
- Router and any pod implementation can interoperate

---

### P-2: User Pod Discovery

**PROBLEM:**
Router receives a request for `user_123` but doesn't know:
- Which pod serves this user?
- What's the pod's IP address?
- Is the pod alive?
- Has the user's pod died and been replaced?

**ACCEPTANCE CRITERIA:**
- [ ] Router can find user's pod in <5ms (cache hit)
- [ ] Router can find user's pod in <50ms (cache miss, K8s lookup)
- [ ] Discovery returns `None` if no pod exists (triggers spawn)
- [ ] Discovery returns `None` if pod is unhealthy
- [ ] Discovery automatically refreshes when pod IP changes
- [ ] Discovery handles pod replacement (old IP invalidated)

**SOLUTION:**
Implement `PodDiscovery` with Redis cache (TTL 5m) + K8s label selector fallback. Cache key format: `pod:{user_id}:{agent_type}` → `pod_ip:port`. K8s query: `labels={"user": user_id, "type": agent_type}`.

**HOW THIS SOLVES THE PROBLEM:**
- Fast cache lookups provide <5ms discovery
- K8s fallback provides correctness when cache is wrong
- None return clearly indicates "pod doesn't exist"
- TTL auto-refreshes on pod changes

---

### P-3: On-Demand Pod Creation

**PROBLEM:**
New user signs up and receives a request, but:
- No pod exists for them
- Router doesn't know how to create one
- No way to apply user-specific config
- No cleanup mechanism for idle pods

**ACCEPTANCE CRITERIA:**
- [ ] System can spawn a pod for any user on first request
- [ ] Pod spawns with correct AGENT_TYPE env variable
- [ ] Pod gets user's custom prompts/tools loaded
- [ ] Pod gets correct resource limits applied
- [ ] Pod labeled with user_id and agent_type for discovery
- [ ] Idle pods auto-terminate after configurable timeout
- [ ] Pod creation rate-limited per org to prevent abuse

**SOLUTION:**
Implement `PodSpawner` using K8s Python client. Create pod manifest with: user labels, env vars for config, resource limits. Implement cleanup job or TTL controller for idle termination.

**HOW THIS SOLVES THE PROBLEM:**
- New users get pods automatically
- User config applied at pod creation time
- Resource isolation per user
- Prevents resource waste via auto-cleanup
- Abuse protection via rate limits

---

### P-4: Lightweight Agent Pod Runtime

**PROBLEM:**
Current Stronghold image is ~4GB (monolithic app). Using it for agent pods means:
- 30s+ cold start time
- 4GB RAM minimum (wasteful for simple agents)
- Includes router/classifier/LLM client code pods don't need
- Can't scale efficiently (memory waste × N pods)

**ACCEPTANCE CRITERIA:**
- [ ] Agent pod image <500MB
- [ ] Cold start time <5s
- [ ] Runtime memory <512MB
- [ ] Exposes FastAPI /v1/agent/execute endpoint
- [ ] Exposes /health endpoint for readiness checks
- [ ] Connects directly to PostgreSQL (no router needed)
- [ ] Connects directly to LiteLLM (no router needed)

**SOLUTION:**
Create `Dockerfile.agent` from `python:3.12-slim`, install only runtime deps (fastapi, uvicorn, psycopg2, redis, pyyaml). Copy only `src/stronghold/agent_pod/` directory. Implement `main.py` with FastAPI, not full app.

**HOW THIS SOLVES THE PROBLEM:**
- Small image = fast startup + low memory
- Eliminates unused code (router, classifier, dashboard)
- Direct DB/LiteLLM connections = one less network hop
- Enables scaling to 100+ pods without memory pressure

---

### P-5: User Configuration Hot-Reload

**PROBLEM:**
User changes their custom SOUL prompt or tool permissions:
- Pod still has old config
- Requires pod restart to pick up changes
- Restart = 30s cold start + lost state
- No way to invalidate config cache

**ACCEPTANCE CRITERIA:**
- [ ] Agent pods fetch user config on each request
- [ ] Config cached with 60s TTL (not permanent)
- [ ] Config changes apply immediately without restart
- [ ] Admin can invalidate a user's config via API
- [ ] Cache invalidation propagates across all user's pods
- [ ] No stale config served (max 60s lag)

**SOLUTION:**
Implement `ConfigManager` with Redis cache (`config:user:{user_id}`, TTL 60s). On each request: fetch from Redis, miss → query PostgreSQL, cache. Admin endpoint: `DELETE /cache/{user_id}` to force invalidation.

**HOW THIS SOLVES THE PROBLEM:**
- Config updates apply immediately (next request)
- No pod restarts required
- Cache reduces DB load while staying fresh
- Admin can force refresh

---

### P-6: Warm Pool with User Affinity

**PROBLEM:**
Without warm pool:
- Every request spawns new pod = 30s latency
- With pre-spawned pods but no affinity:
- Same user might get different pod each request = lost context
- User A's data might be in Pod 1, then Pod 2 = inconsistent state

**ACCEPTANCE CRITERIA:**
- [ ] Pool has N pods pre-spawned (N configurable)
- [ ] Same user always gets same pod (consistent hash)
- [ ] When user's pod dies, they get replacement pod
- [ ] New pods get auto-added when utilization > 80%
- [ ] Idle pods get auto-removed when utilization < 20% for 10m
- [ ] Affinity persisted in Redis (survives pod restart)
- [ ] Pool management runs in background (doesn't block requests)

**SOLUTION:**
Implement `WarmPoolManager` with Redis affinity store (`affinity:user:{user_id}` → `pod_name`). Pre-spawn N generic pods at startup. Background task monitors pod health/usage, scales up/down. On request: check affinity → return assigned pod or spawn new.

**HOW THIS SOLVES THE PROBLEM:**
- 95%+ requests hit warm pods (<50ms latency)
- User state preserved (same pod = shared in-memory state)
- Auto-scaling handles traffic spikes
- Graceful degradation (idle pods removed)

---

### P-7: K8s Autoscaling

**PROBLEM:**
Manual pod management only:
- Can't scale up during traffic spikes
- Can't scale down during idle periods (wasted resources)
- No monitoring of pod health/utilization
- Need to manually edit YAML and apply changes

**ACCEPTANCE CRITERIA:**
- [ ] HPA adds pods when CPU > 70%
- [ ] HPA removes pods when CPU < 20%
- [ ] HPA respects min_replicas (never goes below)
- [ ] HPA respects max_replicas (never exceeds)
- [ ] Pod health checks configured and passing
- [ ] Metrics collection working (Prometheus/metrics-server)
- [ ] Scaling happens automatically within 60s of threshold crossing

**SOLUTION:**
Create K8s HPA resource targeting deployments. Configure metrics: CPU utilization. Set min=1, max=10 (generic), min=0, max=3 (davinci - cold spawn). Add readiness/liveness probes to pods.

**HOW THIS SOLVES THE PROBLEM:**
- Automatic scaling reduces cost (no idle pods)
- Automatic scaling prevents overload during spikes
- No manual intervention needed
- Self-healing (unhealthy pods replaced)

---

### P-8: Circuit Breaker for Failed Pods

**PROBLEM:**
User's pod crashes or hangs:
- Router tries to call it indefinitely
- Request times out after 30s
- User gets generic error
- Router doesn't know pod is unhealthy
- Other requests to same pod also timeout (cascading failure)

**ACCEPTANCE CRITERIA:**
- [ ] Failed pods detected after 3 consecutive failures
- [ ] Failed pods marked as "open" (circuit open)
- [ ] "Open" circuit immediately returns error (no timeout)
- [ ] Circuit enters "half-open" after 60s to test recovery
- [ ] Circuit returns to "closed" on first success
- [ ] Fallback agent receives failed requests (or graceful error)
- [ ] Circuit state persisted in Redis (survives router restart)

**SOLUTION:**
Implement `CircuitBreaker` per pod IP. Track failures in Redis. States: CLOSED → OPEN → HALF-OPEN → CLOSED. Router checks circuit before calling pod. If open, return 503 with `Retry-After` header, call fallback.

**HOW THIS SOLVES THE PROBLEM:**
- Failed pods don't hang requests (fail fast)
- Prevents cascading timeouts
- Automatic recovery testing (don't need manual intervention)
- Graceful degradation (users still get responses via fallback)

---

## Security Problems

### S-1: JWT Forging Vulnerability

**PROBLEM:**
JWT signed with `ROUTER_API_KEY` (static API key):
- Anyone with API key can forge tokens for ANY user/org/role
- Demo cookie uses same key for signing
- Can grant admin privileges to fake users
- No way to revoke forged tokens

**ACCEPTANCE CRITERIA:**
- [ ] JWT signing key is separate from API key
- [ ] JWT uses RS256 (asymmetric), not HS256 (symmetric)
- [ ] API keys have scopes (read-only, user-level, admin-only)
- [ ] Forged JWT signature doesn't validate
- [ ] Token has `iss` (issuer) claim that's validated
- [ ] Token has `aud` (audience) claim that's validated
- [ ] Tokens have `exp` (expiration) and are rejected when expired
- [ ] Demo JWT uses short-lived, expiring key (not router key)

**SOLUTION:**
Generate 2048-bit RSA key pair for JWT signing. Store private key in K8s secret (not .env). Use RS256 for signing. Create `api_keys` table with `scope` column. Validate `iss`, `aud`, `exp` claims on every decode. Remove or separate demo cookie signing key with 1-hour expiry.

**HOW THIS SOLVES THE PROBLEM:**
- API key alone can't forge tokens (need private key)
- Scoping limits damage if private key leaks
- Claim validation prevents acceptance of malformed tokens
- Short-lived demo tokens reduce attack window

---

### S-2: Privileged Containers

**PROBLEM:**
`privileged: true` grants full host access:
- Container can read/write host filesystem
- Container can load kernel modules
- Container can modify host network config
- Container can bypass all Linux security modules (AppArmor, SELinux)
- If pod is compromised, attacker owns the host

**ACCEPTANCE CRITERIA:**
- [ ] No container runs with `privileged: true`
- [ ] Postgres runs without `privileged: true`
- [ ] pgvector extension installs successfully
- [ ] Kind K8s cluster access works (if needed) with specific caps
- [ ] Containers have `securityContext` with limited `runAsUser`
- [ ] Only necessary capabilities granted (`NET_ADMIN`, `SYS_PTRACE`)
- [ ] All containers are read-only where possible

**SOLUTION:**
Remove `privileged: true` from both services. Test pgvector setup. If needed, grant specific capabilities via `securityContext.capabilities.add`. Move K8s cluster access to sidecar container with minimal RBAC (namespace-scoped, not cluster-admin).

**HOW THIS SOLVES THE PROBLEM:**
- Container escape attack surface minimized
- AppArmor/SELinux protections active
- Least-privilege principle enforced
- Host is isolated from containerized workloads

---

### S-3: Cluster-Admin Kubeconfig in App Container

**PROBLEM:**
`.kubeconfig-docker` mounted in app container:
- Contains full cluster-admin credentials
- Any code execution can control entire K8s cluster
- Includes RSA private key and client cert
- App container runs with `privileged: true` (compound issue)

**ACCEPTANCE CRITERIA:**
- [ ] App container has no Kubeconfig mount
- [ ] App container has no K8s credentials
- [ ] K8s access is in separate sidecar
- [ ] Sidecar has namespace-scoped RBAC (not cluster-admin)
- [ ] Sidecar RBAC only allows pods/services CRUD in `mcp-tools` namespace
- [ ] Sidecar uses service account token (not mounted kubeconfig)

**SOLUTION:**
Create MCP deployer as separate sidecar container. Create K8s Role/RoleBinding for namespace `mcp-tools` with limited verbs (create, delete, get, list pods/services). Sidecar uses service account token. Remove kubeconfig volume from main app container.

**HOW THIS SOLVES THE PROBLEM:**
- App compromise doesn't give K8s control
- MCP deployer can only manage MCP tools (not entire cluster)
- Principle of least privilege enforced
- Audit trail for K8s actions (via service account)

---

### S-4: API Keys in Container Environment

**PROBLEM:**
All API keys in environment variables:
- `docker exec stronghold env` reveals all keys
- Any code execution in container can read keys
- Keys persist in process list, logs, core dumps
- No way to rotate without restart

**ACCEPTANCE CRITERIA:**
- [ ] No API keys in environment variables
- [ ] Keys stored in K8s secrets
- [ ] Keys mounted as files (read-only)
- [ ] App reads keys from file paths
- [ ] Container runs as non-root user
- [ ] Keys excluded from process listing
- [ ] Provider keys (Cerebras, Mistral) not in app container
- [ ] Only Router key and LiteLLM master key in app

**SOLUTION:**
Create K8s Secret `stronghold-secrets` with `ROUTER_API_KEY` and `LITELLM_MASTER_KEY`. Mount as read-only volume at `/secrets`. App reads via `Path("/secrets/router_api_key").read_text()`. Provider keys only exist in LiteLLM container (via its own env/secrets).

**HOW THIS SOLVES THE PROBLEM:**
- `docker exec env` doesn't reveal secrets
- Process memory dumps don't contain secrets
- Read-only prevents modification
- Non-root user provides defense in depth

---

### S-5: PostgreSQL Exposed on All Interfaces

**PROBLEM:**
PostgreSQL bound to `0.0.0.0:5432`:
- Any host on network can connect
- Weak password (`stronghold/stronghold`)
- Contains all user data, sessions, learnings
- Can dump all data with single connection
- Can modify/delete all data

**ACCEPTANCE CRITERIA:**
- [ ] PostgreSQL not exposed on 0.0.0.0
- [ ] Bound to 127.0.0.1:5432 (localhost only) or removed entirely
- [ ] App connects via Docker DNS (`postgres:5432`)
- [ ] Password is 32+ random chars
- [ ] Password stored in K8s secret (not env var)
- [ ] Existing password rotated

**SOLUTION:**
Remove `ports: - "5432:5432"` from postgres service. Rely on Docker network DNS (`postgres:5432`). Generate new 32-char random password. Store in K8s secret. Rotate all existing passwords.

**HOW THIS SOLVES THE PROBLEM:**
- External hosts can't connect
- Password brute-forcing prevented (not exposed)
- Docker network provides internal-only access
- Secret-based password management (not in git/env files)

---

### S-6: Warden Scan Window Gap

**PROBLEM:**
Warden scans first 10KB and last 2KB:
- Middle content (bytes 10240..(len-2048)) unscanned
- Attacker can hide injection in unscanned region
- Large payloads bypass all L1/L2 patterns
- 22KB test payload showed injection at byte 16500 succeeded

**ACCEPTANCE CRITERIA:**
- [ ] Warden scans entire content
- [ ] OR Warden uses overlapping windows with 50% coverage
- [ ] No region of content is unscanned
- [ ] Scan completes in <100ms for 100KB payload
- [ ] Test with 22KB payload, injection at byte 16500 is blocked
- [ ] Scan performance doesn't degrade with payload size

**SOLUTION:**
Option A: Scan full content (simpler, higher accuracy). Option B: Overlapping windows (10KB windows, 2KB overlap, step 8KB). Implement batched regex matching. Add test case: 22KB payload with injection at byte 16500.

**HOW THIS SOLVES THE PROBLEM:**
- No region unscanned (eliminates hiding spot)
- Overlapping windows still performant
- Large payloads can't bypass patterns
- Defense in depth (Sentinel still catches escapes)

---

## Infrastructure Problems

### I-1: No Redis for Distributed State

**PROBLEM:**
In-memory sessions/rate-limiting:
- Sessions lost on pod restart
- Rate limits don't work across multiple instances
- User gets logged out when router restarts
- No shared cache for config/pod discovery
- Can't scale horizontally

**ACCEPTANCE CRITERIA:**
- [ ] Redis running and accessible
- [ ] `RedisSessionStore` implements TTL-based expiry
- [ ] `RedisRateLimiter` implements sliding window
- [ ] `RedisCache` for prompts/skills/agents
- [ ] Sessions survive router restart
- [ ] Rate limiting works across all instances
- [ ] Redis uses auth (--requirepass)
- [ ] Redis has TLS (production)
- [ ] Redis not exposed externally

**SOLUTION:**
Add Redis 7.4-alpine to docker-compose. Create `redis[hiredis]` dependency. Implement `RedisSessionStore`, `RedisRateLimiter`, `RedisCache` using `redis.asyncio`. Configure with AUTH and TLS in production.

**HOW THIS SOLVES THE PROBLEM:**
- Sessions persist across restarts
- Horizontal scaling possible (shared state)
- Rate limiting works across all instances
- Reduced database load (cached configs)
- Can implement distributed locks (for future features)

---

### I-2: Reactor Event System Not Started

**PROBLEM:**
Reactor created but no triggers registered:
- Events emitted but no handlers run
- No logging of lifecycle events
- No metrics emission
- No webhook triggers
- Can't audit when requests happen

**ACCEPTANCE CRITERIA:**
- [ ] `post_classify` event triggers handler
- [ ] `pre_agent` event triggers handler
- [ ] `post_response` event triggers handler
- [ ] Handlers emit metrics/logs
- [ ] Handlers can trigger webhooks
- [ ] Reactor registration happens before app starts serving
- [ ] Events work in async context
- [ ] No startup errors

**SOLUTION:**
Register triggers in `container.py` after `reactor = Reactor()` and before agent creation. Implement handlers that log, emit metrics, call webhooks. Start reactor before app.run().

**HOW THIS SOLVES THE PROBLEM:**
- All lifecycle events captured
- Observability (metrics, logs, traces)
- Extensible (add handlers without core changes)
- Audit trail of all operations

---

## Dependency Graph

```
Must Complete First:
- S-1 (JWT) → S-2 (Privileged) → S-3 (Kubeconfig) → S-4 (API Keys) → S-5 (Postgres)
- I-1 (Redis) → I-2 (Reactor)

Architecture Chain:
- P-1 (Protocol) → P-2 (Discovery) → P-3 (Spawner) → P-4 (Runtime) → P-5 (Config) → P-6 (Warm Pool) → P-7 (K8s)
- P-8 (Circuit Breaker) → P-2 (Discovery)
- P-6 (Warm Pool) → I-1 (Redis)
- I-1 (Redis) → P-2 (Discovery)
- I-1 (Redis) → P-5 (Config)
```

---

## Test Strategy

For each acceptance criteria, verify:

1. **Unit Tests**: Test in isolation (mock Redis, K8s)
2. **Integration Tests**: Test with real Redis, K8s (Kind cluster)
3. **Manual Tests**: Verify in running system
4. **Load Tests**: Verify performance under 100 concurrent requests
5. **Security Tests**: Adversarial probes for each fix

---

## Success Metrics

| Metric | Target |
|---------|--------|
| Pod discovery latency (cache hit) | <5ms |
| Pod discovery latency (cache miss) | <50ms |
| Pod cold start time | <5s |
| Pod warm assignment rate | >95% |
| Request latency (user with pod) | <100ms (excluding LLM) |
| Circuit breaker detection time | 3 failures |
| Token validation time | <10ms |
| Redis session persistence | 100% on restart |
| Warden scan accuracy | >95% on test set |
