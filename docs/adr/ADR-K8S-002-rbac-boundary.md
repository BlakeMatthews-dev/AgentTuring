# ADR-K8S-002 — RBAC boundary

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

Stronghold runs as a multi-component Kubernetes workload (see ADR-K8S-001 for
the namespace layout). Each component needs Kubernetes API permissions to do
its job: the MCP deployer creates Deployments and Services, cert-manager mints
certificates, the main API reads ConfigMaps, and so on. The current state of
the prior single-node deployment grants the main app pod a kubeconfig with
**cluster-admin** privileges (BACKLOG R3) — the worst possible RBAC posture.

We need a default RBAC boundary policy that:

- Gives every component the minimum permissions it needs and nothing more
- Makes "what can this component do" auditable in a single command
- Survives the reader-friendliness test: a new operator should be able to read
  one Role manifest and understand exactly what one ServiceAccount can do
- Composes cleanly with OpenShift's SecurityContextConstraints (SCCs) layer
- Maps to common compliance controls (SOC2 CC6.1, ISO 27001 A.9.4.1)

## Decision

We will adopt **per-component ServiceAccounts with namespace-scoped Roles**:

1. **One ServiceAccount per Stronghold component**, named after the component:
   - `stronghold-api` — main FastAPI app
   - `mcp-deployer-sidecar` — sidecar that creates MCP Deployments (R3 fix)
   - `litellm` — gateway
   - `phoenix` — tracing
   - `postgres` — database StatefulSet
   - `mcp-<backend>` — one per MCP server (github, dev-tools, filesystem, …)
   - `cert-manager`, `sealed-secrets`, `velero` — installed by the OperatorHub
     operators in `stronghold-system` namespace

2. **All Roles are namespace-scoped Roles, not ClusterRoles**, except for the
   tightly-controlled set of ClusterRoles required for cluster-scoped resources:
   - `stronghold-priorityclass-reader` — read PriorityClass (cluster-scoped)
   - `stronghold-storageclass-reader` — read StorageClass (cluster-scoped)
   - `stronghold-namespace-creator` — used only by Helm install/upgrade hooks
     to create the four namespace classes; bound to a dedicated installer SA,
     never to a workload SA

3. **Verbs are explicit allowlists**, never wildcards. Each Role lists the
   specific verbs (`get`, `list`, `watch`, `create`, `patch`, `delete`) on
   specific resources (`deployments`, `services`, `configmaps`, etc.). No
   `verbs: ["*"]`. No `resources: ["*"]`.

4. **The mcp-deployer-sidecar's Role is the strictest case** because it's the
   resolution of BACKLOG R3:
   - Bound only in the `stronghold-mcp` namespace
   - Verbs: `get, list, watch, create, patch, delete`
   - Resources: `deployments, services, configmaps, secrets,
     routes.route.openshift.io`
   - Explicitly cannot touch `nodes`, `clusterroles`, `clusterrolebindings`,
     `customresourcedefinitions`, or anything in `kube-system` /
     `openshift-*` namespaces
   - On OpenShift, the SA is bound to the `restricted-v2` SCC explicitly
     (not `anyuid`, not `privileged`)

5. **No ServiceAccount uses the cluster default `default` SA.** Every workload
   pod sets `serviceAccountName: <component>` explicitly in its Deployment spec.
   Helm `_helpers.tpl` provides a `stronghold.serviceAccountName` template that
   computes the right name from the chart values.

6. **Audit aid**: every Role and RoleBinding manifest carries the label
   `stronghold.io/rbac-tier: <component>` so operators can run
   `oc get role,rolebinding -A -l stronghold.io/rbac-tier=mcp-deployer` to see
   the entire authorization surface for one component in one command.

## Alternatives considered

**A) Shared ServiceAccount across multiple components.**

- Rejected: defeats the audit story. "Why does the SA `stronghold-shared` need
  to create Routes?" becomes unanswerable when five components share it.

**B) ClusterRoles bound per-namespace via RoleBindings.**

- Rejected: ClusterRoles are templates that span the cluster. Even when bound
  via a namespace-scoped RoleBinding, their definitions live cluster-wide,
  which makes "what does this role allow" harder to scan and creates a single
  point of compromise. Use namespace-scoped Roles whenever the resources are
  also namespace-scoped.

**C) Aggregated ClusterRoles (Kubernetes feature where labels merge multiple
ClusterRoles into one).**

- Rejected: too clever for our scale. Useful for platform vendors shipping
  reusable RBAC libraries (Velero does this), but adds debugging complexity for
  application workloads.

**D) Single `stronghold-app` ServiceAccount with broader permissions, and rely
on application-layer authz inside Stronghold to scope what each subsystem can
actually do.**

- Rejected: pushes security enforcement out of Kubernetes and into application
  code. A bug in Stronghold's authz layer would be a Kubernetes-level breach.
  Defense in depth requires the Kubernetes RBAC layer to be the first
  enforcement boundary, not the last.

## Consequences

**Positive:**

- Compliance mapping is straightforward: each Role manifest maps directly to a
  SOC2 CC6.1 control statement.
- A breach of one component cannot escalate via Kubernetes API access.
- `oc auth can-i` returns honest answers when operators investigate.
- BACKLOG R3 closes cleanly: the MCP deployer sidecar's namespace-scoped Role
  cannot do anything outside `stronghold-mcp`, making the prior cluster-admin
  kubeconfig grant strictly impossible.

**Negative:**

- More YAML to maintain than a single shared SA. Mitigated by Helm templates
  that generate the per-component RBAC from a single list in `values.yaml`.
- Some debugging requires `oc auth can-i --as=system:serviceaccount:...`
  invocations to figure out what a sidecar can do — slightly more friction
  than `oc get` from a cluster-admin user.

**Trade-offs accepted:**

- We accept template complexity in the Helm chart in exchange for least-
  privilege defaults. The template complexity is a one-time cost; the
  least-privilege posture is a permanent benefit.

## References

- Kubernetes documentation: "Using RBAC Authorization" — kubernetes.io/docs/reference/access-authn-authz/rbac/
- Kubernetes documentation: "Configure Service Accounts for Pods"
- OpenShift Container Platform 4.14 documentation: "Using RBAC to define and apply permissions"
- OpenShift Container Platform 4.14 documentation: "Managing Security Context Constraints"
- NIST SP 800-204 §4.3 (RBAC for microservices)
- CIS Kubernetes Benchmark v1.9.0 §5.1 (RBAC and Service Accounts)
- SOC2 Trust Services Criteria CC6.1 — "logical access controls"
- ISO/IEC 27001:2022 A.5.15 (access control)
