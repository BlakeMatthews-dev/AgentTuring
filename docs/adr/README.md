# Stronghold Kubernetes ADRs

Architecture Decision Records for the Stronghold v0.9 Kubernetes
deployment. Each ADR captures a single decision, the context it was
made in, the alternatives considered, and the consequences accepted.

All ADRs in this index are currently **Proposed** unless noted
otherwise.

## Index

| # | Title | Summary |
|---|-------|---------|
| [001](ADR-K8S-001-namespace-topology.md) | Namespace topology | Four namespace classes (`stronghold-platform`, `stronghold-data`, `stronghold-mcp`, `stronghold-tenant-<id>`) plus a `stronghold-system` auxiliary, giving each trust boundary its own Kubernetes-primitive scope. |
| [002](ADR-K8S-002-rbac-boundary.md) | RBAC boundary | ServiceAccount and Role scopes are per-namespace, with the MCP deployer sidecar constrained to `stronghold-mcp` only. |
| [003](ADR-K8S-003-secrets-approach.md) | Secrets approach | Pluggable backend (`k8s` / `sealed-secrets` / `eso` / `vault`) with file-mount injection, explicit ban on env-var secrets, and four documented injection patterns. |
| [004](ADR-K8S-004-networkpolicy-posture.md) | NetworkPolicy posture | Default-deny baseline with an explicit decision-matrix CSV enumerating every allowed ingress/egress edge. |
| [005](ADR-K8S-005-warden-topology.md) | Warden topology | Warden and Sentinel run in-process inside `stronghold-api` for v0.9, with a documented lift-out plan for a later standalone deployment. |
| [006](ADR-K8S-006-runtime-okd.md) | Runtime selection: OKD single-node OpenShift | OKD SNO is the homelab reference runtime; the chart is OpenShift-first (Routes, SCCs, OperatorHub) with a vanilla-k8s fallback values file. |
| [007](ADR-K8S-007-distro-compatibility-matrix.md) | Distro compatibility matrix | Tier-1 distros are OKD/OCP; Tier-2 are k3s, RKE2, and managed cloud Kubernetes; the chart is validated on each tier at documented cadences. |
| [008](ADR-K8S-008-prod-dev-isolation.md) | Prod / dev isolation on a shared cluster | Eight non-negotiable isolation rules (separate Postgres, NetworkPolicy deny, ResourceQuota, PriorityClass split, PDBs, StorageClass split, sealed-secrets keypair split, Velero backups prod-only) plus a 7-day auto-TTL reaper for dev namespaces. |
| [009](ADR-K8S-009-migration-sequence.md) | Migration sequence | Rollout of v0.9 from the prior single-node runtime to OKD via a phased PR chain with a one-week soak and a rollback-at-every-step design. |
| [010](ADR-K8S-010-storage-pluggability.md) | Storage pluggability | StorageClass-pluggable design so the chart runs on local-path, NFS, CSI, and cloud-managed storage without forking. |
| [011](ADR-K8S-011-secrets-provider-pluggability.md) | Secrets provider pluggability | Detailed Helm-template plumbing for the four secrets backends from ADR-003, including per-tenant keypair scoping. |
| [012](ADR-K8S-012-crc-sandbox.md) | CRC compatibility sandbox | On-demand Code-Ready Containers VM for running the full OpenShift surface against the chart in validation. |
| [013](ADR-K8S-013-hybrid-execution-model.md) | Hybrid execution model | Two execution surfaces: conversational (in-process, sub-second) and agentic (per-mission pods, minutes-to-hours), sharing a single control plane and data plane with Conduit as the routing boundary. |
| [014](ADR-K8S-014-six-tier-priority-system.md) | Six-tier priority system (P0-P5) | Cross-cutting `priority_tier` label spanning routing weight, Kubernetes scheduling, token budgets, quota, observability, and eviction, from P0 chat-critical down to P5 builders. |
| [015](ADR-K8S-015-priority-tier-eviction-order.md) | PriorityClass numeric values and eviction order | Concrete numeric values (1_000_000 down to 100_000, spaced by 200_000) for the six PriorityClasses, with the eviction rationale and an observational verification procedure. |
| [016](ADR-K8S-016-gitops-controller.md) | GitOps controller: OpenShift GitOps | OpenShift GitOps Operator (Red Hat-packaged Argo CD) tracks the Stronghold chart with manual sync, `selfHeal: false`, and `prune: false` so drift is visible but never auto-corrected. |
| [017](ADR-K8S-017-architecture-diagram-pipeline.md) | Architecture diagram pipeline | Two tracks: generated-from-chart SVGs (accuracy, CI-gated) and hand-authored D2 sources (narrative), both rendered by a single `make diagrams` target. |

## Reading order for new contributors

If you are new to the Stronghold Kubernetes deployment, read in this
order:

1. **006 (runtime)** — sets the platform assumptions everything else
   builds on.
2. **001 (namespaces)** and **002 (RBAC)** — the trust boundaries.
3. **004 (NetworkPolicy)** and **003 (secrets)** — how those
   boundaries are enforced.
4. **013 (hybrid execution)** — the two surfaces the chart serves.
5. **014 (priority tiers)** and **015 (eviction order)** — how the
   platform decides who gets resources under contention.
6. **008 (prod/dev isolation)** — how one cluster can hold both
   without crosstalk.
7. **016 (GitOps)** — how cluster state is reconciled against the
   chart.
8. The remaining ADRs in any order as needed.

## Status legend

- **Proposed** — the decision has been made and documented but has
  not yet been fully implemented in the chart.
- **Accepted** — the decision is implemented and the chart conforms.
- **Superseded by ADR-K8S-NNN** — the decision has been replaced by a
  later ADR; the old ADR is kept for history.
- **Deprecated** — the decision no longer applies but nothing has
  replaced it.
