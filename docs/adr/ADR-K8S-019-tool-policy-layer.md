# ADR-K8S-019 — Tool Policy Layer (Casbin) — call-level and task-level gates

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Stronghold mediates tool access for both in-process tools (compiled into
the Stronghold-API binary) and MCP guest pass-through (tools served by
external MCP servers that Stronghold proxies with governance). In the
current implementation, if a user can authenticate to Stronghold, they can
call any tool. There is no policy layer between "user is logged in" and
"user may invoke this specific tool for this specific purpose".

This gap matters along three dimensions.

**Least privilege.** A junior developer on tenant A should be able to run
`code-search` but not `code-write`. A finance user should be able to query
JIRA but not push commits to GitHub. Today there is no mechanism to express
these distinctions — every authenticated user sees every tool in the
catalog.

**Multi-tenant isolation.** Tenant A's tools should not be visible to
tenant B's users. Without a policy gate, a user on tenant B could discover
and invoke a tool registered by tenant A's MCP server — a cross-tenant
data leak vector.

**Task-level budget control.** When a user submits an agentic mission
(ADR-K8S-013, surface 2), the mission may spawn sub-tasks that consume
tokens, call paid APIs, and run for hours. Without a policy gate at
task-creation time, any user can submit arbitrarily expensive missions.
The quota system catches overruns after the fact, but it cannot prevent a
user from creating a task that is structurally over-budget before it
starts.

Stronghold needs a policy layer that evaluates two kinds of decisions:

1. **Per-tool-call**: given a user, tenant, tool name, stated purpose, and
   current context, should this call be allowed?
2. **Per-task-creation**: given a user, tenant, agent strategy, task spec,
   and budget estimate, should this task be created?

Both decisions must be evaluated in-process on the hot path — a network
round-trip to an external policy service adds latency that the P0 chat
tier (sub-2-second p99) cannot afford.

## Decision

**Embed Casbin (Apache 2.0 license) as an in-process policy engine inside
the Stronghold-API process.** Casbin evaluates two policy gates — one at
tool-call time, one at task-creation time — using an ABAC model that reads
policy definitions from a YAML file and runtime overrides from Postgres.

### Gate 1 — per-tool-call

Every tool invocation passes through the tool-call gate before the tool
handler executes:

```
(user_id, tenant_id, tool_name, purpose, context) -> allow | deny
```

- `user_id` — the authenticated user making the request
- `tenant_id` — the tenant the user belongs to
- `tool_name` — the canonical tool identifier (e.g., `github.create_pr`)
- `purpose` — the classifier's assessed purpose of the tool call
- `context` — additional attributes: time of day, request priority tier
  (ADR-K8S-014), whether the call originates from a mission or from chat

A denied tool call returns a structured error explaining which policy
blocked it. The denial is logged to Phoenix with the full request context.

### Gate 2 — per-task-creation

When a user submits a mission via Conduit (ADR-K8S-013), the task-creation
gate evaluates before the mission pod is spawned:

```
(user_id, tenant_id, agent_strategy, task_spec, estimated_budget) -> allow | deny
```

A denied task creation returns a structured error (e.g., "budget exceeds
your tier's per-mission limit" or "your role does not permit
delegate-strategy missions").

### Policy definition

Policies are defined in `config/tool_policy.yaml`, shipped as a ConfigMap.
The file uses Casbin's ABAC model syntax with a custom YAML adapter:

```yaml
policies:
  - effect: allow
    subjects:
      roles: [developer, admin]
      tenants: ["*"]
    actions:
      tools: [github.*, jira.search_*, code_search]
    conditions:
      priority_tier: [P0, P1, P2]

  - effect: deny
    subjects:
      roles: [viewer]
    actions:
      tools: [github.create_pr, github.merge_pr, jira.create_issue]

  - effect: allow
    subjects:
      roles: [admin]
    actions:
      task_creation:
        strategies: [react, plan_execute, delegate]
        max_budget_usd: 50.00
```

Runtime overrides (e.g., a tenant admin granting a specific user access to
a tool their role does not normally permit) are stored in Postgres and
loaded into the Casbin enforcer on startup and on a configurable refresh
interval (default: 60 seconds). Policy changes propagate without pod
restarts, with a bounded staleness window.

### Performance characteristics

Casbin's in-process enforcer evaluates policies in microseconds — the
library maintains an in-memory model and makes no network calls during
evaluation. For the P0 chat tier, the policy gate adds less than 1
millisecond to the request path.

### Audit integration

Every policy decision — allow or deny — is logged to Phoenix as a
structured span attached to the parent request trace. The span includes
the full input tuple, the matching policy rule (or "no match" for
default-deny), and the decision.

## Alternatives considered

**A) OPA (Open Policy Agent) with Rego.**

OPA is the industry standard for policy-as-code in Kubernetes. However,
OPA is designed as a sidecar or standalone service — policy evaluation
requires an HTTP round-trip to the OPA process. For the P0 chat tier,
this round-trip adds measurable latency: OPA's own benchmarks show 1-5ms
per evaluation for moderate policy sets, plus network overhead. The
sidecar model also means an additional container per pod and an additional
failure mode. OPA can be embedded as a Go library, but Stronghold-API is
a Python application; the Python OPA bindings (via WASM or subprocess) add
complexity and reduce the performance advantage of in-process evaluation.

- Rejected: sidecar latency on the hot path, additional failure mode,
  and awkward Python integration for a library designed for Go sidecars.

**B) Cedar (AWS).**

Cedar has formal verification properties and a clean syntax, but the
Python SDK is less mature than Casbin's — as of early 2026, the Python
Cedar evaluator is a WASM binding with limited community adoption outside
AWS-native deployments. The entity model is AWS-centric and requires
translation for Stronghold's user/tenant/tool/purpose tuple.

- Rejected: smaller Python ecosystem, WASM binding complexity, and
  AWS-centric entity model.

**C) Hand-rolled authorization logic.**

Write `if/elif` chains in the tool dispatcher that check user roles and
tenant membership before each tool call. This works until the policy
surface grows beyond a handful of rules. Stronghold's tool catalog already
has 30+ tools, and the role/tenant/tool/purpose combinations grow
combinatorially. Hand-rolled authorization becomes a maintenance burden
with no formal model to audit.

- Rejected: brittle, no formal model, hard to audit, does not scale with
  the tool catalog.

**D) No policy layer — rely on authentication and quota only.**

Quota controls cost but not capability. A user with remaining quota can
call any tool, including tools that access data outside their role's scope.
Authentication tells you who the user is; authorization tells you what
they may do. Skipping authorization is not a defensible security posture
for a multi-tenant platform.

- Rejected: conflates cost control with access control, violates
  least-privilege, and leaves multi-tenant tool isolation unaddressed.

## Consequences

**Positive:**

- Stronghold can express and enforce "user X in tenant Y may call tool Z
  for purpose W" — the fundamental multi-tenant authorization primitive.
- Task-creation gates prevent structurally over-budget missions before
  they consume any resources.
- Policy definitions in YAML are auditable, version-controlled, and
  diffable — operators can review policy changes in pull requests.
- In-process evaluation adds negligible latency to the hot path.
- Phoenix traces include policy decisions, making denial debugging a
  trace lookup rather than a log grep.

**Negative:**

- Casbin's ABAC model has a learning curve. Operators familiar with
  Kubernetes RBAC (role-based, not attribute-based) will need to
  understand how subject/action/condition tuples compose.
- The 60-second refresh interval for runtime overrides means there is a
  bounded window where a newly granted permission is not yet active.
- Policy misconfiguration (overly broad allow rules, missing deny rules)
  is a security risk. Mitigation: a `policy-lint` CI check validates the
  YAML against a schema and warns on wildcard grants.

**Trade-offs accepted:**

- We accept the dependency on Casbin (a well-maintained Apache 2.0
  library) in exchange for a formal policy model that scales with the
  tool catalog.
- We accept ABAC complexity over simpler RBAC because the authorization
  decisions involve attributes (purpose, budget, context) that pure
  role-based checks cannot express.
- We accept bounded staleness on runtime policy overrides in exchange for
  not requiring a pod restart on every policy change.

## References

- Casbin documentation: https://casbin.org/docs/overview
- Casbin ABAC model: https://casbin.org/docs/abac
- NIST SP 800-162: "Guide to Attribute Based Access Control (ABAC)
  Definition and Considerations"
- Kubernetes documentation: "Using RBAC Authorization"
- ADR-K8S-013 (hybrid execution model), ADR-K8S-014 (six-tier priority
  system), ADR-K8S-018 (per-user credential vault)
