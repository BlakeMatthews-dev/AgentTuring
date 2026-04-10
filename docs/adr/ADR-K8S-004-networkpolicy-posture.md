# ADR-K8S-004 — NetworkPolicy posture

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

By default, Kubernetes pods can talk to any other pod in the cluster on any
port. This is a permissive posture that fails to contain a compromised pod —
once an attacker has code execution in any container, they have network reach
to every other service in the cluster, including the database, the gateway,
the secrets controller, and other tenants' workloads.

NetworkPolicy is the Kubernetes primitive for restricting pod-to-pod traffic.
Properly used, it implements zero-trust networking inside the cluster: a pod
can only reach the destinations explicitly allowed by a NetworkPolicy that
selects it.

The current state of the prior single-node deployment uses a CNI that does not
enforce NetworkPolicy at all — its default networking layer silently no-ops
policy resources, so any policies we write would have zero effect. The
migration to OKD (see ADR-K8S-006) gives us OVN-Kubernetes, which enforces
NetworkPolicy correctly.

We need to decide:

- What posture do we adopt? Permissive-by-default (current) or deny-by-default?
- How do we represent the allow rules so they're auditable and don't drift?
- How do we test that policies are actually enforced and not silently ignored?
- How do we handle DNS, the Kubernetes API, and other infrastructure traffic?

## Decision

We will adopt **default-deny per namespace plus an explicit-allow decision
matrix**, enforced by OVN-Kubernetes on OKD and by the customer's CNI on other
distros (with a chart pre-install hook that verifies the CNI actually enforces).

### Posture rules

1. **Default-deny ingress and egress in every Stronghold namespace.** A
   `NetworkPolicy` named `default-deny-all` is installed in
   `stronghold-platform`, `stronghold-data`, `stronghold-mcp`, and every
   `stronghold-tenant-<id>` namespace by the Helm chart. The `stronghold-system`
   namespace is excluded because the operators it hosts (cert-manager, sealed-
   secrets, OADP) need their own policies which the operators install
   themselves.

2. **Every allowed flow is an explicit `NetworkPolicy` selector pair**:
   - Source: pod label selector + namespace label selector
   - Destination: pod label selector + port + protocol
   - No wildcards beyond what's needed for DNS and the Kubernetes API server

3. **DNS is always allowed** via a single namespace-wide policy:
   `allow-dns-egress` lets all pods in the namespace reach `kube-system/coredns`
   on UDP and TCP port 53. Without this, nothing in the namespace can resolve
   any hostname.

4. **Kubernetes API access is allowed only for pods that need it.** The
   `mcp-deployer-sidecar` and the cert-manager / sealed-secrets / Velero
   operator pods get an explicit `allow-kube-apiserver-egress` policy. All
   other pods cannot reach the API server.

5. **Cross-tenant traffic is denied.** The per-tenant default-deny is enough
   to block this, but each tenant namespace also installs an explicit
   `deny-cross-tenant-ingress` policy as belt-and-braces, in case a future
   `allow-from-platform` policy is misconfigured.

### The decision matrix CSV

The single source of truth for which flows are allowed is
`deploy/helm/stronghold/network-policy-matrix.csv`, with columns:

```
source_namespace,source_pod_selector,destination_namespace,destination_pod_selector,port,protocol,justification,owner
```

Initial rows for v0.9 (single-tenant):

| Source | Dest | Port | Justification |
|---|---|---|---|
| `stronghold-platform` / `app=litellm` | `stronghold-mcp` / `tier=mcp` | 8000/TCP | gateway → MCP tool calls |
| `stronghold-platform` / `app=stronghold-api` | `stronghold-platform` / `app=litellm` | 4000/TCP | API → gateway model proxy |
| `stronghold-platform` / `app=stronghold-api` | `stronghold-data` / `app=postgres` | 5432/TCP | API → memory + state |
| `stronghold-platform` / `app=stronghold-api` | `stronghold-platform` / `app=phoenix` | 6006/TCP | API → trace export |
| `stronghold-mcp` / `app=mcp-deployer-sidecar` | (kube-apiserver) | 443/TCP | scoped Deployments in stronghold-mcp |
| `*` (all stronghold-* namespaces) | `kube-system` / `k8s-app=kube-dns` | 53/UDP, 53/TCP | DNS resolution |
| `*` (all stronghold-* namespaces) | `*` | * | **deny-by-default** |

The CSV is the source-of-truth. The Helm chart renders it into NetworkPolicy
manifests via a template helper. **The CSV must be updated whenever a new
component is added that needs to talk over the network.** A CI lint check
fails the build if a Deployment with a Service is added but no matching CSV
row exists.

### Enforcement verification

A NetworkPolicy is only useful if it's actually enforced. The chart has two
verification mechanisms:

1. **Pre-install hook**: a Helm `pre-install` Job runs a probe pod that tries
   to connect to a target pod under a known-deny rule. If the connection
   succeeds, the CNI is not enforcing NetworkPolicy and the install fails fast
   with a clear error. This catches CNIs that silently accept NetworkPolicy
   resources without actually enforcing them.

2. **CI smoke test** (PR-14, the e2e workflow): after `helm install`, spawn
   a probe pod in a separate namespace and assert it cannot reach the
   `stronghold-api` service. The test is designed to fail if enforcement is
   absent — `assert connection refused`, not `assert no error`.

## Alternatives considered

**A) Permissive-by-default with explicit deny rules.**

- Rejected: this is the current state, and it's a security failure mode. New
  components added in the future would default to "can talk to everything",
  which means a single forgotten deny rule creates a cluster-wide breach
  vector. Default-deny is the only posture that fails safely.

**B) Default-deny but no decision matrix CSV — write each NetworkPolicy by
hand.**

- Rejected: drift. Within six months the manifests would diverge from
  reality. The CSV gives us a single audit surface and a forcing function for
  CI to lint against.

**C) Use a service mesh (Istio, Linkerd, Cilium L7) instead of NetworkPolicy.**

- Rejected for v0.9: adds significant operational complexity and is
  unnecessary at our scale. NetworkPolicy is sufficient for L4 enforcement.
  We document service mesh as a future option for v1.3+ if Stronghold ever
  needs L7-level enforcement (e.g., for Warden's per-request policy
  decisions in a horizontally-scaled topology — see ADR-K8S-005).

**D) Cluster-wide AdminNetworkPolicy (alpha in Kubernetes 1.29+).**

- Rejected for v0.9: still alpha, not GA on OKD 4.14. Worth revisiting in
  v1.0+ if it goes GA and offers better central enforcement than the
  per-namespace default-deny pattern.

## Consequences

**Positive:**

- Zero-trust networking inside the cluster: a compromised MCP server cannot
  reach Postgres or the gateway except via the explicit allow flow.
- Audit story: one CSV file shows every allowed flow in the cluster, with
  justification and owner per row.
- The pre-install enforcement check catches the silent-CNI failure mode that
  the prior single-node deployment was running on.
- Multi-tenant isolation gets the same primitive — per-tenant namespaces
  inherit default-deny automatically (see ADR-K8S-008).

**Negative:**

- Adding a new service requires updating the CSV AND the Helm template.
  Mitigated by the CI lint that flags missing rows.
- DNS misconfigurations cause cryptic failures (services can't resolve
  hostnames). Mitigated by the always-on `allow-dns-egress` policy and the
  smoke test that catches it.
- Some debugging requires running `oc rsh` inside a pod to test connectivity
  manually, since `kubectl port-forward` doesn't traverse NetworkPolicy.

**Trade-offs accepted:**

- Template + matrix maintenance overhead in exchange for hard-default zero-
  trust networking.

## References

- Kubernetes documentation: "Network Policies" — kubernetes.io/docs/concepts/services-networking/network-policies/
- OpenShift Container Platform 4.14 documentation: "About network policy"
- OpenShift Container Platform 4.14 documentation: "OVN-Kubernetes default CNI network provider"
- NIST SP 800-207 (Zero Trust Architecture) §3.4.1 (network microsegmentation)
- CIS Kubernetes Benchmark v1.9.0 §5.3 (Network Policies and CNI)
- BSI Grundschutz APP.4.4 §A.4.4.A19 (network segmentation)
- Kubernetes Network Special Interest Group: "Network Policy v2 design"
