# ADR-K8S-015 — PriorityClass numeric values and eviction order

**Status:** Proposed
**Date:** 2026-04-08
**Deciders:** Stronghold core team

## Context

ADR-K8S-014 defines the six Stronghold priority tiers (P0-P5) as a
cross-cutting label that flows through routing, scheduling, budgets,
quota, observability, and eviction. This ADR pins down the concrete
Kubernetes `PriorityClass` numeric values that realize the eviction
half of that design, explains why those specific numbers were chosen,
and gives the verification procedure that confirms the kubelet actually
evicts in the intended order.

`PriorityClass` is a cluster-scoped Kubernetes resource. A pod with a
higher numeric `priority` value is preferred over a pod with a lower
value when the kubelet has to evict pods to relieve node pressure, and
when the scheduler has to preempt pods to make room for a pending pod.
The numeric value is the single source of truth for both behaviors —
names are labels for humans, but the ordering is pure integer
comparison.

Stronghold must pick values that satisfy three constraints at once:

1. They must strictly order Stronghold's six tiers in the intended
   eviction sequence (P5 first, P0 last).
2. They must sit comfortably below the two reserved
   Kubernetes system priority classes so that Stronghold pods can never
   starve control-plane pods under contention. The reserved values are
   `system-cluster-critical` = 2_000_000_000 and `system-node-critical`
   = 2_000_001_000.
3. They must leave room for future tiers to be inserted between
   existing ones without having to renumber the whole scheme.

## Decision

**The six Stronghold `PriorityClass` resources use the following numeric
`priority` values:**

| PriorityClass name | Tier | Numeric value |
|--------------------|------|---------------|
| `stronghold-p0-chat-critical` | P0 | 1_000_000 |
| `stronghold-p1-chat-tools`    | P1 |   800_000 |
| `stronghold-p2-user-missions` | P2 |   600_000 |
| `stronghold-p3-backend`       | P3 |   400_000 |
| `stronghold-p4-quartermaster` | P4 |   200_000 |
| `stronghold-p5-builders`      | P5 |   100_000 |

### Spacing rationale

The spacing is 200_000 between adjacent tiers, except between P5 and P4,
which is 100_000. This leaves room for at least one new tier to be
inserted between any two existing tiers without renumbering — a tier
between P2 and P3 could take 500_000, a tier between P0 and P1 could
take 900_000, and so on. Spacing of 1 would work for ordering but would
force renumbering every existing tier whenever a new one lands, and
renumbering is a chart-wide change.

The absolute values sit between 100_000 and 1_000_000, which is
roughly four orders of magnitude below `system-cluster-critical` at
2_000_000_000. Stronghold pods therefore cannot be scheduled in
preference to Kubernetes system pods, which is correct: losing the
Stronghold platform to an evicted kube-apiserver would be worse than
any amount of Stronghold-level outage.

### Eviction order and its rationale

The kubelet evicts pods under node-memory pressure in ascending
`priority` order (lowest numeric value first). Applied to the values
above, the eviction order is:

P5 (100_000) → P4 (200_000) → P3 (400_000) → P2 (600_000) → P1 (800_000) → P0 (1_000_000)

That matches ADR-K8S-014's dependency order in reverse. Builders (P5)
are safe to evict because the quartermaster that spawned them can
detect the eviction and respawn. Evicting a quartermaster (P4) is more
disruptive: it orphans several in-flight builders, but the controller
can still recover by resuming the parent issue's state from the
checkpoint in Postgres. Evicting a backend-support task (P3) starts to
hurt the platform's housekeeping. Evicting a user mission (P2) damages
user-visible long-running work. Evicting P1 breaks warm tool pods that
chat is actively reaching into. Evicting P0 breaks chat itself — the
product's primary surface.

P0 and P1 are additionally protected by `PodDisruptionBudget` with
`minAvailable: 1` (or 2 for P0 in the HA configuration), so voluntary
disruptions like node drains cannot take them down even without memory
pressure. This is belt-and-braces: the `PriorityClass` handles
involuntary eviction, the `PodDisruptionBudget` handles voluntary
disruption.

### Verification procedure

The order must not be assumed — it must be observed. After any change
to the `PriorityClass` values or to the Stronghold chart's use of them,
run this check on the target cluster:

1. Deploy a `stronghold-p0-chat-critical` pod and a `stronghold-p5-builders`
   pod onto the same node. Size them so that their combined memory
   request is within the node's allocatable pool, but their combined
   memory **limit** is above what the node can actually deliver under a
   forced-allocation test container.
2. Start a memory-hog container in a third pod targeting that node.
3. Observe the kubelet's eviction decisions:

   ```
   oc get events -A --field-selector reason=Evicted \
     --sort-by=.lastTimestamp
   ```

4. Confirm the P5 pod is evicted before the P0 pod. The expected event
   pattern is: the P5 pod transitions to `Failed` with reason
   `Evicted` and a message mentioning memory pressure; the P0 pod
   remains `Running`.
5. Repeat the test pairing each adjacent pair (P5 vs P4, P4 vs P3, …,
   P1 vs P0) to confirm monotonic ordering.
6. Record the results in the cluster's install-verification log
   (`docs/runbooks/cluster-bootstrap.md`).

This test runs once at cluster bootstrap and on any chart change that
touches the PriorityClass stanza in `templates/priority-classes.yaml`.
It does not need to run on every deploy.

### Preemption policy

Every Stronghold `PriorityClass` sets `preemptionPolicy: PreemptLowerPriority`
(the default). A pending high-priority pod can evict a running
lower-priority pod to make room. This is the intended behavior for the
chat-critical tier, where a chat pod restarting after a failure must
be able to come back immediately even if builders are occupying the
node.

## Alternatives considered

**A) Random spacing based on "what feels right".**

- Rejected: no principled room for future tiers. The first time someone
  wants to insert a tier between P2 and P3, they either have to
  renumber everything or pick an awkward value. Uniform spacing of
  200_000 with a consistent gap is the minimum discipline required to
  avoid that scenario.

**B) Spacing of 1_000_000 between adjacent tiers.**

- Rejected: would push P5 below 0 if more tiers were added to either
  end of the scheme. A symmetric six-tier scheme at 1M spacing would
  need values from 1_000_000 up to 6_000_000 to stay positive, which
  works but doesn't leave room for tiers beyond P5. Shrinking the
  spacing to 200_000 fits six tiers comfortably in the 100_000 to
  1_000_000 range, with plenty of headroom on both ends.

**C) Use the default PriorityClass values Kubernetes ships with.**

- Rejected: Kubernetes ships with `system-cluster-critical` and
  `system-node-critical` for control-plane pods and nothing else for
  user workloads. There are no predefined values that correspond to
  Stronghold's dependency graph, and using the system values for
  application pods would be actively wrong because application pods
  must never outrank kube-apiserver or kubelet.

**D) Identical numeric values for all Stronghold tiers, distinguishing
by `PodDisruptionBudget` alone.**

- Rejected: `PodDisruptionBudget` only handles voluntary disruption.
  Under involuntary memory pressure, the kubelet picks pods to evict by
  PriorityClass, and identical values mean the kubelet picks
  arbitrarily within the tied group. That would let the kubelet evict
  P0 chat pods while P5 builders survived, which is the exact failure
  mode the whole scheme exists to prevent.

**E) Use 2_000_000_000-range values so Stronghold pods outrank
everything, including system pods.**

- Rejected: dangerous and wrong. If a Stronghold pod outranks
  kube-apiserver, a memory leak in Stronghold can evict the API server
  and take the entire cluster offline. Application pods must always
  rank below platform control-plane pods.

## Consequences

**Positive:**

- Eviction order is mechanical, not judgmental — no operator needs to
  remember "which tier goes first", the integer comparison handles it.
- The 200_000 gap gives future-proofing: new tiers can land without
  renumbering.
- Stronghold pods cannot starve Kubernetes control-plane pods under any
  circumstances.
- The verification procedure turns the numeric ordering from a claim
  into an observed property of the running cluster.

**Negative:**

- The verification procedure is a manual step at bootstrap. Mitigated
  by documenting it in the cluster bootstrap runbook and by the low
  frequency with which `PriorityClass` values change.
- Numeric values must be kept in sync between the chart
  (`templates/priority-classes.yaml`) and the deployment specs that
  reference them by name. Mitigated by using name-based references in
  pod specs and only having the numeric values in one place.

**Trade-offs accepted:**

- We accept a one-time verification step at bootstrap in exchange for
  having actually observed (rather than assumed) the eviction order.
- We accept the 200_000 spacing convention in exchange for being able
  to insert future tiers without chart-wide renumbering.

## References

- Kubernetes documentation: "Pod Priority and Preemption"
- Kubernetes documentation: "Node-pressure Eviction"
- Kubernetes documentation: "API Priority and Fairness"
- OpenShift Container Platform 4.14 documentation: "Configuring pod
  priority classes"
- Kubernetes source: `pkg/scheduler/framework/plugins/defaultpreemption`
  (the plugin that enforces preemption by PriorityClass)
- ADR-K8S-008 (prod/dev isolation), ADR-K8S-014 (six-tier priority
  system)
