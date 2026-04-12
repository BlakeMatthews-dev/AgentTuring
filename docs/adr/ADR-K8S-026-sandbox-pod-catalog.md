# ADR-K8S-026 — Sandbox Pod Catalog

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

ADR-K8S-025 established the rule: tools that need OS-level process
isolation for safety run as MCP guest server pods; everything else runs
in-process. This ADR answers the follow-up question: what sandbox pod
types does Stronghold ship, what security profile does each get, and how
does the `mcp-deployer` controller know how to spawn them?

When a Stronghold agent needs to execute code, drive a browser, or
access a scoped filesystem, it invokes a tool (`shell.exec`,
`python.eval`, `browser.navigate`). From the LLM's perspective, these
are tools like any other — the agent calls them, gets a result, and
continues reasoning. From the platform's perspective, the tool
invocation triggers the creation (or reuse) of a sandbox pod that
performs the actual work in isolation. The sandbox pod runs an MCP guest
server inside it; the Stronghold-API pod connects to it as an MCP
client, sends the tool call, receives the result, and tears down the
pod (or returns it to a pool, depending on lifecycle policy).

The problem with ad-hoc pod specs is that every team building an agent
would invent its own pod template: different base images, different
security contexts, different resource limits, different network policies.
Some would forget to set `readOnlyRootFilesystem`. Some would request
10 GB of memory for a shell that runs `ls`. The result is an
inconsistent, hard-to-audit sprawl of pod shapes with no shared
security baseline.

A catalog solves this by providing a fixed set of pre-defined sandbox
templates, each with a specific security profile, resource envelope, and
lifecycle policy. Agent developers pick from the catalog; they do not
write pod specs. The `mcp-deployer` controller reads the catalog and
materializes pods from the templates. Security review happens once per
template, not once per agent.

## Decision

**Stronghold ships a pre-defined catalog of sandbox pod templates. The
`mcp-deployer` controller spawns pods from these templates on demand.
Each template defines a base image, security context, resource limits,
network policy, lifecycle policy, and the MCP server binary it runs.**

### The catalog

| Template | Purpose | Lifecycle | CPU / Mem | Timeout | Network egress |
|----------|---------|-----------|-----------|---------|----------------|
| `sandbox.shell` | Allow-listed binaries + scoped filesystem | per-call | 1 / 512Mi | 30s | DNS allow-list |
| `sandbox.python` | Restricted Python 3.12 interpreter | per-call | 2 / 1Gi | 60s | None (default) |
| `sandbox.browser` | Camoufox + Playwright headless | per-session | 2 / 2Gi | 15min session | Public internet, no cluster |
| `sandbox.filesystem` | Tenant-scoped PVC read/write | per-call | 0.5 / 256Mi | 30s | None |
| `sandbox.k8s` | kubectl + scoped kubeconfig | per-call | 0.5 / 256Mi | 30s | API server only |
| `sandbox.network` | curl + DNS allow-list | per-call | 0.5 / 256Mi | 30s | DNS allow-list |

**`sandbox.shell`** includes `bash`, `sh`, `cat`, `grep`, `sed`, `awk`,
`jq`, `curl`, and `git` — no compilers, no package managers, no `sudo`.
A writable tmpfs at `/workspace` (default 256 MB) is the only mutable
storage; everything else is read-only. Each invocation creates a pod,
runs the command, returns stdout/stderr/exit-code, and destroys the pod.
The execution timeout is enforced by the MCP server binary; the pod's
`activeDeadlineSeconds` (60s) is a backstop.

**`sandbox.python`** ships Python 3.12 with a curated library set
(`requests`, `numpy`, `pandas`, `pydantic`, `httpx`) and no `pip`. Each
invocation gets a fresh interpreter with no carryover state. The MCP
server wrapper enforces a 50 MB output cap to prevent unbounded output
from autonomous agents. No network egress by default; agents that need
to fetch data use `sandbox.network` or request a per-tenant egress
policy exception.

**`sandbox.browser`** runs Camoufox (a hardened Firefox fork) with
Playwright. It is the only per-session sandbox: the pod persists for
the session (up to 15 minutes) so multi-step browsing workflows avoid
paying browser startup on every call. Requires `shm_size: 2 GB` to
prevent OOM in headless mode. Network egress is open to the public
internet (the point of a browser) but blocked to cluster-internal
services by NetworkPolicy, preventing use as an internal proxy. The MCP
server caps screenshots at 5 MB and extracted text at 1 MB.

**`sandbox.filesystem`** mounts a tenant-scoped PVC at `/data`. The PVC
persists independently of the pod, so tenant files survive across calls.
No network egress — completely air-gapped. PVC size is configurable per
tenant (default 1 GB, maximum 10 GB).

**`sandbox.k8s`** includes `kubectl` and `helm` (read-only mode). A
scoped kubeconfig grants `get`, `list`, and `watch` on common resources
in the tenant's namespace only. Egress is restricted to the Kubernetes
API server endpoint.

**`sandbox.network`** provides `curl`, `wget`, `dig`, `nslookup`, and
`jq` with egress restricted to a per-tenant DNS allow-list. It exists
because other sandbox types default to no network access. Output is
capped at 5 MB to prevent large file downloads.

### Common security baseline

All sandbox templates share these properties:

- Run under the `restricted-v2` Pod Security Standard (or equivalent
  SCC on OpenShift): `runAsNonRoot`, no privilege escalation, all
  capabilities dropped, seccomp profile `RuntimeDefault`.
- `readOnlyRootFilesystem: true` on every container, with explicitly
  declared writable mounts (tmpfs for `/workspace` or `/tmp`, PVC for
  `/data` where applicable).
- Resource limits enforced via `LimitRange` in the sandbox namespace.
  No sandbox pod can exceed its template's ceiling.
- `ResourceQuota` on the sandbox namespace caps concurrent sandbox pods
  per tenant (default 5, configurable in the Helm values).
- Every sandbox pod emits audit events (tool call inputs and outputs)
  to the Stronghold audit trail, tagged with the originating user
  identity from ADR-K8S-024.

### Catalog registration and lifecycle

The catalog is defined in the Helm chart's `values.yaml` under the
`sandbox.catalog` key, one entry per template specifying image, lifecycle
policy, resource limits, and timeout. The `mcp-deployer` controller
reads this catalog at startup. When a tool call arrives that maps to a
sandbox type, the controller materializes a pod from the template, waits
for readiness, connects to its MCP server, forwards the tool call,
collects the result, and (for per-call lifecycle) destroys the pod.
Per-session pods (browser) are pooled and reused within the session, then
destroyed when the session ends or the maximum lifetime expires.

## Alternatives considered

**A) In-process sandboxing via Python subprocess with resource limits.**

- Rejected: `subprocess` with `resource.setrlimit` provides per-process
  caps, but a kernel exploit escapes the process boundary into the
  Stronghold-API container's namespace — with access to its secrets, its
  ServiceAccount token, and its network identity. Pod-level isolation
  (separate cgroup, network namespace, mount namespace) is a
  fundamentally stronger boundary.

**B) Docker-in-Docker — nested Docker daemon inside Stronghold-API.**

- Rejected: DinD requires privileged mode or a bind-mounted Docker
  socket, both of which give the pod effective root on the host.
  Kubernetes provides pod-level isolation natively; adding a nested
  container runtime gains nothing and opens a severe attack surface.

**C) Firecracker or gVisor micro-VMs for stronger isolation.**

- Rejected for v0.9, documented as a future upgrade path. Firecracker
  provides VM-level isolation at near-container startup times; gVisor
  intercepts syscalls via a user-space kernel. Both add operational
  complexity (KVM access for Firecracker, custom RuntimeClass for
  gVisor) beyond what v0.9 on a homelab k3s cluster requires. When
  Stronghold targets multi-node production clusters with untrusted
  tenants, this becomes the right choice.

**D) No catalog — ad-hoc pod specs per agent team.**

- Rejected: inconsistent security contexts, resource limits, and
  network policies. A catalog provides a single security review surface:
  six templates hardened once, reused everywhere. New sandbox types
  require a deliberate catalog entry, not a drive-by pod spec.

## Consequences

**Positive:**

- Agent developers pick from six sandbox types instead of writing pod
  specs. This eliminates an entire class of security misconfigurations.
- Security review scales: six templates reviewed once, not N ad-hoc
  specs per agent. Policy changes propagate to six places, not across
  the entire codebase.
- Resource accounting is predictable — capacity planning reduces to
  counting expected concurrent pods per type times their template limits.
- The `mcp-deployer` controller has a well-defined contract: read the
  catalog, materialize pods, manage lifecycle. No ad-hoc security
  decisions at runtime.

**Negative:**

- Six sandbox images must be built, versioned, and maintained, each
  with its own dependency tree. Image maintenance is ongoing work.
- The catalog is intentionally restrictive. A sandbox type not in the
  catalog requires a Helm chart update and a security review. This is
  the security property, but it will occasionally slow development.
- Per-call lifecycle means pod creation latency on every tool call (1-3
  seconds warm, 10+ seconds cold). Mitigated by pre-pulling images on
  all nodes via a DaemonSet.

**Trade-offs accepted:**

- We accept image maintenance burden in exchange for a consistent,
  auditable security baseline across all sandbox workloads.
- We accept per-call pod creation latency in exchange for the guarantee
  that no state leaks between tool calls (except browser, which uses
  per-session lifecycle by design).
- We defer Firecracker/gVisor to a future release in exchange for
  shipping v0.9 with standard pod isolation adequate for the current
  threat model.

## References

- Kubernetes documentation: "Pod Security Standards" (Restricted profile)
- Kubernetes documentation: "Resource Management for Pods and Containers"
- Kubernetes documentation: "LimitRange" and "ResourceQuota"
- Kubernetes documentation: "Network Policies"
- OpenShift documentation: "SecurityContextConstraints" (restricted-v2)
- Camoufox project documentation (hardened Firefox for automation)
- Firecracker documentation: "Design" (micro-VM architecture)
- gVisor documentation: "Architecture Guide" (user-space kernel)
- ADR-K8S-002 (RBAC boundary)
- ADR-K8S-025 (sandboxed guest pattern — the decision rule for when to
  use a sandbox pod)
- ADR-K8S-024 (MCP transport and auth — user identity for audit)
