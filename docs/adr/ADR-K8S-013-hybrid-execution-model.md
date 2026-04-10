# ADR-K8S-013 — Hybrid execution model: conversational and agentic surfaces

**Status:** Proposed
**Date:** 2026-04-08
**Deciders:** Stronghold core team

## Context

Stronghold serves two fundamentally different request shapes, and the v0.9
Kubernetes deployment has to host both on the same cluster without forcing
one shape's constraints onto the other.

The first shape is **conversational**: a user types a message into the chat
UI (or a programmatic client hits `/v1/chat/completions`), the request
classifies as chat-style, the model replies, tools run synchronously within
the request, and the whole exchange finishes in under a handful of seconds.
Concurrency is high (many users, many sessions), latency budget is small
(p99 under 2 seconds for P0 chat), and state is mostly ephemeral — each
turn stands on its own with context pulled from the session store.

The second shape is **agentic**: a user submits a mission ("research topic
X and produce a report", "refactor this package across 40 files", "monitor
this market for the next 6 hours and flag anomalies"). The work runs for
minutes to hours, progresses through multiple phases, accumulates durable
state (intermediate files, partial results, tool call history), and is
resumable across pod restarts. Concurrency is much lower (a single user
might have 2-3 missions running), latency budget is enormous (minutes is
fine, cold start is fine), and state must survive failures.

Trying to serve both shapes from the same process, or from the same pod
shape, produces obvious failures. A sub-second chat handler cannot afford
to pay pod-startup latency. A multi-hour mission cannot be held in an
in-process handler without blocking a request worker for hours and without
losing state on any pod restart. The load shapes, the failure modes, and
the trust assumptions are different enough to justify different execution
surfaces.

What is **not** different: the platform services that support both shapes.
Postgres (memory, traces, mission state), Phoenix (tracing and dashboards),
LiteLLM (model proxy), MCP servers (tool backends), Classifier, Router,
Auth, Quota, and Audit are all shared. We do not want two copies of the
control plane or two copies of the data plane — that would double ops cost
and split the audit trail.

## Decision

**Stronghold runs two execution surfaces sharing a single control plane
and a single data plane.** Conduit, the ingress component inside
Stronghold-API, is the routing boundary that decides which surface handles
a given request.

### Surface 1 — conversational (in-process)

- Runs inside the `stronghold-api` Deployment in `stronghold-platform`
- Every request is handled synchronously by a FastAPI worker within the
  main application process
- Tools invoked during the request run in-process or via short HTTP calls
  to MCP servers
- State lives in Postgres (session store, conversation history) and is
  loaded per request; no persistent per-user compute state
- Target latency: sub-second to a handful of seconds (p99 under 2s for P0)
- Concurrency: hundreds of in-flight requests per replica
- Trust boundary: Stronghold's own code only. No customer-supplied strategy
  code runs here.
- Failure mode: an individual request fails, the client retries, the next
  request lands on any healthy replica

### Surface 2 — agentic (per-user Mission pods)

- Each active mission runs in its own dedicated pod
- Conduit returns a `mission_id` immediately on submission; the client
  polls or streams progress via a separate endpoint
- The pod runs until the mission completes, fails irrecoverably, or is
  cancelled
- State is durable: intermediate artifacts, partial results, tool-call
  history, and checkpoints are written to Postgres and/or a mission-scoped
  volume so the mission can resume after a pod restart
- Target latency: minutes to hours; cold start of ~30 seconds is acceptable
- Concurrency: a handful of missions per user, tens to low-hundreds per
  cluster
- Trust boundary: may execute customer-supplied agent strategies (issue #59
  "custom strategy pluggability"), long-running scripts, and arbitrary
  tool chains. Each mission pod runs under the `restricted-v2` SCC with
  the minimum ServiceAccount permissions the mission needs.
- Failure mode: the mission is resumed from its last checkpoint on a
  fresh pod. The controller responsible for lifecycle is the subject of
  the #770-#795 issue chain already in the backlog.

### Shared plane (both surfaces)

Control plane:

- **Conduit** — ingress router, applies classifier output to pick a surface
- **Classifier** — intent and task-type detection
- **Router** — model selection (quality/cost scoring per ADR on routing)
- **Auth** — OIDC and JWT verification
- **Quota** — per-tenant, per-provider, per-priority-tier budget tracking
- **Audit** — structured event log

Data plane:

- **Postgres + pgvector** — memory, traces, session store, mission state
- **Phoenix** — tracing dashboard and trace storage
- **LiteLLM** — model proxy to cloud providers
- **MCP servers** — tool backends (github, dev-tools, filesystem, …)

Both the conversational workers and the mission pods talk to the shared
plane over the same in-cluster service FQDNs. Every call is tagged with
`surface=conversational` or `surface=agentic` so Phoenix traces and audit
events can be filtered by surface.

### The routing rule

Conduit applies this rule on every incoming request:

1. Run the classifier on the request.
2. If `classifier.task_type` is a chat-style type (chat, single-tool-call,
   quick-answer, follow-up) and `classifier.expected_duration_seconds`
   under 30, dispatch to the conversational surface in-process.
3. Otherwise dispatch to the agentic surface: synthesize a `mission_id`,
   enqueue the mission, return the id to the client, and let the mission
   pod lifecycle controller spawn the pod.
4. The client can subsequently query `/v1/missions/{mission_id}` to stream
   events or poll status.

The rule is deliberately one-directional: a request starts in one surface
and stays there. A chat-style request cannot "promote" itself to a mission
mid-flight; if a chat turn wants to kick off a longer background workflow,
it does so by submitting a new mission via a tool call.

## Alternatives considered

**A) Single execution model for both shapes.** Collapse conversational and
agentic onto one surface — for example, run everything as in-process
handlers, or run everything as per-request pods.

- Rejected: the load shapes are fundamentally different. In-process
  handlers cannot hold multi-hour missions without pinning a request
  worker and losing state on any restart. Per-request pods cannot meet
  sub-second chat latency because pod startup alone blows the budget.
  Forcing one surface to serve both shapes means compromising on the
  binding constraint of at least one.

**B) Per-request pods always, including for chat.** Every chat turn gets
its own short-lived pod.

- Rejected: pod startup latency (even with image cache warm and scheduler
  warm) is measured in seconds, not tens of milliseconds. The P0 chat
  tier has a sub-2-second budget that pod startup alone would miss. A
  pool of warm chat pods would partially mitigate, but then we are
  re-inventing in-process workers with a pod shell around them for no
  isolation benefit — chat traffic is all Stronghold-owned code already.

**C) Always-warm pool of mission containers.** Keep a fixed number of
mission-capable pods hot so mission startup is instant.

- Rejected: missions are bursty and rare compared to chat. A warm pool
  large enough to absorb mission bursts idles most of the time; a warm
  pool small enough not to idle runs out under burst. Scale-to-zero with
  a 30-second cold start matches the mission latency budget and costs
  nothing when idle. This is the classic case where the latency budget
  pays for itself by allowing cheap lifecycle.

**D) Two entirely separate deployments (two clusters, two control
planes).** Run conversational Stronghold and agentic Stronghold as
independent stacks.

- Rejected: doubles the ops surface and splits the audit trail across two
  Postgres instances, two Phoenix instances, two Quota trackers. Tenants
  would need to be provisioned twice. Cross-surface observability
  (correlating a chat turn that spawned a mission with the resulting
  mission's events) becomes a cross-cluster problem. The correct axis of
  separation is the execution surface, not the entire stack.

## Consequences

**Positive:**

- Each surface is tuned to its binding constraint: chat gets latency,
  missions get durability and isolation.
- Customer-supplied strategy code (issue #59) is contained to mission
  pods with narrow RBAC and no access to the chat hot path.
- The shared plane means a single Postgres, a single Phoenix, a single
  quota tracker, a single audit log — consistent tenant experience.
- The hybrid shape matches how Stronghold's users actually use the
  product: quick questions interleaved with occasional long tasks.

**Negative:**

- Conduit gains a routing responsibility and must be tested on both
  surfaces.
- The mission pod lifecycle controller (the #770-#795 chain) is a new
  component to build, operate, and secure.
- Cross-surface correlation in Phoenix requires a shared `request_id` /
  `parent_mission_id` convention; chart and tracing config must enforce
  it.

**Trade-offs accepted:**

- We accept the complexity of two execution surfaces in exchange for
  meeting both the chat latency budget and the mission durability budget
  without compromising either.
- We accept the burden of the mission pod controller in exchange for
  proper isolation of customer strategies.

## References

- Kubernetes documentation: "Pods" and "Jobs"
- Kubernetes documentation: "Pod Lifecycle"
- OpenShift Container Platform 4.14 documentation: "Understanding Jobs and CronJobs"
- Google SRE Book, chapter 22 ("Addressing Cascading Failures") — on the
  value of shedding long requests away from latency-critical paths
- Nygard, "Release It!" 2nd ed., chapter 4 (stability patterns: bulkheads)
- ADR-K8S-001 (namespace topology), ADR-K8S-002 (RBAC boundary),
  ADR-K8S-014 (priority tiers), ADR-K8S-015 (PriorityClass eviction order)
