# ADR-K8S-025 — Sandboxed primitive MCP guests pattern

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Stronghold exposes tools to LLM agents. Some of those tools are simple
HTTP API calls — talk to GitHub, create a Jira ticket, post a Slack
message. Others are fundamentally unsafe at the OS level — execute
arbitrary shell commands, run a Python script, drive a headless browser
through untrusted web pages, read and write files on a filesystem. The
question "should this tool run as an MCP guest server in its own pod, or
as an in-process tool inside the Stronghold-API pod?" has come up
repeatedly, and the lack of a clear decision rule has led to
inconsistent choices.

The clearest example of the inconsistency is the `deployment-mcp-github.yaml`
template introduced in PR-9. That template deploys a GitHub MCP server as
a separate pod with a shared PAT mounted as a secret. This is wrong on
two counts:

1. **Process isolation adds no safety value for an HTTP API call.** The
   GitHub MCP server does not execute untrusted code, does not drive a
   browser, does not touch a filesystem. It makes HTTPS calls to
   `api.github.com`. Running it in a separate pod costs a pod's worth of
   resources, adds network latency for every tool call, and creates a
   new surface to monitor — all for zero isolation benefit.

2. **A shared PAT breaks multi-tenant credential isolation.** If GitHub
   access is a shared-PAT MCP server pod, every user's GitHub tool calls
   go through the same credential. There is no way to use user A's PAT
   for user A's requests and user B's PAT for user B's requests, because
   the MCP server pod has one credential baked in at deploy time. The
   vault (ADR-K8S-018) exists precisely to solve this: per-user
   credentials looked up at call time, injected into the outbound
   request, never shared across users.

The `deployment-mcp-github.yaml` template is gated behind `devMode: true`
in the v0.9 Helm chart and will be replaced by an in-process tool backed
by vault-injected per-user credentials in v0.9.1. But the broader
question remains: when IS it correct to deploy an MCP guest server pod?

The answer comes down to a single criterion: **does the tool need
OS-level process isolation for safety?**

## Decision

**We define three legitimate use cases for deploying a tool as an MCP
guest server in its own pod. Everything else runs as an in-process tool
inside Stronghold-API with vault-injected per-user credentials.**

### Use case 1 — Sandboxed unsafe operations

The tool performs operations where process isolation provides genuine
safety value: executing arbitrary code, driving a browser through
untrusted pages, accessing a scoped filesystem. If a bug or a malicious
input in the tool could crash the process, corrupt memory, escape a
sandbox, or consume unbounded resources, that tool belongs in its own
pod with its own resource limits, its own security context, and its own
blast radius.

Examples: shell execution, Python code evaluation, browser automation
(Playwright/Camoufox), filesystem read/write with tenant scoping.

The key property is that the isolation boundary protects the
Stronghold-API process from the tool, not the other way around. If the
sandbox pod crashes, Stronghold-API continues serving other users. If
the sandbox pod is compromised, the attacker is contained within a pod
that has no access to vault secrets, no access to other tenants' data,
and no network egress beyond what its NetworkPolicy allows.

### Use case 2 — Customer-supplied MCP server images

Enterprise customers may bring their own MCP server images — proprietary
tools that Stronghold orchestrates but does not trust at the code level.
These images run in customer-scoped pods managed by the `mcp-deployer`
controller. Stronghold treats them as untrusted: they run under the
`restricted-v2` SCC, they have no access to the Stronghold-API
ServiceAccount, and their network egress is limited to declared
endpoints.

The distinction from use case 1 is trust: Stronghold wrote the sandbox
pods in use case 1 and trusts their code but not their inputs.
Customer-supplied images are untrusted at both the code and input level.

### Use case 3 — Read-only public-data tools

Tools that access only publicly available data and require no per-user
credential at all. A public documentation search tool, a Wikipedia
lookup, or a public package registry query has no credential to inject
from the vault and no per-user state to manage. Running these as a
shared MCP server pod is acceptable because there is no credential to
isolate and no user-specific data to protect.

These tools are the exception, not the rule. Most tools that seem
"public" actually benefit from per-user context (search personalization,
rate-limit attribution, audit trail). A tool should only be classified
under use case 3 if it genuinely has zero per-user state.

### Everything else — in-process tools

Any tool that calls an HTTP API with a user credential — GitHub, Jira,
Slack, Linear, Notion, PagerDuty, Confluence, Google Drive, AWS, GCP,
Azure — runs as an in-process tool inside Stronghold-API. The request
context carries the authenticated user identity (ADR-K8S-024). The tool
implementation calls the vault to fetch the user's credential for that
service, makes the HTTP call, and returns the result. The entire flow
happens within the Stronghold-API process, under full policy enforcement
(ADR-K8S-019) and full audit coverage.

This is cheaper (no extra pod), faster (no network hop to a sidecar),
more secure (credential never leaves the Stronghold-API process), and
easier to operate (one Deployment to monitor, not N). The only reason
NOT to do this is when the tool's execution itself is unsafe, which
brings us back to use cases 1-3 above.

### The decision rule

Given a new tool to integrate, apply this rule:

1. Does the tool execute untrusted code, drive a browser, or access a
   filesystem where process isolation provides real safety value?
   **Yes** -> MCP guest server pod (use case 1). See ADR-K8S-026 for
   the sandbox pod catalog.

2. Is the tool a customer-supplied MCP server image that Stronghold
   does not trust at the code level? **Yes** -> MCP guest server pod
   (use case 2), managed by `mcp-deployer`.

3. Does the tool access only public data with no per-user credential
   and no per-user state? **Yes** -> MCP guest server pod (use case 3),
   deployed as a shared service.

4. None of the above? **In-process tool** with vault-injected per-user
   credentials. This is the default path and should cover the majority
   of integrations.

## Alternatives considered

**A) All tools as MCP guest server pods — one pod per tool type.**

- Rejected: this is the "microservice every tool" approach. It costs a
  pod per tool type (or per tool type per tenant), adds a network hop
  per tool call, and — critically — breaks per-user credential isolation.
  Each pod would need either vault access (expanding the blast radius)
  or a shared credential (breaking multi-tenancy). For API-calling tools,
  process isolation adds cost without safety value. The only tools that
  benefit from process isolation are the ones that run untrusted code.

**B) All tools in-process — no MCP guest server pods at all.**

- Rejected: running `exec()`, `eval()`, or a headless browser inside
  the Stronghold-API process is a non-starter. A kernel exploit in a
  code-execution tool escapes the process boundary and compromises the
  entire platform. A runaway browser session that OOMs takes down the
  API pod and every user on it. Process isolation for unsafe operations
  is not optional — it is the reason containers exist.

**C) No explicit decision rule — decide case by case.**

- Rejected: case-by-case decisions produce the exact inconsistency we
  already observed with the GitHub MCP server template. Without a rule,
  each team member applies their own heuristic. Some deploy everything
  as pods (wasting resources), others keep everything in-process
  (risking safety). An explicit rule eliminates the ambiguity: if the
  tool runs untrusted code, it gets a pod; if it calls an API, it stays
  in-process.

## Consequences

**Positive:**

- The decision rule is simple and deterministic. Given a new tool, the
  answer to "pod or in-process?" follows directly from the rule without
  debate.
- Per-user credential isolation is enforced by default. In-process tools
  get vault-injected credentials scoped to the requesting user. No
  shared-PAT pods exist in production.
- The number of MCP guest server pods stays small — only the sandbox
  types from ADR-K8S-026, customer-supplied images, and a handful of
  public-data tools. The cluster is not overrun with one-pod-per-API
  deployments.
- Audit coverage is complete for in-process tools because the tool
  execution happens within the Stronghold-API process where the audit
  middleware runs. Guest server pods emit their own audit events via the
  audit sidecar pattern.

**Negative:**

- In-process tools share the Stronghold-API process's resource limits.
  A poorly written in-process tool that blocks the event loop or leaks
  memory affects all users on that replica. Mitigated by timeouts,
  circuit breakers, and the existing per-request resource tracking.
- The existing `deployment-mcp-github.yaml` template must be deprecated
  and replaced, which is a migration cost for anyone who deployed it
  in dev mode.
- Customer-supplied MCP server images (use case 2) require the
  `mcp-deployer` controller to manage their lifecycle, which is
  additional infrastructure to build and operate.

**Trade-offs accepted:**

- We accept the risk of in-process tool faults affecting the API process
  in exchange for per-user credential isolation and operational
  simplicity. The risk is mitigated by timeouts and circuit breakers,
  and it only applies to HTTP-calling tools — the actually dangerous
  tools (code exec, browser) run in their own pods.
- We accept the migration cost of replacing the GitHub MCP server
  template in exchange for establishing a clean decision rule early,
  before more shared-PAT templates proliferate.

## References

- MCP specification: "Architecture" (client, server, transport)
- Kubernetes documentation: "Pod Security Standards"
- Kubernetes documentation: "Network Policies"
- ADR-K8S-018 (vault — per-user credential storage and injection)
- ADR-K8S-019 (tool policy — per-user and per-tenant permission rules)
- ADR-K8S-024 (MCP transport and auth — user identity propagation)
- ADR-K8S-026 (sandbox pod catalog — the specific sandbox types)
