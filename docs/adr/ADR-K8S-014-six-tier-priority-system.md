# ADR-K8S-014 — Six-tier priority system (P0-P5)

**Status:** Proposed
**Date:** 2026-04-08
**Deciders:** Stronghold core team

## Context

Stronghold has six related subsystems that each need some notion of "how
important is this request, and how much should the platform spend on it":

- **Routing** — how aggressively should the router prefer a flagship
  model over a cheap one?
- **Kubernetes scheduling** — which pods should the kubelet evict first
  when a node runs out of memory?
- **Token budgets** — how much context window should this task type be
  allowed to consume?
- **Quota tracking** — against which bucket does this request draw?
- **Observability / alerting** — when this request misses its SLA, page
  or log?
- **Failure handling** — retry, log, or give up?

Without a shared label, each subsystem invents its own priority scheme and
they drift out of alignment. The worst failure mode is a request that the
router treats as high priority (flagship model, expensive tokens) but the
kubelet treats as low priority (evicted first under pressure), because the
two systems disagree about what "high" means.

The existing `intent.priority` enum on the router side already has four
values (`low`, `normal`, `high`, `critical`) but they are used only for
model selection. They do not reach the Kubernetes layer, they do not have
associated token budgets, and they do not match the execution-surface
split between conversational and agentic work (ADR-K8S-013). Extending the
enum to a handful of additional values is not enough; we need a single
cross-cutting tier label that every subsystem reads from.

## Decision

**We introduce a six-tier cross-cutting priority system (`priority_tier`
values P0 through P5) that every relevant subsystem must read from.** The
existing four-value `intent.priority` enum is repurposed as a routing-only
signal; the new `priority_tier` label is what flows through scheduling,
budgets, quota, observability, and eviction.

### The six tiers

| Tier | Name | Surface | Routing weight | Model bias | Token budget | Cold-start | PriorityClass | minReplicas | Eviction | SLA / alert |
|------|------|---------|----------------|------------|--------------|------------|---------------|-------------|----------|-------------|
| P0 | chat-critical | in-process (conversational) | 2.0× | flagship | 2.0× base | 0s — always warm | 1_000_000 | 2+ (HA) | LAST (protected) | <2s p99 / page |
| P1 | chat-tools | per-pod, kept warm | 1.5× | flagship | 1.5× base | <2s warm pool | 800_000 | 1+ | after P2-P5 | <5s p99 / page |
| P2 | user-missions | per-pod, on-demand | 1.0× | balanced | 1.0× base | 30s acceptable | 600_000 | 0 (scale-to-zero) | after P3-P5 | <60s p99 / log+retry |
| P3 | backend-support | scheduled / event-driven | 0.7× | fast-cheap | 0.5× base | 30s+ | 400_000 | 0-1 | after P4-P5 | best-effort / log |
| P4 | quartermaster | per-pod, on-demand per parent issue | 1.0× | balanced (research-capable) | 1.0× base | 30s+ | 200_000 | 0 | after P5 | best-effort / log+retry |
| P5 | builders | per-pod, on-demand per sub-issue | 0.7× | balanced (code-capable) | 0.5× base | minutes acceptable | 100_000 | 0 | FIRST (evicted first) | best-effort / log+retry |

### How the tiers map to real work

- **P0 chat-critical** — a logged-in user typing into the chat UI,
  expecting a sub-2-second reply. No tool calls, or tool calls that
  resolve in-process. This is the hot path for the conversational
  surface from ADR-K8S-013.
- **P1 chat-tools** — a chat turn that invokes long-running tools
  (browser automation, deep-search MCPs). Still conversational from the
  user's point of view, but routed to a kept-warm tool pod.
- **P2 user-missions** — agentic surface work submitted by a user (a
  research mission, a refactor mission). Runs in its own mission pod,
  scale-to-zero when idle.
- **P3 backend-support** — janitors, sweepers, quota reconcilers,
  scheduled maintenance tasks that keep the platform healthy. Runs on
  cron or on events, not on user request.
- **P4 quartermaster** — the supervising agent that decomposes a parent
  issue into sub-issues and hands them off. One quartermaster pod per
  active parent issue.
- **P5 builders** — the implementer agents that pick up sub-issues and
  produce code changes. Many builder pods per quartermaster. Lowest
  priority because the platform can always re-spawn a builder if its
  pod is evicted; in-flight parent issues retain their checkpoints.

### Routing weight and model bias

The router (quality / cost scoring, see the routing ADR) multiplies its
quality term by the tier's routing weight. A P0 request gets 2.0× the
quality weight, so the router willingly picks a more expensive flagship
model. A P5 request gets 0.7×, so the router prefers the cheapest model
that clears the quality floor.

Model bias is a soft filter: P0 and P1 bias toward models tagged
`flagship` in the registry; P2/P4 toward `balanced`; P3/P5 toward
`fast-cheap`. The bias is a preference, not a hard restriction — the
router can still pick a non-biased model if its scoring says so.

### Token budget multiplier

Each tier multiplies a base token budget. A P0 request is allowed up to
2.0× the base context window; a P5 request only 0.5×. Base values are
set per task type in the router config. The effect is that chat-critical
traffic gets the most room to paste a large file into a question, while
builder pods are kept tight to prevent runaway context growth in
autonomous work.

### Eviction order and PriorityClass

The `PriorityClass` numeric values come from ADR-K8S-015. The order of
eviction under node-memory pressure is P5, then P4, then P3, then P2,
then P1, then P0. P0 and P1 are additionally protected by
`PodDisruptionBudget` so voluntary disruptions cannot remove them either.

The numeric values (1_000_000 down to 100_000) sit comfortably below the
Kubernetes system-level priority classes (`system-cluster-critical` is
2_000_000_000 and `system-node-critical` is 2_000_001_000), so Stronghold
pods can never starve platform control-plane pods.

### Default values in the chart

The Helm chart's `values-prod-homelab.yaml` sets:

```yaml
priority:
  tiers:
    P0: { priorityClassName: stronghold-p0-chat-critical, minReplicas: 2, routingWeight: 2.0, tokenMultiplier: 2.0 }
    P1: { priorityClassName: stronghold-p1-chat-tools,    minReplicas: 1, routingWeight: 1.5, tokenMultiplier: 1.5 }
    P2: { priorityClassName: stronghold-p2-user-missions, minReplicas: 0, routingWeight: 1.0, tokenMultiplier: 1.0 }
    P3: { priorityClassName: stronghold-p3-backend,       minReplicas: 0, routingWeight: 0.7, tokenMultiplier: 0.5 }
    P4: { priorityClassName: stronghold-p4-quartermaster, minReplicas: 0, routingWeight: 1.0, tokenMultiplier: 1.0 }
    P5: { priorityClassName: stronghold-p5-builders,      minReplicas: 0, routingWeight: 0.7, tokenMultiplier: 0.5 }
```

### Eviction order matches dependency order in reverse

Builders (P5) depend on quartermaster (P4) to hand them work. Quartermaster
depends on backend-support (P3) janitors keeping quota tables clean, session
state tidy, and crashed mission pods reaped. Backend-support depends on the
platform itself (chat on P0/P1) staying responsive enough that users keep
using the product. If the kubelet has to evict something, taking out a
builder is least disruptive — the quartermaster above it will simply notice
the builder went away and respawn one. Evicting a quartermaster orphans
multiple in-flight builders. Evicting a backend-support task leaves the
platform limping. Evicting chat kills the product. The order P5 → P4 → P3
→ P2 → P1 → P0 is therefore the dependency order reversed.

## Alternatives considered

**A) Keep the four-value `intent.priority` enum (low / normal / high /
critical) and wire it through the other subsystems.**

- Rejected: four values cannot cleanly represent the chat/agent split.
  "chat-critical" and "user-mission" are both what the old enum would
  call "high", but they want completely different eviction behavior,
  warm-pool behavior, and token budgets. Collapsing them loses the
  distinction that matters most.

**B) Per-tenant priority tiers (each tenant names and numbers its own).**

- Rejected: breaks the global eviction ordering. If tenant A's P1 and
  tenant B's P1 are different numeric values, the kubelet evicts based
  on the numeric value, not the tenant's intent. Shared infrastructure
  needs a shared priority scale.

**C) Use Kubernetes' default PriorityClasses only
(`system-cluster-critical`, `system-node-critical`, and a single
"normal" user class).**

- Rejected: those classes are designed for platform control-plane pods,
  not for application tiers. There are only two reserved user classes
  in a default cluster, which gives us two tiers — we need six. And the
  numeric values are chosen to keep Kubernetes platform pods safe, not
  to encode Stronghold's own dependency graph.

**D) Three tiers only (critical / normal / low).**

- Rejected: three tiers conflate chat-critical with chat-tools, and
  conflate user-missions with quartermaster and builders. The three
  most interesting places where we want different behavior all collapse
  into "normal". The chart ends up with ad-hoc overrides per workload,
  which is worse than just having six tiers.

**E) A continuous priority score (0.0 to 1.0) instead of discrete tiers.**

- Rejected: Kubernetes PriorityClass is discrete, and operators reason
  about eviction in discrete buckets ("which tier got evicted?"). A
  continuous score would have to be bucketed at the k8s boundary
  anyway, so we may as well expose the buckets as first-class concepts
  everywhere.

## Consequences

**Positive:**

- Routing, scheduling, quotas, budgets, observability, and eviction all
  read from the same label. They cannot drift.
- Operators diagnosing an incident can ask "what tier is affected?" and
  get a clean answer that pins down the right subsystems to check.
- Adding a new workload means picking a tier, not inventing one — which
  keeps the taxonomy from sprawling.
- The tier table becomes the single reference document for anyone
  deciding how a new Stronghold component should behave.

**Negative:**

- Six tiers is more than the old four, so existing intent-classification
  rules need an upgrade to emit `priority_tier` alongside `priority`.
- The chart templates grow a `{{ with .Values.priority.tiers.P0 }}` kind
  of block on every Deployment that needs a tier — mitigated by a
  `_helpers.tpl` macro.
- Test coverage must now include all six tiers' PriorityClass and
  budget behavior.

**Trade-offs accepted:**

- We accept more tiers than the old enum in exchange for cleanly
  separating chat from agent and flagship from fast-cheap.
- We accept a one-time migration cost in exchange for never again
  having to reconcile divergent priority notions across subsystems.

## References

- Kubernetes documentation: "Pod Priority and Preemption"
- Kubernetes documentation: "Pod Quality of Service Classes"
- OpenShift Container Platform 4.14 documentation: "Using pod priority
  and preemption"
- RFC 6733 §4.1.1 (priority ordering concepts from a different domain,
  used here as a reasoning template)
- Google SRE Book, chapter 21 ("Handling Overload") — on shedding
  low-priority work to protect high-priority work
- ADR-K8S-008 (prod/dev isolation), ADR-K8S-013 (hybrid execution
  model), ADR-K8S-015 (PriorityClass eviction order)
