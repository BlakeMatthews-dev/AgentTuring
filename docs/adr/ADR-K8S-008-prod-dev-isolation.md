# ADR-K8S-008 — Prod / dev isolation rules on a shared cluster

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

The Stronghold homelab cluster (see ADR-K8S-006) is a single Kubernetes
cluster that hosts both:

- The production Stronghold instance (`stronghold-prod` namespace)
- Per-branch development deployments (`stronghold-dev-<branch>` namespaces)

Sharing one cluster between prod and dev is intentional: it cuts ops cost
and matches the multi-tenant pattern Stronghold itself targets, so we
dogfood our own design. But sharing also creates a real risk: a runaway
agent loop in a dev branch must not be able to OOM-kill prod, exhaust
prod's database connections, or read prod's secrets.

We need an explicit set of isolation rules that make "dev branch cannot
hurt prod" a structural property of the cluster, not a matter of operator
discipline.

## Decision

We adopt **eight non-negotiable isolation rules** for any Stronghold
deployment that shares a cluster with the production deployment. The chart's
`values-prod-homelab.yaml` and `values-dev-branch.yaml` enforce these by
construction; CI checks the rendered manifests for compliance.

### The eight non-negotiables

1. **Separate Postgres StatefulSets per namespace.** Prod has its own
   StatefulSet in `stronghold-data` (or wherever the prod values place it).
   Each dev branch gets its own StatefulSet in `stronghold-dev-<branch>`.
   Different credentials, different PVCs, different StorageClasses are
   acceptable. **No shared database between prod and dev under any
   circumstances.** A SQL injection in a dev branch must not be able to
   reach prod data.

2. **NetworkPolicy denies all ingress to `stronghold-prod` from any
   `stronghold-dev-*` namespace.** The default-deny baseline (ADR-K8S-004)
   handles this implicitly, but we add an explicit `deny-from-dev-namespaces`
   policy as belt-and-braces. Egress from prod to dev is also denied — prod
   has no business reaching into a dev branch.

3. **ResourceQuota on every namespace.** Prod gets the larger slice. Dev
   branches are capped so a runaway pod loop in a dev branch cannot
   over-allocate the node. Default v0.9 values:
   - `stronghold-prod`: 8 CPU, 16Gi RAM, 50Gi storage, 30 pods
   - `stronghold-dev-<branch>`: 4 CPU, 8Gi RAM, 20Gi storage, 15 pods
   - These are starting points; tunable per `values.yaml`.

4. **PriorityClass split: prod is high, dev is low.** Prod pods get a
   PriorityClass at the top of the user range (`stronghold-prod-critical`,
   value 1000000). Dev pods get a PriorityClass at the bottom
   (`stronghold-dev-low`, value 100). If the node ever runs out of memory
   under pressure, the kubelet evicts dev pods first. Prod stays up.

5. **PodDisruptionBudget on prod.** The prod `stronghold-api` Deployment
   has a `PodDisruptionBudget` with `minAvailable: 1`. Voluntary disruptions
   (drains, node maintenance, dev pod chaos) cannot take prod offline. Dev
   pods do not get PDBs — they're expendable by design.

6. **Separate StorageClasses for prod and dev (or quota-controlled
   shared).** On the homelab, prod PVCs use a StorageClass backed by NVMe
   (`local-path-nvme-prod`); dev PVCs use a separate StorageClass
   (`local-path-nvme-dev`) on the same physical disk but with a separate
   storage quota allocation in the namespace ResourceQuota. Alternatively,
   dev can be moved to slower storage (`local-path-bulk` on HDD) if disk
   contention becomes a problem.

7. **Separate sealed-secrets keypairs for prod and dev.** The
   `stronghold-prod` namespace has its own sealed-secrets controller key
   (or its own ESO ClusterSecretStore, or its own Vault namespace —
   depends on the secrets backend per ADR-K8S-003). A compromise of a
   dev branch's secret store cannot decrypt prod secrets.

8. **Velero backups schedule prod only.** Prod's namespace is included in
   the daily `velero schedule` with 30-day retention. Dev branches are
   not backed up — they are by definition reproducible from git. Saving
   storage and PBS bandwidth.

### Auto-TTL on dev branches

Dev branches are ephemeral by design. A namespace older than **7 days
since last commit on its source branch** is auto-deleted by a CronJob in
`stronghold-system` (`stronghold-dev-namespace-reaper`). The CronJob:

- Lists all `stronghold-dev-*` namespaces
- For each, reads the `stronghold.io/source-branch` and
  `stronghold.io/source-commit-date` labels
- Deletes any namespace whose source-commit-date is more than 7 days ago
- Posts a notification to a Slack channel (if configured) before deletion

The TTL is overridable per-namespace by setting
`stronghold.io/ttl-override: <RFC3339 timestamp>`.

### Operator workflow

Creating a dev branch namespace:

```
helm install stronghold-dev-feat-foo \
  deploy/helm/stronghold \
  --namespace stronghold-dev-feat-foo \
  --create-namespace \
  -f deploy/helm/stronghold/values-dev-branch.yaml \
  --set tenancy.devBranch.name=feat-foo \
  --set tenancy.devBranch.sourceCommitDate=2026-04-07
```

Deleting it:

```
helm uninstall stronghold-dev-feat-foo --namespace stronghold-dev-feat-foo
oc delete namespace stronghold-dev-feat-foo
```

(Or wait 7 days and let the reaper handle it.)

## Alternatives considered

**A) Separate clusters for prod and dev.**

- Rejected: doubles the ops surface for a single-operator homelab. Two
  clusters means two upgrade cycles, two CNI installs, two cert-manager
  installs, two backup pipelines. The benefit (cluster-level isolation)
  is real but smaller than the cost. Namespace-level isolation with the
  eight rules is sufficient.

**B) Shared Postgres with per-branch schemas.**

- Rejected: violates Rule 1. A SQL injection bug in a dev branch could
  reach prod data. Per-namespace StatefulSets is the only safe answer.

**C) No ResourceQuota on dev branches; trust developers not to oversubscribe.**

- Rejected: a runaway agent loop is the most likely failure mode of a
  dev branch (Stronghold IS an agent platform, so dev branches are
  literally agents under development). Trusting developers means trusting
  agents, which is a bad bet for a security-focused product.

**D) PriorityClass on prod only; dev pods get the cluster default.**

- Rejected: Kubernetes' default PriorityClass is in the middle of the
  range. Prod-high alone doesn't help if dev competes at the same priority
  level — the eviction algorithm picks arbitrarily within a class. Dev-low
  is the symmetric pair to prod-high; both are needed.

**E) Use vcluster (virtual Kubernetes clusters inside a host cluster) for
each dev branch.**

- Rejected for v0.9: adds operational complexity for a problem that
  namespace-level isolation handles cleanly. vcluster is excellent when
  you have adversarial multi-tenancy with a need for kubectl access at the
  virtual-cluster level. We have one operator and the eight rules are
  enough. Worth revisiting if the dev workflow grows beyond a handful of
  branches.

## Consequences

**Positive:**

- "Dev branch cannot hurt prod" is structural, not procedural.
- The cluster lifecycle (one upgrade flow, one CNI, one cert-manager) is
  simple to operate.
- Stronghold dogfoods its own multi-tenant isolation primitives.
- Auto-TTL keeps dev branch sprawl manageable without operator chasing.

**Negative:**

- More YAML to write per branch (PriorityClass, ResourceQuota, NetworkPolicy
  references). Mitigated by `values-dev-branch.yaml` which sets all of them
  via a single helm install command.
- Per-branch Postgres StatefulSets cost storage. Mitigated by ResourceQuota
  caps and the 7-day auto-TTL.
- The reaper CronJob is one more thing to operate. Acceptable.

**Trade-offs accepted:**

- We accept storage cost for per-branch Postgres in exchange for hard
  isolation between prod and dev data.
- We accept TTL automation in exchange for not managing dev branches by
  hand.

## References

- Kubernetes documentation: "Resource Quotas"
- Kubernetes documentation: "Pod Priority and Preemption"
- Kubernetes documentation: "PodDisruptionBudget"
- Kubernetes documentation: "Network Policies"
- OpenShift Container Platform 4.14 documentation: "Setting up multi-tenancy"
- OpenShift Container Platform 4.14 documentation: "Configuring quotas across multiple projects"
- Velero documentation: "Schedule reference"
- ADR-K8S-001 (namespace topology), ADR-K8S-003 (secrets), ADR-K8S-004 (NetworkPolicy)
