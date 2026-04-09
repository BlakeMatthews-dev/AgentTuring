# ADR-K8S-003 — Secrets approach

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

Stronghold needs to handle several classes of sensitive material:

- Database credentials (Postgres connection strings)
- Model provider API keys (OpenAI, Anthropic, Cerebras, Mistral, Google, …)
- LiteLLM virtual keys per agent and per tenant
- TLS certificates and private keys (issued by cert-manager)
- OAuth client secrets and JWT signing keys
- Per-tenant secrets that must not be readable by other tenants or by the
  platform team without explicit elevation

The current state of the prior single-node deployment hardcodes credentials in
`docker-compose.yml` (BACKLOG R6 family) and mounts a kubeconfig containing a
cluster-admin private key directly into the main app container (BACKLOG R3).
Both must end before v0.9 ships.

We also need to support enterprise customers who run Stronghold on EKS / GKE /
AKS / OpenShift, each of which has a different native secret-handling story
(IRSA, Workload Identity, Azure WI, OpenShift Secrets). The chart must be
pluggable across these environments without forking.

## Decision

We will adopt a **pluggable secrets backend** with four supported providers,
selected per-deployment via `values.yaml`. The default for the OKD homelab and
for OpenShift customers is **OpenShift Secrets + sealed-secrets for GitOps**.

### Supported backends

1. **`k8s` (default for vanilla Kubernetes)** — Kubernetes-native Secrets
   resources, populated by Helm at install time from values or by the operator
   out of band. Suitable for: developer environments, single-node clusters
   where GitOps is not in use.

2. **`sealed-secrets`** — Bitnami sealed-secrets controller installed in
   `stronghold-system`. Secrets are encrypted client-side with the cluster's
   public key, committed to git as `SealedSecret` resources, and decrypted in-
   cluster by the controller. Suitable for: GitOps workflows, OKD homelab
   default, OpenShift customers who want declarative secret management.

3. **`eso` (External Secrets Operator)** — operator that syncs Kubernetes
   Secrets from external secret stores (AWS Secrets Manager, GCP Secret
   Manager, Azure Key Vault, HashiCorp Vault, …) using the cloud provider's
   native pod identity (IRSA on EKS, Workload Identity on GKE, Azure WI on
   AKS). Suitable for: cloud-managed Stronghold deployments where the customer
   already has a cloud-native secret store.

4. **`vault`** — HashiCorp Vault Agent injector or CSI provider, for self-
   hosted enterprise customers who run Vault. Suitable for: regulated
   enterprise on-prem deployments.

The chart selects the backend with `values.yaml`:

```yaml
security:
  secretsBackend: sealed-secrets   # one of: k8s | sealed-secrets | eso | vault
```

### Universal rules (apply regardless of backend)

- **No secrets in environment variables on the pod spec.** Secrets are
  mounted as files under `/var/run/secrets/stronghold/` so that `printenv`
  on a compromised pod returns nothing useful and so that secrets are not
  visible in `oc describe pod` output.
- **No secrets in ConfigMaps.** ConfigMaps are world-readable inside the
  namespace; Secrets enforce additional RBAC and (with etcd encryption-at-
  rest enabled) are encrypted on disk.
- **Per-tenant secret isolation.** Each tenant namespace gets its own
  sealed-secrets keypair (or its own ESO ClusterSecretStore, or its own Vault
  namespace). The platform team cannot decrypt one tenant's secrets without
  access to that tenant's keypair.
- **etcd encryption at rest is required.** This is enabled by default on
  OKD and on all major managed clouds, but the chart's `values.yaml` includes
  a check at install time that fails fast if `EncryptionConfiguration` is
  missing on a self-managed cluster.
- **Secret rotation is owned by the secrets backend, not by the chart.**
  sealed-secrets supports rotation by re-sealing and committing; ESO supports
  it via the upstream secret store's rotation policy; Vault supports it via
  Vault Agent template re-renders.

### Secret injection patterns

The universal rules above pin down WHERE secrets live (files, not env vars)
and WHO can read them (per-tenant isolation). This section pins down HOW
they reach a running container. Four patterns are supported; each pod picks
exactly one.

**1. Preferred: projected volume mounts via `secret` references.** The pod
spec declares a `volume` of type `secret` referencing a Kubernetes Secret
(populated by whichever backend is active), and a `volumeMount` that places
the decoded files under `/var/run/secrets/stronghold/<name>/`. The workload
reads the file on demand. This is the default for every Stronghold
component.

Why preferred:

- Secret rotation propagates automatically when the Secret is updated (the
  kubelet refreshes the mounted file within ~60 seconds) — no pod restart
  required for workloads that re-read the file on each use.
- The secret material never appears in `oc describe pod`, `oc get pod -o
  yaml`, or process environment, which narrows the blast radius of a
  read-only API compromise.
- Works identically across all four secrets backends (k8s, sealed-secrets,
  ESO, Vault CSI), so the pod spec is portable.

**2. Init container for one-shot materialization.** A dedicated init
container runs before the main container, reads from the secrets backend,
and writes a derived artifact (e.g., a pre-rendered config file that
interpolates secret values into a non-secret template) to an `emptyDir`
shared with the main container. The main container then reads the
non-secret artifact.

When to use:

- The workload is a third-party component that cannot be taught to read
  secrets from a file path and requires the secret baked into a config
  file (LiteLLM's `config.yaml`, for example).
- A secret must be transformed (base64-decoded, reformatted, combined with
  other values) before the main container can consume it.
- A pre-flight integrity check on the secret must run and fail-fast the
  pod before the main container starts, rather than failing at first-use.

Init containers are not the default because they delay pod start by the
init-container runtime and because the rendered artifact sits unencrypted
on the node's `emptyDir` tmpfs for the pod's lifetime.

**3. Downward API for pod-identity metadata only.** The downward API
exposes pod metadata (namespace, pod name, labels, annotations, node name,
ServiceAccount name) to the container as environment variables or mounted
files. It is explicitly **not** a secrets mechanism — downward API values
are all non-sensitive metadata already visible in `oc describe pod`.

When to use:

- Populating `POD_NAMESPACE` / `POD_NAME` for log correlation and telemetry
  (Phoenix traces, audit events).
- Surfacing the `stronghold.io/tenant-id` label to the workload so it can
  scope its queries.
- Passing the node name for topology-aware client behavior.

The downward API is called out here specifically to prevent the common
mistake of treating it as a secrets channel. Pod labels and annotations
are world-readable inside the namespace; never put a secret there.

**4. CSI secret provider (Vault / cloud-native).** When the backend is
`vault` or `eso` with the `secrets-store.csi.k8s.io` driver enabled, a
`csi` volume mounts the backend's secrets directly at pod start without
first materializing a Kubernetes Secret. This is the most tightly coupled
option and is only used for customers who have a policy requirement that
secret material never touch etcd at all.

### Explicit ban on env-var injection of API keys

**`env.valueFrom.secretKeyRef` and `envFrom.secretRef` are forbidden for
any secret whose value provides authentication or authorization** (API
keys, database passwords, OAuth client secrets, JWT signing keys, model
provider keys). CI fails a PR whose rendered manifests place a
`secretKeyRef` under `env:` or an `envFrom.secretRef` on any
Stronghold-owned Deployment, StatefulSet, or Job.

Rationale (OWASP Top 10 2021, A05:2021 Security Misconfiguration):

- Environment variables are inherited by every child process of the
  container and by any debugger attached to PID 1. A compromised sidecar
  or a shell-out from the main process leaks the key transitively.
- `oc describe pod`, `oc get pod -o yaml`, and the kubelet's audit log all
  surface the environment. Any operator with pod read access gets the
  secret, regardless of Secret RBAC.
- Crash dumps, stack traces, and common observability tooling (APM
  agents, error reporters) frequently capture process environment.
  Secrets in env vars end up in third-party error-tracking services.
- File-mounted secrets can be rotated in place; env vars require a pod
  restart to pick up a new value, which disincentivizes rotation.

The only exception is non-sensitive configuration (feature flags,
hostnames, log levels) sourced from ConfigMaps via `envFrom.configMapRef`.
Those are not secrets and are unaffected by this rule.

### Migration path

The current hardcoded credentials in `docker-compose.yml` and `.kubeconfig-docker`
are removed in PR-8 (R3 fix) and PR-18 (legacy compose decommission). They are
replaced by sealed-secrets in the OKD homelab deployment.

## Alternatives considered

**A) Kubernetes Secrets only, no sealed-secrets / ESO / Vault.**

- Rejected: forces operators to manage secrets out-of-band (kubectl create
  secret, never committed to git). Doesn't support GitOps workflows. Doesn't
  support cloud-native pod identity. Acceptable as a developer convenience
  (`secretsBackend: k8s`) but not as the production default.

**B) Hardcoded secrets in Helm values (current state of the prior deployment).**

- Rejected: this is what we are running away from. Closes BACKLOG R6 family.

**C) Single backend (e.g., Vault only) with no pluggability.**

- Rejected: forces every customer to deploy Vault. The OKD homelab does not
  need Vault. EKS customers prefer IRSA + Secrets Manager. AKS customers
  prefer Workload Identity + Key Vault. Pluggability is the only way to be
  portable across these environments.

**D) ESO as the only supported backend.**

- Rejected: ESO is excellent on cloud but adds an operator + a cloud-side
  secret store + IAM configuration for self-hosted single-node deployments
  where sealed-secrets is much simpler. Both have legitimate use cases.

**E) HashiCorp Vault Agent as the only supported backend.**

- Rejected: Vault is heavyweight to deploy and operate. Inappropriate as the
  default for a single-operator homelab. Necessary as an option for regulated
  enterprise customers.

## Consequences

**Positive:**

- Closes BACKLOG R3 (cluster-admin kubeconfig) and BACKLOG R6 family
  (hardcoded credentials).
- The chart works on any of the four backends without forking.
- Per-tenant secret isolation is built into the design from day one, not
  bolted on later.
- GitOps customers can manage all infrastructure declaratively.

**Negative:**

- Four backends means four code paths in the Helm templates. Mitigated by
  putting backend-specific logic in `_helpers.tpl` and gating template
  blocks on `.Values.security.secretsBackend`.
- Documentation grows: each backend gets its own setup section in
  `docs/INSTALL.md`. Acceptable cost.
- Operators of Stronghold need to know which backend their installation uses
  before they can rotate a secret. Mitigated by `helm get values stronghold`
  showing the active backend.

**Trade-offs accepted:**

- Template complexity in exchange for portability across the four major
  enterprise environments.
- Operator-knowledge cost in exchange for not making a one-size-fits-all
  choice that fits no one.

## References

- Kubernetes documentation: "Secrets" — kubernetes.io/docs/concepts/configuration/secret/
- Kubernetes documentation: "Encrypting Confidential Data at Rest"
- OpenShift Container Platform 4.14 documentation: "Providing sensitive data to pods"
- Bitnami sealed-secrets project documentation
- External Secrets Operator documentation — external-secrets.io
- HashiCorp Vault documentation: "Vault Agent Injector for Kubernetes"
- AWS IAM Roles for Service Accounts (IRSA) documentation
- Google Cloud Workload Identity documentation
- Azure AD Workload Identity documentation
- NIST SP 800-57 Part 1 Rev. 5 (Recommendation for Key Management)
- OWASP Top 10 2021 A05:2021 Security Misconfiguration — owasp.org/Top10/A05_2021-Security_Misconfiguration/
- Kubernetes documentation: "Downward API for Pods"
- Kubernetes documentation: "Projected Volumes"
- Kubernetes documentation: "Secrets Store CSI Driver" — secrets-store-csi-driver.sigs.k8s.io
- SOC2 Trust Services Criteria CC6.1 (logical access)
