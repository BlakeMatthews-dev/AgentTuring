# ADR-K8S-007 — Distro compatibility matrix

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

Stronghold is sold as a Helm chart that customers install on their own
Kubernetes cluster. The customer's cluster is not Stronghold's choice — it
is whatever distro and cloud their platform team has standardized on.
Stronghold's chart needs to run on a defined set of those environments
without surprises.

We chose OKD as the homelab reference deployment (ADR-K8S-006), which sets
the chart's primary design target. We now need to decide:

- Which distros do we explicitly validate every release? (Tier-1)
- Which distros do we promise best-effort compatibility but don't gate
  releases on? (Tier-2)
- Which distros are out of scope?
- What does "tested" mean for each tier?

## Decision

### Tier-1: validated every release (release-blocking)

These distros are tested before every release. A release cannot ship if any
Tier-1 distro fails the validation suite. Test coverage: helm install + smoke
+ NetworkPolicy enforcement + RBAC scope + multi-tenant isolation.

| Distro | Min version | Why Tier-1 |
|---|---|---|
| **OKD** | 4.14+ | Homelab reference deployment; primary design target |
| **OpenShift Container Platform (OCP)** | 4.14+ | Same code path as OKD; paid Red Hat customers |
| **Amazon EKS** | 1.29+ | Largest enterprise k8s footprint; most likely customer environment |
| **Google GKE** | 1.29+ | Second largest enterprise k8s footprint |
| **Azure AKS** | 1.29+ | Required for Microsoft-shop customers |

### Tier-2: best-effort, community-supported (not release-blocking)

These distros are not tested every release. We promise the chart should work
on them, and we accept community PRs to fix breakage, but we don't gate
releases on Tier-2 results.

| Distro | Min version | Notes |
|---|---|---|
| **Vanilla upstream Kubernetes (kubeadm)** | 1.29+ | Reference; if it works here it should work on Tier-1 distros too |
| **RKE2** | 1.29+ | SUSE / Rancher hardened upstream k8s; common on-prem in regulated industries |
| **k3s** | 1.29+ | Lightweight; common edge / single-node enterprise |
| **Rancher (managing any of the above)** | n/a | Pass-through; chart cares about the underlying cluster, not the management layer |

### Out of scope

- Kubernetes < 1.29 (older than ~18 months at v0.9 release)
- KEP-deprecated APIs (we use only stable v1 APIs)
- "Distroless k8s" experiments and research projects
- Embedded / IoT k8s variants (MicroShift, KubeEdge) — see ADR-K8S-012 for
  Stronghold's compatibility validation rationale
- Ephemeral CI Kubernetes runtimes as production targets (CI tools designed
  for throwaway clusters, not always-on production)

### Test surface per tier

**Tier-1 release validation suite** (runs before every release tag):

1. `helm lint` and `kubeconform -strict` against the rendered manifests
2. `helm install` with the appropriate values file:
   - OKD / OCP: `values-prod-homelab.yaml` (minus the homelab-specific
     hostnames)
   - EKS / GKE / AKS: `values-vanilla-k8s.yaml` plus a per-cloud overlay
     (`values-eks.yaml`, etc.)
3. Pod readiness check (`oc wait` / `kubectl wait`)
4. Smoke test: curl `/health` endpoints, exercise basic Stronghold API
5. NetworkPolicy enforcement test: probe pod from a separate namespace
   should fail to connect
6. RBAC scope test: `oc auth can-i` / `kubectl auth can-i` for the
   mcp-deployer-sidecar ServiceAccount
7. Persistence test: write data, restart the API pod, read data back
8. Multi-tenant test (v1.3+): two ephemeral tenant namespaces, verify
   cross-tenant traffic denied

**Tier-2 best-effort:** the chart's CI workflow runs `helm template` +
`kubeconform` against the vanilla-k8s values file on every PR. Real cluster
tests are not gated. If a Tier-2 user reports a regression, we triage as a
bug and accept community PRs.

### Per-cloud overlays (Tier-1)

Each Tier-1 cloud has a values overlay file that translates the chart's
abstract requirements into provider-specific resources:

- `values-eks.yaml` — IRSA service account annotations, EBS-CSI StorageClass,
  AWS ALB Ingress Controller annotations (if `openshift.enabled: false`)
- `values-gke.yaml` — Workload Identity service account annotations, GCE
  Persistent Disk StorageClass, GCE Ingress annotations
- `values-aks.yaml` — Azure AD Workload Identity annotations, Azure Disk CSI
  StorageClass, Azure Application Gateway annotations
- `values-okd.yaml` — Routes enabled, OpenShift Secrets, OperatorHub
  references for cert-manager / sealed-secrets / OADP

### Compatibility documentation

`docs/INSTALL.md` ships a per-distro quickstart for each Tier-1 distro,
including the values overlay to use, the prerequisites the customer needs
on their cluster (CNI with NetworkPolicy enforcement, ingress controller or
Route capability, supported StorageClass for ReadWriteOnce PVCs, secrets
backend), and the expected post-install verification steps.

## Alternatives considered

**A) OpenShift-only support.**

- Rejected: cuts the addressable market by ~80%. EKS and GKE customers are
  not going to switch to OpenShift to install Stronghold. The chart needs
  vanilla Kubernetes support as a first-class concern.

**B) Vanilla Kubernetes only — no OpenShift-specific support.**

- Rejected: enterprise governance customers run OpenShift heavily, and
  designing the chart for vanilla k8s only means it would silently fail on
  OpenShift's strict SCC defaults. Better to design OpenShift-first and add
  vanilla as a fallback than the reverse.

**C) "Whatever Kubernetes" — no compatibility matrix, customer's problem.**

- Rejected: enterprise buyers expect a compatibility matrix as part of the
  evaluation. "Tested with EKS, GKE, AKS, OCP" is a sales requirement, not
  a nice-to-have.

**D) Test only the homelab cluster (OKD), trust customer environments by
analogy.**

- Rejected: testing only OKD means Stronghold ships with OpenShift-specific
  bugs that vanilla k8s users will hit immediately. The vanilla-k8s render
  step in the per-PR validate workflow catches the easy cases; the
  release-gated EKS / OCP tests catch the harder ones.

**E) Test on every reasonable distro.**

- Rejected: cost. Real-cluster validation against five distros per release
  is already expensive (cloud cost, terraform spin-up time, debugging
  matrix). Six or seven would push us into "validation theatre" territory
  where the test takes longer than the engineering work.

## Consequences

**Positive:**

- Customers know exactly what we support before they evaluate.
- The Tier-1 validation suite catches the most common breakage classes
  before customers do.
- Sales can answer the "does it work on X?" question definitively for
  every Tier-1 distro.
- The chart's design discipline (OpenShift-first with vanilla fallback)
  produces a more portable artifact than "vanilla k8s and hope".

**Negative:**

- Five Tier-1 distros means five real-cluster validation runs per release.
  Cost: ~$50-150 in cloud spend per release for EKS / GKE / AKS spin-ups,
  plus ~30-45 minutes of validation wallclock per release.
- Per-cloud overlays mean five values files to maintain. Mitigated by
  keeping the overlays small (< 50 lines each) and using the base
  `values.yaml` for everything common.
- Tier-2 distros may regress between releases without our noticing.
  Acceptable: that's the point of the tier distinction.

**Trade-offs accepted:**

- Validation cost in exchange for a real compatibility promise.
- Per-cloud overlay maintenance in exchange for portability across all
  major clouds.

## References

- OpenShift Container Platform 4.14 documentation
- AWS EKS documentation: "Best practices for security, IAM, and networking"
- Google GKE documentation: "Workload Identity"
- Azure AKS documentation: "Azure AD workload identity"
- Kubernetes documentation: "Container Storage Interface (CSI)"
- CNCF Cloud Native Computing Foundation: "CNCF Landscape — Certified Kubernetes Distributions"
- Helm chart best practices: helm.sh/docs/chart_best_practices/
