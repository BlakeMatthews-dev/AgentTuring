# ADR-K8S-006 — Runtime selection: OKD single-node OpenShift

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

Stronghold's Phase 9 (v0.9) ships a Kubernetes deployment as the production
target. ARCHITECTURE.md §9 describes the workload — gateway, API, MCP servers,
Postgres, tracing — but does not pin a specific Kubernetes runtime. We need
to choose one for the homelab reference deployment, and that choice shapes
several downstream design decisions:

- Which CNI we get by default and whether NetworkPolicy enforcement is
  guaranteed
- Whether the chart needs OpenShift-specific resources (Routes, SCCs) or
  vanilla Kubernetes only (Ingress, PodSecurityAdmission)
- Which security defaults the platform forces vs. which we have to layer on
- The audit and compliance posture our chart inherits from the platform
- The development and operations workflow for the engineer running the
  homelab cluster
- How portable the chart is to enterprise customer environments

The current state of the prior single-node deployment runs on a CI-grade
Kubernetes runtime that lacks production-shaped guarantees: its default CNI
silently no-ops NetworkPolicy, its storage is ephemeral hostPath inside a
container, and upgrades require recreating the cluster. This is not a
production runtime — it is a CI tool that has been pressed into a production
role, with predictable consequences.

Stronghold's market is enterprise multi-tenant agent governance. Our buyers
run regulated workloads on hardened Kubernetes — most commonly EKS, GKE, AKS,
or OpenShift. The runtime we choose for the homelab reference deployment
should be one whose security defaults and operational patterns prepare the
chart to ship cleanly to those environments.

## Decision

**The Stronghold homelab reference deployment runs on OKD single-node
OpenShift (SNO).** OKD is the upstream community distribution of OpenShift,
Apache 2.0 licensed, fully open, with no Red Hat subscription required.

The chart is designed **OpenShift-first**: Routes for external exposure,
SecurityContextConstraints for pod security, the OperatorHub model for
platform components (cert-manager, sealed-secrets, OADP). Vanilla Kubernetes
support exists as a fallback (`values-vanilla-k8s.yaml`) for customers on
EKS / GKE / AKS without OpenShift, gated by `.Values.openshift.enabled`.

### Rationale

1. **Strict SecurityContextConstraints force correct security defaults from
   day one.** OpenShift's `restricted-v2` SCC is the default for new
   ServiceAccounts and rejects: `runAsUser: 0`, `privileged: true`,
   `hostPath` volumes, `hostNetwork`, `hostPID`, and most Linux capabilities.
   A chart that runs on OKD's restricted-v2 SCC is by construction free of
   the most common Kubernetes security antipatterns. The platform catches
   our mistakes before customers do.

2. **Routes + ImageStreams + OperatorHub match enterprise customer
   environments.** Most large-enterprise Kubernetes runs OpenShift Container
   Platform. Designing the chart for Routes and SCCs first means it works on
   OCP without modification. The vanilla-k8s fallback values are the smaller
   adaptation, not the larger one.

3. **Same code path as paid OpenShift Container Platform.** OKD is upstream
   OCP — same operators, same APIs, same SCCs, same Routes. If a Stronghold
   customer wants paid Red Hat support, they install OCP with the same chart
   and the same `values-prod-homelab.yaml` (modulo a few hostnames). No
   architectural changes.

4. **Apache 2.0 community licensing.** No Red Hat subscription required for
   the homelab. No pull-secret renewal cycle. No license cost. Fully open.

5. **A chart that ships clean on OKD's restricted-v2 SCC ships clean on
   EKS, GKE, AKS, and vanilla Kubernetes by construction.** The strictness
   gradient runs from "vanilla k8s with PodSecurityAdmission `restricted`
   profile" up through "OpenShift restricted-v2 SCC" — anything that passes
   the latter passes the former. The reverse is not true.

6. **OperatorHub eliminates Helm wrangling for platform infrastructure.**
   cert-manager, sealed-secrets, OADP/Velero, monitoring stack — each
   installs with two clicks via OperatorHub on OKD, with operator-managed
   upgrades. We maintain less Helm-of-Helms machinery for things that aren't
   Stronghold itself.

7. **OVN-Kubernetes is the default CNI on OKD 4.x and enforces
   NetworkPolicy.** No CNI swap dance. The pre-install enforcement check in
   ADR-K8S-004 passes on day one.

### What this commits us to

- The chart's primary target is OpenShift. Routes, SCC bindings, and
  OperatorHub assumptions are first-class.
- The vanilla-k8s fallback is a tested path (covered in
  `values-vanilla-k8s.yaml` and the per-PR validate workflow), but it is the
  secondary code path, not the primary.
- The homelab cluster is a real Kubernetes runtime, not a CI tool. Cluster
  upgrades follow OKD's upgrade flow (every 4-6 months, ~30 min, mostly
  automated).
- The engineer running the homelab learns OpenShift conventions (`oc` CLI,
  Routes vs Ingress, SCCs, OperatorHub) — this is desirable, since those
  same conventions apply to most of our future enterprise customers.

## Alternatives considered

**A) Continue running on the prior CI-grade single-node runtime.**

- Rejected: not designed for always-on production. Default CNI silently
  fails to enforce NetworkPolicy (verified). Storage is hostPath inside a
  container. Upgrades require cluster recreation. We cannot ship the
  Stronghold v0.9 NetworkPolicy work on a runtime that ignores it.

**B) k3s on a dedicated VM.**

- Rejected as the homelab reference, but acceptable as a Tier-2 supported
  distro for customers. Reasoning: k3s is a fine production runtime, but
  using it in the homelab means we never test against the OpenShift surface
  (SCCs, Routes, OperatorHub) that our enterprise customers will hit. We'd
  ship a chart that works on k3s and breaks on OpenShift, and discover the
  break only when a customer reports it. The whole point of the homelab is
  to be the early-warning system for chart compatibility issues.

**C) RKE2 on a dedicated VM.**

- Rejected as the homelab reference for the same reason as k3s: it's an
  excellent production runtime (CIS-hardened defaults, Canal CNI for
  NetworkPolicy enforcement, real upstream Kubernetes), but it does not
  catch OpenShift-specific issues. RKE2 is a strong Tier-1 distro for the
  customer compatibility matrix (ADR-K8S-007), just not the primary
  reference target.

**D) Paid OpenShift Container Platform (OCP).**

- Rejected for the homelab: requires a Red Hat subscription, which adds a
  recurring cost and a renewal cycle for no functional benefit over OKD on
  a self-supported deployment. OCP and OKD share the same code path, the
  same APIs, the same operators. The differences are: support contract
  (Red Hat handles incidents), curated update channels (OCP gets slower
  more-tested updates; OKD gets faster less-tested ones), and the pull
  secret. None of those differences matter for a homelab single-operator
  deployment. We document OCP as a Tier-1 supported customer distro in
  ADR-K8S-007, just not the homelab choice.

**E) MicroShift (edge-stripped OpenShift) for the homelab and full CRC for
compatibility validation.**

- Rejected: MicroShift drops the Web Console, OperatorHub, ImageStreams,
  and Builds — the very surface we need to test against to validate
  compatibility with full OpenShift. We want the homelab to be
  representative of the customer environment, not a stripped-down
  approximation. MicroShift is appropriate for edge / IoT use cases, not
  for homelab reference deployments. (See ADR-K8S-012 for the related
  decision on the on-demand sandbox VM, which uses full CRC for the same
  reason.)

**F) A managed cloud cluster (EKS / GKE / AKS) for the reference
deployment.**

- Rejected for the homelab: ongoing cloud cost for what is fundamentally a
  development and dogfooding cluster. Cloud is appropriate for customer
  pre-release validation (a release-gated terraform spin-up of EKS or AKS,
  documented in the v1.0+ roadmap) but not for the always-on reference.

## Consequences

**Positive:**

- The chart is forced to handle OpenShift-specific concerns from day one,
  catching SCC and Route issues before customers do.
- NetworkPolicy enforcement works out of the box (OVN-Kubernetes default).
- OperatorHub eliminates Helm wrangling for platform components.
- Same code path as paid OCP — customers can switch to OCP with a support
  contract without architectural changes.
- The engineer running the homelab develops OpenShift muscle memory that
  transfers to most enterprise customer environments.
- Apache 2.0 community license — no subscription, no pull-secret renewal,
  no recurring cost.

**Negative:**

- OKD is heavier than k3s or RKE2: ~16GB RAM minimum for the SNO node,
  ~50GB disk, slower upgrades (~30 min vs ~5 min for k3s), and more
  cluster operators to monitor. Acceptable on the homelab hardware (i9-
  13900K / 128GB RAM has plenty of headroom).
- Operators learning curve: `oc` CLI, Routes vs Ingress, SCCs, OperatorHub
  workflow. Acceptable: this is the same learning curve enterprise
  customers face, and we want to share their experience.
- The chart's vanilla-k8s fallback is a second code path with its own test
  matrix. Mitigated by the per-PR validate workflow that renders both
  values files and runs kubeconform on each.
- Customers who run k3s or RKE2 are Tier-2 supported, which means a smaller
  set of pre-release validation tests run against those distros.

**Trade-offs accepted:**

- We accept higher resource usage and a steeper learning curve in exchange
  for catching enterprise compatibility issues in the homelab instead of
  in customer support tickets.
- We accept dual code paths in the chart (OpenShift and vanilla) in
  exchange for portability.

## References

- OpenShift Container Platform 4.14 documentation: "Architecture"
- OpenShift Container Platform 4.14 documentation: "Managing Security Context Constraints"
- OpenShift Container Platform 4.14 documentation: "Configuring Routes"
- OpenShift Container Platform 4.14 documentation: "Single-node OpenShift cluster install"
- OKD project documentation — okd.io
- OVN-Kubernetes documentation
- Red Hat: "OpenShift vs Kubernetes" (comparison of base k8s with OpenShift additions)
- NIST SP 800-190 (Application Container Security Guide)
- CIS Kubernetes Benchmark v1.9.0
- CIS Red Hat OpenShift Container Platform Benchmark v1.5.0
