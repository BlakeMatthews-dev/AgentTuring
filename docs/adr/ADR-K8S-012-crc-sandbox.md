# ADR-K8S-012 — CRC sandbox over edge-stripped variants

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

ADR-K8S-006 commits the homelab production runtime to OKD single-node
OpenShift. We also want a separate, throwaway sandbox environment for:

- Validating chart compatibility against fresh OpenShift versions before
  upgrading the prod cluster
- Learning OpenShift-specific features (Operator development, Build
  pipelines, ImageStreams) without risking the prod cluster
- Reproducing customer issues on a clean cluster
- Practicing destructive operations (delete the cluster, recreate from
  scratch) without affecting prod

OpenShift offers several "small footprint" variants for this purpose:

1. **OpenShift Local (CRC)** — single-node OpenShift in a VM, includes
   the full Web Console, OperatorHub, ImageStreams, Builds, Routes
2. **MicroShift** — edge / IoT focused variant, strips the Web Console,
   OperatorHub, ImageStreams, Builds; keeps SCCs, NetworkPolicy, core
   k8s APIs, and basic OpenShift APIs
3. **Single-Node OpenShift (SNO)** — full OpenShift on a single node,
   identical to multi-node OpenShift in capability; this is what the
   homelab prod cluster runs

The choice between CRC and MicroShift for the sandbox affects what we
can validate. We need to decide which one fits our purpose.

## Decision

**The Stronghold sandbox VM runs full OpenShift Local (CRC), not
MicroShift.** The sandbox VM (`stronghold-crc`, VMID 108) lives on the
homelab host, stays stopped except when actively in use, and exposes the
complete OpenShift surface for compatibility validation.

### Rationale

1. **We must test against the surface our customers use.** Most enterprise
   OpenShift customers run full OCP with the Web Console, OperatorHub,
   ImageStreams, Routes, and Builds. A sandbox that strips those out
   cannot validate that Stronghold's chart works with them. MicroShift's
   strip list directly removes the things we need to test.

2. **Routes are first-class in our chart design.** ADR-K8S-006 commits to
   OpenShift-first design with Routes for external exposure. MicroShift
   includes Route support, so this isn't a hard blocker, but the
   downstream operator workflow (`oc expose service`, certificate
   automation via cert-manager Operator, edge TLS termination) depends on
   the full Web Console and Operator surface that MicroShift drops.

3. **OperatorHub is the chart's recommended path for cert-manager,
   sealed-secrets, and OADP.** ADR-K8S-006 specifically calls out
   OperatorHub as a reason to choose OpenShift. A sandbox that does not
   have OperatorHub cannot validate the OperatorHub-based install path.

4. **The hardware can afford it.** CRC requires ~16GB RAM, 4 vCPU, 50GB
   disk. The homelab host has 128GB RAM and 24 cores; the sandbox VM is
   stopped most of the time anyway. The resource cost is irrelevant.

5. **CRC is a Red Hat product, free with a developer account.** We need
   to register for a Red Hat developer account to get the pull secret
   (one-time, no cost, no subscription). This is acceptable. CRC's
   `crc setup` and `crc start` workflow is well-documented and stable.

6. **OKD vs CRC version skew matters.** CRC tracks OpenShift Container
   Platform releases closely, so it gets new versions before OKD does.
   This is actually useful: the sandbox can validate Stronghold's chart
   against a newer OpenShift version before the homelab prod cluster
   upgrades to the corresponding OKD release.

### Operating model

- **VM stays stopped by default.** `qm stop 108` is the resting state.
- **`qm start 108`** spins it up when an operator wants to validate
  something. Boot time ~5-10 minutes for a cold start.
- **Weekly cron** in `stronghold-system` on the prod cluster (or in the
  homelab host's cron) brings the sandbox up, runs the chart's
  compatibility test suite, posts results, brings it down. This catches
  CRC version drift and Stronghold chart drift before either becomes a
  surprise.
- **Manual sessions**: an operator can `qm start 108`, `crc start`, run
  exploratory work, then `qm stop 108` when done.
- **No production workload** ever runs on the sandbox. It is by
  definition a throwaway environment.
- **No backups.** The sandbox is stateless from Stronghold's perspective.
  CRC's own state (the cluster image, the pull secret cache) is on the
  VM disk and is reproducible by `crc setup` from scratch.

### What lives in the sandbox

- A full OpenShift cluster (Web Console, OperatorHub, ImageRegistry,
  Routes, SCCs, Builds, ImageStreams)
- Whatever Stronghold chart version is currently being validated
- Test data only — no real customer data, no real model API keys (use
  fake values from `values-crc.yaml`)

### What does NOT live in the sandbox

- Production Stronghold workload
- Any customer data
- Real secrets (use fake values throughout)
- Persistent state that matters across `crc start` / `crc stop` cycles

## Alternatives considered

**A) MicroShift instead of CRC.**

- Rejected: MicroShift drops the Web Console, OperatorHub, ImageStreams,
  and Builds. These are the very things we need to validate compatibility
  against. A sandbox that strips out the surface we want to test is
  worse than no sandbox.

**B) A second SNO cluster (full OKD on a dedicated VM, just like prod).**

- Rejected: too much resource cost for a throwaway environment. Two SNO
  clusters means ~64GB of allocated RAM (2× 32GB VMs) and two upgrade
  cycles to keep healthy. CRC's 16GB on-demand footprint is right-sized
  for a sandbox.

**C) An ephemeral CI Kubernetes runtime on the homelab host.**

- Rejected: a CI runtime is not OpenShift. It doesn't have Routes, doesn't
  have SCCs, doesn't have OperatorHub. We already rejected ephemeral CI
  runtimes as production targets in ADR-K8S-006; they're also not a
  substitute for OpenShift validation.

**D) No sandbox at all — validate against the prod cluster directly
using ephemeral namespaces.**

- Rejected: prod cluster is for prod and dev branches per ADR-K8S-008.
  Compatibility validation that involves cluster-level changes (cluster
  operator upgrades, OperatorHub installs, Web Console testing) cannot
  be done in a namespace. A separate cluster is the only safe place.

**E) Run CRC on the operator's workstation, not on the homelab.**

- Rejected: the homelab is the canonical environment for Stronghold
  development on this team. Workstation CRC means another local VM, more
  battery drain on a laptop, and asymmetry between team members. Putting
  it on the homelab keeps the development surface uniform.

## Consequences

**Positive:**

- We can validate Stronghold's chart against the full OpenShift surface
  without risking the prod cluster.
- CRC's faster release cadence catches OpenShift version drift before
  OKD ships the same version, giving us a heads-up window.
- The sandbox costs nothing when stopped (`qm stop 108` releases all
  RAM and CPU back to the host).
- Operator learning happens on the sandbox, not on prod.

**Negative:**

- Red Hat developer account registration required for the pull secret.
  One-time, free, mildly annoying.
- CRC boot time (5-10 minutes cold start) makes the weekly compatibility
  cron slower than running it against an always-on cluster. Acceptable —
  the cron isn't latency-sensitive.
- 50GB of VM disk allocated to a mostly-stopped VM. Acceptable on the
  homelab's NVMe budget.
- One more VM in the inventory (`stronghold-crc`, VMID 108) to register
  in the homelab CLAUDE.md and PBS backup config (the VM disk gets
  snapshotted nightly even though it's stopped, for convenience of
  rollback if `crc setup` ever corrupts the install).

**Trade-offs accepted:**

- Resource cost (mostly stopped) and Red Hat account in exchange for a
  full-fidelity OpenShift sandbox.
- We accept that the sandbox is not a complete substitute for testing
  against real customer environments — that's what the per-cloud
  pre-release validation in ADR-K8S-007 is for.

## References

- Red Hat OpenShift Local (CRC) documentation
- Red Hat MicroShift documentation
- OpenShift Container Platform 4.14 documentation: "Single-node OpenShift cluster install"
- ADR-K8S-006 (runtime selection — homelab prod cluster choice)
- ADR-K8S-007 (distro compatibility matrix — Tier-1 release validation)
- ADR-K8S-008 (prod/dev isolation — why the sandbox can't share the prod cluster)
