# ADR-K8S-005 — Warden topology

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

Stronghold's Warden + Sentinel layers enforce security and policy on every
agent action: detecting prompt injection, sanitizing tool inputs, applying
strike-based lockouts, and gating tool calls against the per-tenant policy.
ARCHITECTURE.md §6 describes them as "in-process" components inside the main
Stronghold API process.

There are two viable deployment topologies:

1. **In-process** — Warden and Sentinel run as Python modules inside the
   `stronghold-api` Deployment. Every API request crosses no network boundary
   to consult policy. Failure modes are local.

2. **Microservice split** — Warden runs as a separate Deployment exposing an
   API; the main Stronghold API calls it over RPC for every policy decision.
   Allows horizontal scaling of policy enforcement independently from the
   main API.

The microservice split has appeal for high-scale deployments (Warden
bottleneck on a single pod, want to scale policy throughput independently)
and for hot-swap policy updates (rotate Warden pods without restarting the
API). It also has serious downsides (per-request RPC latency, cache coherence,
network failure handling, split-brain between remote policy and local
fallback).

We need to decide which topology Stronghold ships with in v0.9, and whether
the microservice split is on the roadmap for v1.3+ or rejected outright.

## Decision

**v0.9 ships with Warden and Sentinel in-process inside the `stronghold-api`
Deployment.** No separate Warden or Sentinel pods. No RPC layer for policy
decisions. The split topology is documented here as a future option for
v1.3+, with the conditions that would trigger reconsidering it.

### v0.9 deployment shape

- `stronghold-api` Deployment includes Warden and Sentinel as Python modules
  loaded at startup
- Policy decisions happen via direct in-process function calls
- Strike state lives in PostgreSQL (BACKLOG R22 fix in PR-4) so it survives
  pod restarts and scales horizontally with the API replica count
- Hot-reload of policy rules happens via PostgreSQL `LISTEN/NOTIFY` or a
  filesystem watcher on a ConfigMap volume — no Warden restart required

### When to reconsider the split (v1.3+ trigger conditions)

The microservice split becomes worth the cost when **any two** of the
following are true:

1. Warden's policy evaluation dominates p95 API latency (measure: Warden
   span > 30% of total request span on Phoenix traces)
2. Warden CPU saturates the `stronghold-api` pod and we cannot scale the API
   horizontally without over-provisioning unrelated workload
3. Policy rotation cadence exceeds once per day, AND restarting `stronghold-
   api` to pick up new rules causes user-visible disruption that hot-reload
   does not solve
4. Multi-tenant isolation requires per-tenant Warden policies that a single
   shared in-process Warden cannot serve safely
5. A regulatory requirement mandates a separate audit boundary for policy
   enforcement (rare but possible for FedRAMP / HITRUST)

If we reach the trigger, the v1.3+ split topology would be:

- New `stronghold-warden` Deployment in `stronghold-platform` namespace
- gRPC server for policy evaluation; protobuf schema versioned via
  buf.build
- `stronghold-api` calls Warden via a typed client with: 50ms timeout,
  exponential-backoff retry (max 2 retries), local LRU cache (1000 entries,
  60s TTL) for repeat queries within a session
- Failure mode: **fail closed**. If Warden is unreachable after retries,
  the request is denied. Open is not safe for a security layer.
- Strike state stays in PostgreSQL (already centralized post-PR-4)
- A new ADR documents the actual rollout when the time comes

## Alternatives considered

**A) Microservice split in v0.9.**

- Rejected: premature. Adds RPC latency, cache complexity, network failure
  handling, and a new pod to operate, with no measured need. The right time
  to split is when the in-process design hits a measurable limit, not on
  speculation. We're optimizing the wrong end of the latency budget.

**B) In-process now, but with the Warden and Sentinel modules wrapped in an
internal RPC interface so we can move them out later without rewriting
callers.**

- Rejected: this is the "future-proof now" trap. The interface we'd design
  before measuring the actual hot path would be wrong, and we'd carry the
  cost of the RPC indirection in v0.9 without the benefit. When we actually
  split (if we ever do), we will know what shape the interface needs.

**C) In-process for Warden, microservice for Sentinel.**

- Rejected: no clean reason to split them. They share state (strike counts,
  per-tenant policy versions, the `tool_registry`). Splitting one introduces
  the same RPC and cache problems as splitting both, with no proportional
  benefit.

**D) Sidecar pattern — Warden as a sidecar in every `stronghold-api` pod.**

- Rejected: sidecars share lifecycle with the main container, so the hot-
  swap-policy benefit is lost. Sidecars are appropriate when the workload
  needs different runtime characteristics (different language, different
  scaling) — neither applies to Warden vs. the main API.

## Consequences

**Positive:**

- Simplest possible v0.9 deployment: one Deployment to operate, one set of
  metrics to monitor, no RPC failure modes.
- Lowest possible policy decision latency (function call, not network
  round-trip).
- No cache coherence problem to solve.
- Strike persistence (PR-4) handles horizontal scaling cleanly.
- We don't pay any operational cost for a split until we have evidence we
  need it.

**Negative:**

- Cannot scale Warden independently of the main API. If Warden becomes a
  bottleneck, the only knob is "scale the entire API horizontally", which
  may over-provision other components.
- Hot-reload of policy rules is more complex than "kubectl rollout restart
  warden" would be — we need a LISTEN/NOTIFY or ConfigMap-watch mechanism.
- Cannot place Warden behind a separate audit boundary without a rewrite.
  Acceptable: regulatory boundary requirements aren't on the v0.9 roadmap.

**Trade-offs accepted:**

- We accept that the in-process design will eventually hit a limit at some
  customer scale, and we will pay the cost of the split at that point — not
  before.

## References

- ARCHITECTURE.md §6 (Warden + Sentinel design)
- BACKLOG R22 (strike persistence — addressed in PR-4)
- Kubernetes documentation: "Pod design patterns" — kubernetes.io/docs/concepts/workloads/pods/
- Sam Newman, "Building Microservices" 2nd ed., chapter 4 (when to split a service)
- Google SRE Book, chapter 2 ("Production Environment at Google" — service decomposition criteria)
- Martin Fowler, "MonolithFirst" — martinfowler.com/bliki/MonolithFirst.html
