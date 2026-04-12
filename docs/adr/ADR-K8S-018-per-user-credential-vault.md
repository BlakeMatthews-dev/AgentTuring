# ADR-K8S-018 — Per-user credential vault (OpenBao)

**Status:** Proposed
**Date:** 2026-04-09
**Deciders:** Stronghold core team

## Context

Stronghold's MCP tools — GitHub, JIRA, Slack, Linear, Notion, and others —
need per-user credentials to act on behalf of individual users. The current
model uses shared PATs: one GitHub token for all users, one Slack bot token
for all tenants, one JIRA service account for the entire cluster. This
works for prototyping but fails along three axes in production.

First, **audit identity is wrong**. When Stronghold calls the GitHub API
with a shared PAT, every commit, PR comment, and issue mutation is
attributed to the PAT owner, not to the user who asked the agent to do it.
Compliance teams cannot answer "who did what" because the answer is always
"the service account".

Second, **permission escalation is silent**. A shared PAT scoped to one
repository grants the same access to every user on every tenant. If the
PAT has `repo:write` on a sensitive repository, any user who can invoke the
GitHub MCP tool gets that access — even users who should only have
read-only on that repo. There is no per-user scoping because there is only
one credential.

Third, **revocation is all-or-nothing**. When a user leaves a tenant, the
only way to revoke their tool access is to rotate the shared PAT, which
breaks every other user simultaneously. Per-user credentials allow
revocation of a single user's vault path without touching anyone else.

Per ADR-K8S-025 (PAT-based API tools become in-process Stronghold tools),
all MCP tools that call external APIs will migrate from carrying their own
credentials to requesting credentials from a central vault at call time.
This ADR defines that vault.

The homelab cluster (k3s on VM 301, single node, 32 GB RAM, 10 vCPU) is
resource-constrained. Whatever we deploy must run lean. OpenBao is a Go
binary with a memory footprint measured in hundreds of megabytes, which
fits comfortably.

## Decision

**Deploy OpenBao (Linux Foundation fork of HashiCorp Vault, MPL 2.0
license) in the `stronghold-system` namespace, using the Kubernetes auth
method with projected ServiceAccount tokens, and organize per-user secrets
under a path convention that encodes both user and service identity.**

### Deployment topology

OpenBao runs as a single-replica StatefulSet in `stronghold-system` with
the integrated Raft storage backend on a PersistentVolumeClaim. In the
homelab this lands on ZFS NVMe via the local-path provisioner — fast
enough for a write-light, read-moderate vault workload. When the cluster
grows to multiple nodes, the StatefulSet scales to 3 replicas for Raft
quorum; the Helm chart parameterizes `replicaCount` so the upgrade is a
values change, not a template rewrite.

### Authentication method

OpenBao's Kubernetes auth method validates projected ServiceAccount tokens
issued by the cluster's TokenRequest API. When a Stronghold-API pod needs
to read a user's credentials, it presents its projected token to OpenBao,
which verifies the token against the Kubernetes API server, confirms the
pod's ServiceAccount and namespace, and returns a short-lived vault token
scoped to the policies the ServiceAccount is bound to.

No long-lived vault tokens are stored anywhere. The unseal keys are split
via Shamir secret sharing (3-of-5 threshold) and stored outside the
cluster in the operator's password manager.

### Secret path convention

All per-user credentials live under:

```
stronghold/users/<user_id>/services/<service_name>
```

For example:
- `stronghold/users/u-abc123/services/github` — GitHub PAT or OAuth token
- `stronghold/users/u-abc123/services/jira` — JIRA API token
- `stronghold/users/u-abc123/services/slack` — Slack user token

Tenant-wide credentials (bot tokens, webhook secrets) live under:

```
stronghold/tenants/<tenant_id>/services/<service_name>
```

This two-level hierarchy means a vault policy can grant a Stronghold-API
pod read access to `stronghold/users/*` while denying access to
`stronghold/tenants/*/services/billing` (tenant billing secrets that only
the billing service should read).

### Lease management

Every secret read from OpenBao returns a lease with a 1-hour default TTL.
The consuming code (the MCP tool handler inside Stronghold-API) holds the
lease in memory for the duration of the tool call and does not cache the
credential beyond the call. If a tool call runs longer than 1 hour (some
agentic missions do), the handler renews the lease before expiry.

Short leases mean that rotating a user's credential in the vault takes
effect within 1 hour at most, without restarting any pods. For immediate
revocation, the operator revokes the lease explicitly via the OpenBao API.

### Audit logging

OpenBao's audit device writes JSON audit logs to stdout, which the
cluster's log collector ships to Phoenix. Every secret read, write,
renewal, and revocation is logged with the requesting ServiceAccount,
namespace, source IP, and vault path. The audit log does **not** contain
secret values — OpenBao HMACs the secret payloads by default.

### Helm chart integration

The OpenBao deployment is managed by a Helm subchart vendored under
`charts/openbao/`. The parent chart's `values.yaml` exposes:

```yaml
openbao:
  enabled: true
  server:
    replicaCount: 1
    resources:
      requests: { cpu: 100m, memory: 256Mi }
      limits:   { memory: 512Mi }
    auditDevice: { enabled: true, type: file, path: stdout }
  injector:
    enabled: false
```

The injector sidecar is disabled. Stronghold-API reads credentials via
the OpenBao HTTP API directly, not via sidecar injection, avoiding the
init-container ordering issues that plague vault-agent-injector.

## Alternatives considered

**A) HashiCorp Vault (enterprise or community).**

HashiCorp relicensed Vault under BSL 1.1 in August 2023. The BSL
prohibits offering Vault as a managed service, and the license change
signals a direction that makes long-term dependency risky. OpenBao is
API-compatible, MPL 2.0 licensed, and maintained by the Linux Foundation.

- Rejected: license incompatibility with Stronghold's open-source
  deployment model and long-term risk of further BSL restrictions.

**B) Conjur OSS (CyberArk).**

Conjur's development velocity has slowed significantly, its community is
small, and its primary focus is CyberArk's commercial PAM product line.
The Kubernetes auth integration is less mature than OpenBao's.

- Rejected: low development velocity, small community, and commercial
  focus make it a risky long-term dependency.

**C) Kubernetes Secrets only (no external vault).**

This approach fails on four counts: (1) no lease management — a Secret
is valid until explicitly deleted; (2) no audit trail tied to application-
level user identity; (3) no dynamic secrets — generating short-lived
tokens requires a separate controller anyway; (4) no per-user namespacing
— RBAC on Secrets is per-namespace, not per-key.

- Rejected: no leases, no user-level audit, no dynamic secrets, and no
  per-user access control within a namespace.

**D) Infisical.**

Infisical's dynamic secrets engine is less mature than OpenBao's, its
community is smaller, and its self-hosted deployment requires a MongoDB
backend — an additional stateful dependency the homelab does not need.

- Rejected: less mature dynamic secrets, smaller community, and MongoDB
  dependency for no clear benefit over OpenBao.

## Consequences

**Positive:**

- Every MCP tool call that touches an external API uses a per-user
  credential, so audit logs correctly attribute actions to the user who
  initiated them.
- Revoking a user's access is a single vault path deletion — no PAT
  rotation, no pod restart, no impact on other users.
- Short-lived leases bound the credential exposure window to 1 hour.
- The OpenBao audit log provides a complete, HMAC-protected record of
  every credential access.
- MPL 2.0 licensing removes the BSL risk of HashiCorp Vault.

**Negative:**

- OpenBao is a new stateful component to operate — unsealing after node
  restarts, monitoring Raft health, backing up the storage backend.
- The Shamir unseal ceremony is a manual step on cold start. Auto-unseal
  via a cloud KMS is not available on the homelab.
- Stronghold-API gains a runtime dependency on OpenBao availability. If
  OpenBao is down, credentialed tool calls fail. Mitigation: the health
  endpoint is checked by a readiness probe on the Stronghold-API pod.

**Trade-offs accepted:**

- We accept the operational burden of a stateful vault in exchange for
  per-user credential isolation, short-lived leases, and a real audit
  trail.
- We accept manual unsealing on the homelab in exchange for not depending
  on a cloud KMS that does not exist in this environment.
- We accept the OpenBao fork's smaller community (relative to pre-BSL
  Vault) in exchange for a clear open-source license.

## References

- OpenBao documentation: https://openbao.org/docs/
- OpenBao Kubernetes auth method: https://openbao.org/docs/auth/kubernetes/
- Kubernetes documentation: "Configure Service Accounts for Pods"
- Kubernetes documentation: "Projected Volumes — ServiceAccountToken"
- NIST SP 800-53 rev. 5, AC-6 (Least Privilege)
- NIST SP 800-53 rev. 5, IA-5 (Authenticator Management)
- ADR-K8S-001 (namespace topology), ADR-K8S-003 (secrets approach),
  ADR-K8S-011 (secrets provider pluggability)
