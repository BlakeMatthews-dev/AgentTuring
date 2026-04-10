# ADR-K8S-030 — Task acceptance policy

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

When an external A2A caller (or an internal Conduit dispatch) submits a
task to Stronghold, the platform faces a decision: should it accept this
task? The question sounds simple but has several dimensions that no
single existing mechanism addresses.

ADR-K8S-019 defines per-tool-call authorization via the Tool Policy
engine. That policy answers "is this user allowed to invoke this tool
with these arguments?" — a fine-grained, synchronous check on each tool
call during agent execution. But a task is broader than a tool call. A
task is a goal that may run for minutes or hours, invoke dozens of tools,
consume thousands of tokens, and cost real money. The per-tool-call
policy gates individual operations inside the task, but nothing gates the
task itself.

Without a task-level gate, any authenticated caller can submit arbitrarily
expensive tasks. A legitimate user could accidentally submit a research
task with a million-token budget. A misconfigured external A2A peer could
flood Stronghold with tasks that each pass per-tool-call authorization
but collectively overwhelm the cluster. A malicious actor with valid
credentials could submit tasks targeting high-cost agents, draining the
tenant's token budget before anyone notices.

The problem is compounded by the priority system from ADR-K8S-014. Each
task is assigned a priority tier that determines its resource allocation,
model bias, and eviction order. If the task acceptance gate does not
consider the tier's quotas and limits, a burst of P2 tasks could starve
P0 chat traffic by exhausting shared resources before the kubelet's
eviction logic kicks in.

The two-gate model — task acceptance at the boundary, per-tool
authorization during execution — provides defense in depth. The task
acceptance gate prevents expensive or unauthorized tasks from starting.
The per-tool gate prevents authorized tasks from exceeding their
per-operation permissions. Neither gate alone is sufficient; together
they cover both the macro (task) and micro (tool call) authorization
surfaces.

## Decision

**Stronghold introduces a task acceptance policy as a distinct policy
surface at the A2A boundary, evaluated before any task execution begins,
enforcing budget limits and tier quotas alongside authorization rules.**

### Policy evaluation

When a task creation request arrives (via A2A or internal dispatch), the
task acceptance engine evaluates a Casbin policy with the following
attributes:

- **Subject:** `(user_id, tenant_id, caller_type)` — who is requesting
  the task. `caller_type` distinguishes human users, internal Conduit
  dispatch, and external A2A peers.

- **Object:** `(agent_name, agent_trust_tier)` — which agent the task
  targets and its trust level from the catalog (ADR-K8S-027).

- **Action:** `task_create` — the operation being requested.

- **Context:** `(task_spec, requested_budget, expected_tools, deadline)`
  — the task's specification, the caller's requested token and cost
  budgets, the set of tools the agent is likely to invoke (inferred from
  the agent's capabilities), and the caller's requested deadline.

The Casbin model uses ABAC (Attribute-Based Access Control) so that
policies can express conditions like "tenant X's users can create tasks
for agent Y with a maximum budget of Z tokens" or "external A2A peers
can only create tasks for agents at trust tier T2 or below."

### Budget enforcement

Every accepted task is assigned a budget with three dimensions:

- **Token budget** — maximum total tokens (input + output) the task may
  consume across all LLM calls. Derived from the tier's token multiplier
  (ADR-K8S-014) and the tenant's remaining token allocation.

- **Cost budget (USD)** — maximum dollar cost the task may incur. Tracks
  model pricing through the router's cost model. Prevents a task that
  selects expensive flagship models from running up costs unbounded.

- **Wall-clock deadline** — maximum elapsed time before the task is
  forcibly cancelled. Prevents zombie tasks that stall without failing.
  Default deadlines are set per tier: P0 tasks have a 30-second
  deadline, P2 missions have a 1-hour default, P5 builders have a
  4-hour default.

Budget enforcement is continuous, not just at acceptance time. The task
runtime checks budget consumption after each tool call and LLM
invocation. If any budget dimension is exhausted, the task is cancelled
with a `budget_exceeded` status and the reason is recorded.

### Priority tier integration

The accepted task is assigned a priority tier from ADR-K8S-014. The tier
assignment considers:

- The agent's default tier (from its catalog entry)
- The caller's maximum permitted tier (from the Casbin policy)
- The task's characteristics (expected duration, expected tool set)

The tier determines the task's PriorityClass (for pod scheduling), its
token budget multiplier, its model bias, and its eviction order. A task
cannot be assigned a tier higher than the caller is authorized for; an
external A2A peer at T3 trust cannot create a P0 task.

### Audit trail

Every task acceptance decision emits a Phoenix span with:

- The full policy evaluation context (subject, object, action, context
  attributes)
- The decision (accepted or rejected)
- If accepted: the assigned budget, tier, and task_id
- If rejected: the reason (policy denial, budget exceeded, tier
  unauthorized, rate limit)

This audit trail is queryable in Phoenix dashboards and exportable for
compliance reporting. The span is emitted regardless of the decision, so
rejected tasks are visible to operators investigating abuse or
misconfiguration.

### Rate limiting

In addition to policy and budget gates, the task acceptance engine
enforces rate limits per (tenant, caller_type) pair. Rate limits are
configured per tier:

- P0/P1 tasks: high rate limit (these are chat-driven, frequent)
- P2 tasks: moderate rate limit (user-submitted missions)
- P3 tasks: low rate limit (backend maintenance, scheduled)
- P4/P5 tasks: moderate rate limit (builder workflows, bursty but
  bounded by quartermaster concurrency)

Rate limits are a safety net, not a primary authorization mechanism.
They catch runaway automation that passes policy checks but submits
tasks faster than intended.

### The two-gate model

The relationship between task acceptance (this ADR) and per-tool-call
authorization (ADR-K8S-019) is complementary:

1. **Gate 1 (task acceptance):** Should this task exist at all? Is the
   caller authorized to create a task for this agent with this budget?
   Evaluated once, at task creation time.

2. **Gate 2 (per-tool authorization):** Should this specific tool call
   proceed? Is the user allowed to invoke this tool with these
   arguments? Evaluated on every tool call during task execution.

The two gates ensure that an external A2A caller who is authorized to
create a task for the Ranger agent cannot transitively invoke tools
that the caller would not be authorized to invoke directly. The task
acceptance gate controls who can delegate to which agents; the tool
authorization gate controls what those agents can do on behalf of the
caller.

## Alternatives considered

**A) Per-tool-call policy only — no task-level gate.**

- Rejected: allows unbounded task creation. A caller can submit
  thousands of tasks, each of which individually passes tool-level
  policy, but collectively overwhelms the cluster and drains budgets.
  Cost and resource control only kicks in after the task is already
  running and consuming resources.

**B) Simple rate limiting — N tasks per minute per caller, no policy
or budget enforcement.**

- Rejected: rate limits are blunt instruments. They cannot distinguish
  a cheap 100-token task from an expensive 100,000-token task. A rate
  limit that permits 10 tasks per minute allows 10 million-token tasks
  per minute, which is catastrophic. Budget enforcement is the
  mechanism that matches cost control to actual resource consumption.

**C) Manual approval for all tasks — a human reviews each task before
execution begins.**

- Rejected: defeats the purpose of autonomous agent-to-agent
  delegation. The A2A protocol exists precisely so that agents can
  delegate to each other without human intervention in the loop. Manual
  approval may be appropriate for specific high-risk task types (and
  the Casbin policy can express "require approval" as a special action),
  but it cannot be the default for all tasks.

**D) Budget enforcement without policy — always accept the task, just
enforce budget limits during execution.**

- Rejected: no ability to restrict which agents a caller can delegate
  to. A caller authorized for the Scribe agent (documentation) should
  not be able to submit tasks to the Warden-at-Arms agent (security
  enforcement) just because they have budget remaining. Authorization
  and budget are orthogonal dimensions; both must be checked.

## Consequences

**Positive:**

- Every task creation is explicitly authorized, budgeted, and audited
  before any execution begins.
- The two-gate model provides defense in depth: task-level gates prevent
  expensive tasks from starting, tool-level gates prevent authorized
  tasks from exceeding their permissions.
- Budget enforcement with three dimensions (tokens, cost, time) catches
  the three most common runaway-task failure modes.
- The audit trail gives operators full visibility into what tasks are
  being created, by whom, and whether they were accepted or rejected.

**Negative:**

- The task acceptance engine is a new component on the critical path of
  every task creation. It must be fast (target: under 10ms for a policy
  evaluation) and reliable (a policy engine failure must fail closed,
  rejecting the task).
- Casbin policy authoring for ABAC is more complex than simple role
  checks. Operators need documentation and examples to write correct
  policies. Misconfigured policies can either over-permit (security
  risk) or over-deny (usability risk).
- Budget tracking adds write load to Postgres on every LLM call and
  tool invocation. This is mitigable with batched writes and
  in-memory accumulation, but adds implementation complexity.

**Trade-offs accepted:**

- We accept the latency cost of policy evaluation on every task
  creation in exchange for authorization and budget enforcement before
  execution begins.
- We accept the complexity of ABAC policy authoring in exchange for the
  expressiveness needed to model multi-tenant, multi-agent, multi-tier
  authorization rules.
- We accept the Postgres write load of continuous budget tracking in
  exchange for real-time cost control that catches runaway tasks before
  they drain budgets.

## References

- Casbin documentation: ABAC (Attribute-Based Access Control) model
- A2A specification: task lifecycle and task creation
- Kubernetes documentation: "Resource Quotas" and "Limit Ranges"
- NIST SP 800-162: Guide to Attribute Based Access Control
- ADR-K8S-014 (six-tier priority system — tier quotas and limits)
- ADR-K8S-019 (tool policy — per-tool-call authorization)
- ADR-K8S-027 (agent catalog — agent trust tiers)
- ADR-K8S-028 (A2A peer endpoint — task lifecycle)
