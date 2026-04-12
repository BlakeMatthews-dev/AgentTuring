# ADR-K8S-028 — Stronghold as A2A peer

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Stronghold exposes two protocol surfaces to external callers. The first
is MCP (Model Context Protocol), which provides a function-level
interface: a caller invokes a specific tool with specific arguments and
gets a structured result back. MCP is synchronous, stateless from the
caller's perspective, and scoped to a single operation. It is the right
abstraction when a caller knows exactly which tool to invoke.

The second abstraction level is task-level: a caller wants to delegate a
complex goal to an agent without specifying which tools to use, in what
order, or for how long. The caller says "research this topic and produce
a report" or "monitor this service and alert on anomalies," and the
agent decides how to accomplish the goal — selecting tools, making
multiple LLM calls, streaming intermediate progress, and eventually
producing a final result. This is what A2A (Google's Agent-to-Agent
protocol) provides: a task lifecycle with create, get, stream, and
cancel operations.

Without an A2A endpoint, external systems that want to use Stronghold's
agents must compose multi-step MCP tool calls themselves. They must
manage the agent loop, handle retries, track intermediate state, and
poll for completion. This is error-prone, duplicates logic that
Stronghold's agent strategies already implement, and prevents
Stronghold from participating in the A2A ecosystem as a peer that other
agent platforms can discover and delegate to.

MCP and A2A are complementary, not competing. MCP is the function-level
interface (call a tool, get a result). A2A is the task-level interface
(submit a goal to an agent, let it run, stream progress, get the final
result). Stronghold needs both because its callers operate at both
levels. The two endpoints share authentication, policy enforcement,
the credential vault, and the agent registry — they differ only in the
protocol shape and the abstraction level they serve.

## Decision

**Stronghold-API serves an A2A endpoint co-located in the same pod as
the MCP endpoint, on a separate URL path, sharing all platform
services.**

### Endpoint layout

The Stronghold-API pod exposes:

- `/mcp/*` — MCP protocol endpoint (existing, function-level)
- `/a2a/*` — A2A protocol endpoint (new, task-level)
- `/a2a/.well-known/agent.json` — A2A Agent Card discovery for the
  Stronghold platform agent

Both endpoints share the same FastAPI application, the same auth
middleware, the same Postgres connection pool, and the same Phoenix
tracing. They are different routers mounted on the same ASGI app.

### Task lifecycle

The A2A endpoint implements the standard A2A task lifecycle:

- `POST /a2a/tasks/create` — submit a new task to a named agent. The
  request includes the target agent name, the task specification (a
  natural-language goal plus optional structured parameters), and
  caller identity. The endpoint validates the request against the
  task acceptance policy (ADR-K8S-030), resolves the agent via the
  catalog (ADR-K8S-027), creates a task record in Postgres, and
  returns a `task_id` immediately.

- `GET /a2a/tasks/get/<id>` — retrieve the current state of a task,
  including its status (pending, running, completed, failed, cancelled),
  intermediate artifacts, and final result if complete.

- `GET /a2a/tasks/stream/<id>` — open an SSE (Server-Sent Events)
  stream that emits task progress events in real time. Events include
  status transitions, intermediate outputs, tool call notifications,
  and the final result. The stream closes when the task reaches a
  terminal state.

- `POST /a2a/tasks/cancel/<id>` — request cancellation of a running
  task. The agent is signaled to stop at its next checkpoint; the task
  transitions to cancelled state.

### Internal and external dispatch

Stronghold's own Conduit component uses the same dispatch path when
routing agentic requests to agents. When an internal request is
classified as agentic (per ADR-K8S-013), Conduit creates a task through
the same code path that the A2A endpoint uses, minus the A2A protocol
serialization. This means internal agent dispatch and external A2A
dispatch share the same policy enforcement, quota tracking, and audit
trail.

External A2A callers go through the additional A2A protocol layer:
JSON-RPC framing, A2A-specific error codes, and A2A Agent Card
discovery. But the core dispatch — agent resolution, task creation,
strategy execution, state persistence — is identical.

### Task state persistence

Every task is persisted in the `a2a_tasks` Postgres table with:

- `task_id` (UUID, primary key)
- `agent_id` (FK to `agent_registry`)
- `tenant_id`, `user_id` — ownership and isolation
- `status` (enum: pending, running, completed, failed, cancelled)
- `spec` (JSONB — the task specification from the caller)
- `result` (JSONB — the final output, nullable until complete)
- `artifacts` (JSONB array — intermediate outputs)
- `priority_tier` (P0-P5, assigned at acceptance time)
- `budget` (token limit, cost limit, wall-clock deadline)
- `created_at`, `updated_at`, `completed_at`

Task state survives pod restarts. A restarted Stronghold-API pod
picks up in-progress tasks from Postgres and resumes them from their
last checkpoint.

### Relationship to MCP

The A2A endpoint does not replace MCP. They serve different callers and
different use cases:

- A caller that knows it wants to invoke the `github_create_pr` tool
  uses MCP. The call is synchronous, the result comes back immediately,
  and no task state is created.
- A caller that wants to delegate "review this PR and suggest
  improvements" to the Ranger agent uses A2A. A task is created, the
  agent runs asynchronously, and the caller streams progress.

An A2A task may internally invoke MCP tools as part of its execution.
The agent strategy decides which tools to call; the A2A task is the
container for that execution.

## Alternatives considered

**A) Internal-only agent dispatch — no external A2A endpoint.**

- Rejected: limits Stronghold to MCP as its only external protocol.
  Other agent platforms that speak A2A cannot discover or delegate to
  Stronghold's agents. Enterprise customers with multi-platform agent
  ecosystems cannot integrate Stronghold at the task level without
  writing custom glue.

**B) Separate A2A service in its own pod and Deployment.**

- Rejected: A2A and MCP share authentication, policy enforcement, the
  credential vault, the agent registry, Postgres, and Phoenix. Splitting
  them into separate pods means either duplicating these dependencies
  (doubling resource cost and drift risk) or adding internal RPC between
  the two pods (adding latency and failure modes). Co-location in the
  same pod is the natural choice when two endpoints share all their
  dependencies.

**C) Task lifecycle exposed as MCP tools — `create_task`, `get_task`,
`stream_task`, `cancel_task` as MCP tool definitions.**

- Rejected: conflates two protocol abstractions. MCP tools are
  synchronous request-response pairs. Task streaming (SSE over
  minutes or hours) does not fit MCP's tool model. Forcing task
  lifecycle into MCP tools would require the caller to poll
  `get_task` in a loop, losing the streaming capability that A2A
  provides natively. The abstractions are different enough to justify
  different protocol surfaces.

**D) gRPC for the task-level interface instead of A2A.**

- Rejected: gRPC is a transport protocol, not an agent interoperability
  standard. It defines how to serialize and transmit, but not what an
  agent is, what a task is, or how discovery works. Adopting gRPC would
  mean inventing the agent and task semantics ourselves, losing
  interoperability with the A2A ecosystem, and requiring every caller
  to generate gRPC stubs.

## Consequences

**Positive:**

- Stronghold becomes a peer in the A2A ecosystem, discoverable by and
  delegatable from any A2A-compatible platform.
- External callers get a task-level interface that matches the
  complexity of agentic work, with streaming progress and cancellation.
- Internal and external agent dispatch share the same code path,
  ensuring consistent policy, audit, and quota enforcement.
- The co-located architecture avoids the operational overhead of a
  separate A2A deployment.

**Negative:**

- The Stronghold-API pod now serves two protocols, increasing its
  surface area and testing requirements.
- A2A is a younger specification than MCP, so the protocol may evolve
  in ways that require Stronghold to adapt. We mitigate this by
  versioning our A2A endpoint and supporting protocol negotiation.
- SSE streaming for long-running tasks holds open HTTP connections,
  which requires tuning connection limits and load balancer timeouts.

**Trade-offs accepted:**

- We accept the increased surface area of a dual-protocol pod in
  exchange for co-location benefits (shared auth, shared state, no
  internal RPC).
- We accept the specification-evolution risk of A2A in exchange for
  ecosystem interoperability that a proprietary protocol cannot provide.
- We accept the SSE connection management burden in exchange for
  real-time task streaming without polling.

## References

- A2A specification: task lifecycle (tasks/create, tasks/get,
  tasks/stream, tasks/cancel)
- MCP specification: tool invocation protocol (for contrast)
- Kubernetes documentation: "Services" and "Pods"
- IETF RFC 8895: Server-Sent Events
- ADR-K8S-013 (hybrid execution model — conversational vs. agentic)
- ADR-K8S-027 (agent catalog — agent resolution and discovery)
- ADR-K8S-030 (task acceptance policy — gates task creation)
