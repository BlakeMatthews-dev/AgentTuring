# ADR-K8S-001 — Namespace topology

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

Stronghold is a multi-tenant agent governance platform. Per ARCHITECTURE.md §9,
the runtime components are:

- Gateway (LiteLLM model proxy + tool policy)
- Stronghold API (FastAPI, the main application)
- MCP servers (one Deployment per tool backend: GitHub, dev-tools, filesystem, …)
- Postgres + pgvector (memory, traces, state)
- Phoenix (trace storage and dashboards)
- Warden + Sentinel (in-process security layers, v0.9)
- Optional containerized agent strategies

Multiple tenants must be isolated from each other AND from shared platform
infrastructure. We need to decide how to map these components onto Kubernetes
namespaces.

Constraints we must satisfy:

- **Blast radius** — a compromise of one component must not give direct access to
  the others (especially the database).
- **RBAC scope** — ServiceAccount permissions should be local to the smallest
  namespace that works.
- **Operator authorization** — humans (oncall, security, tenant admin) need
  clear, distinct scopes.
- **Backup boundaries** — Velero schedules and retention apply per namespace, so
  the namespace layout determines our backup tiers.
- **Network boundaries** — NetworkPolicy is naturally namespace-scoped.
- **ResourceQuota / LimitRange** — apply per namespace; cost attribution and
  cap enforcement want a meaningful unit.
- **Multi-tenant goal** — per-tenant isolation must be enforceable from v1.3 on
  without restructuring the platform.

## Decision

We will use **four namespace classes plus one platform-system namespace**:

1. **`stronghold-platform`** — shared platform infrastructure
   - Components: gateway (LiteLLM), Stronghold API, Phoenix
   - Shared across all tenants
   - Operated by the Stronghold platform team
   - Backed up daily, standard retention

2. **`stronghold-data`** — persistent data services
   - Components: Postgres + pgvector StatefulSet
   - Separated from `stronghold-platform` so an API-tier compromise has no direct
     network path to the database pod
   - Backed up daily, longer retention than platform (PITR-capable when v1.0
     external Postgres ships — see ADR-K8S-010)
   - RBAC: only the `stronghold-api` ServiceAccount may read/write

3. **`stronghold-mcp`** — MCP server deployments
   - Components: one Deployment per tool backend (github, dev-tools, filesystem,
     plus any future MCP servers)
   - The `mcp-deployer-sidecar` ServiceAccount is RBAC-scoped to this namespace
     only — this is the resolution of BACKLOG R3 (cluster-admin in main pod)
   - NetworkPolicy: ingress only from `stronghold-platform`, egress only to
     each MCP server's assigned backend (see ADR-K8S-004)

4. **`stronghold-tenant-<id>`** — per-tenant workloads (one namespace per tenant)
   - Components: tenant-specific Deployments, ConfigMaps, Secrets, Routes
   - Per-tenant ResourceQuota and LimitRange
   - NetworkPolicy denies cross-tenant ingress; allows ingress only from
     `stronghold-platform`
   - Sealed-secrets keypair scoped to this namespace (separate from prod's)
   - **v0.9 ships with the four-class design and zero tenant namespaces.**
     v1.3 introduces the first tenant namespaces (see ADR-K8S-008).

Plus one auxiliary cluster-services namespace:

5. **`stronghold-system`** — cluster-wide platform support
   - Components: cert-manager, sealed-secrets controller, OADP/Velero, monitoring
   - Higher privilege than the workload namespaces, but isolated from any
     Stronghold workload
   - Operated by the platform team only

## Alternatives considered

**A) Single namespace** — everything in one `stronghold` namespace, which is the
current state of the prior single-node Kubernetes deployment.

- Rejected: no blast-radius isolation. A compromised MCP server has direct
  network reach to Postgres. NetworkPolicy on labels alone is fragile and easy
  to misconfigure. ResourceQuota becomes meaningless because all components
  share the same pool.

**B) Per-component namespace** — one namespace per service.

- Rejected: too much overhead. ResourceQuota and RBAC become noise. Operators
  need elevated permissions across many namespaces routinely. The granularity
  exceeds the trust-boundary granularity we actually care about.

**C) Per-tenant only, no shared platform namespace** — duplicate gateway and
tracing per tenant.

- Rejected: forces duplication of LiteLLM, Phoenix, and Postgres per tenant.
  Costly in resources and licenses. Conflicts with Stronghold's intended sharing
  model where the gateway and tracing are shared infrastructure with per-tenant
  RBAC inside.

**D) Single namespace with pod-level isolation via labels** — keep the
single-namespace shape but rely on label-based NetworkPolicies and ResourceQuota
scoped via PriorityClass.

- Rejected: namespace is the cleanest Kubernetes primitive for trust boundaries.
  Label-based isolation is fragile, easy to break with a typo, and doesn't give
  operators the clean `oc project <name>` workflow.

## Consequences

**Positive:**

- Each namespace is a clear trust boundary; compromises are contained at the
  Kubernetes layer, not just at the application layer.
- Velero backup schedules and retention naturally align with risk class
  (`stronghold-data` gets the strongest retention, `stronghold-mcp` gets the
  weakest).
- ResourceQuota per namespace gives natural cost attribution as multi-tenant
  ships in v1.3.
- RBAC roles are local and easy to audit — `oc adm policy who-can <verb>
  <resource>` on a tenant namespace returns only the relevant SAs.
- The multi-tenant story (v1.3) drops in cleanly by adding tenant namespaces
  without restructuring the platform layout.

**Negative:**

- More NetworkPolicy rules to maintain than a single-namespace design (mitigated
  by the decision matrix CSV in ADR-K8S-004).
- Cross-namespace service references must use FQDN
  (`postgres.stronghold-data.svc.cluster.local` rather than just `postgres`).
- Helm chart must template namespace assignment per resource via `_helpers.tpl`
  rather than relying on the `--namespace` install flag alone.
- Operators must `oc project <name>` more often during interactive debugging.

**Trade-offs accepted:**

- We accept slightly more operational complexity in exchange for hard,
  primitive-level isolation between API tier, data tier, MCP tier, and tenants.
- We accept that the platform team must understand the namespace layout before
  performing routine operations — this will be documented in `docs/dev/local-k8s.md`.

## References

- Kubernetes documentation: "Namespaces" — kubernetes.io/docs/concepts/overview/working-with-objects/namespaces/
- OpenShift Container Platform 4.14 documentation: "Working with projects"
- NIST SP 800-190 "Application Container Security Guide" §4.1.2 (namespace isolation)
- CIS Kubernetes Benchmark v1.9.0 §5.7.1 (namespace separation)
- Kubernetes SIG Multi-tenancy: "Multi-tenancy primitives"
