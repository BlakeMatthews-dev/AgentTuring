# ADR-K8S-011 — Secrets provider pluggability

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

ADR-K8S-003 established the four supported secrets backends (k8s, sealed-
secrets, eso, vault) and the universal rules (no secrets in env vars, no
secrets in ConfigMaps, etcd encryption at rest required, per-tenant
isolation). This ADR records the deeper details of how the chart actually
selects and configures the backend for each environment, and how the
operator workflow differs across them.

The four backends are not interchangeable from an operator perspective:

- `k8s`: kubectl-create-secret workflow, no GitOps
- `sealed-secrets`: kubeseal client-side encryption, GitOps-friendly
- `eso`: depends on a cloud secret store + cloud pod identity
- `vault`: depends on Vault Agent injector or Vault CSI provider

A v0.9 customer needs to know which backend to pick during install, what
prerequisites that backend requires, and what the day-2 operator workflow
looks like. This ADR is the per-backend reference.

## Decision

The chart selects the backend via `.Values.security.secretsBackend`, with
the following per-backend behavior:

### `k8s` — Kubernetes-native Secrets

**Use when:** developer environments, single-node clusters where GitOps
is not in use, smoke tests.

**Prerequisites:** none beyond a running cluster with etcd encryption at
rest enabled.

**Operator workflow:**

1. Create the Secret out of band:
   ```
   oc create secret generic stronghold-litellm-key \
     --from-literal=api-key=sk-... \
     -n stronghold-platform
   ```
2. Reference it in `values.yaml`:
   ```yaml
   security:
     secretsBackend: k8s
     secrets:
       litellm:
         existingSecret: stronghold-litellm-key
         key: api-key
   ```
3. `helm install` consumes the existing Secret reference.

**Rotation:** `oc create secret --dry-run=client | oc apply -f -` to
update; restart pods to pick up the new value.

**Trade-off:** secrets are not committed to git, so the chart install is
not fully reproducible from the repo. Acceptable for dev / single-node
where the operator is the source of truth.

### `sealed-secrets` — Bitnami sealed-secrets controller (default for OKD homelab)

**Use when:** GitOps workflows, OKD homelab default, OpenShift customers
who want declarative secret management without a separate cloud secret
store.

**Prerequisites:**

- sealed-secrets controller installed in `stronghold-system` namespace
  (one-time, via OperatorHub on OKD or via Helm on vanilla k8s)
- `kubeseal` CLI installed on the operator's workstation

**Operator workflow:**

1. Encrypt the secret client-side:
   ```
   echo -n 'sk-...' | kubeseal \
     --raw \
     --namespace stronghold-platform \
     --name stronghold-litellm-key \
     > stronghold-litellm-key.sealed
   ```
2. Reference it in a `SealedSecret` manifest committed to git
3. `helm install` (or `oc apply`) creates the SealedSecret; the controller
   decrypts it in-cluster into a plain Secret
4. Stronghold pods reference the resulting Secret as if it were a regular
   Secret

**Rotation:** re-encrypt with `kubeseal`, commit, `oc apply`. The
controller updates the underlying Secret, and pods pick up the new value
on restart (or via a Reloader sidecar if zero-downtime rotation is
needed).

**Per-tenant isolation:** each tenant namespace gets its own sealed-
secrets keypair. Compromising one tenant's key cannot decrypt another
tenant's SealedSecrets.

### `eso` — External Secrets Operator

**Use when:** cloud-managed Stronghold deployments where the customer
already has a cloud-native secret store (AWS Secrets Manager, GCP Secret
Manager, Azure Key Vault, HashiCorp Vault, …) and uses cloud-native pod
identity (IRSA, Workload Identity, Azure WI).

**Prerequisites:**

- ESO installed in the cluster (one-time)
- A `ClusterSecretStore` or `SecretStore` configured to authenticate
  against the customer's secret backend, using cloud-native pod identity
- The customer's secret values exist in the cloud secret store before
  install

**Operator workflow:**

1. Customer creates the secret in the cloud store (out of band, via
   their existing IaC: terraform, CloudFormation, Bicep, …)
2. Reference it in an `ExternalSecret` manifest committed to git
3. ESO syncs the cloud value into a Kubernetes Secret in the local
   cluster
4. Stronghold pods reference the synced Secret

**Rotation:** rotate the value in the cloud store; ESO syncs within its
poll interval (default 1 hour, tunable per ExternalSecret).

**Per-cloud configuration helpers:** the chart's per-cloud overlay files
(`values-eks.yaml`, `values-gke.yaml`, `values-aks.yaml` per ADR-K8S-007)
include the ServiceAccount annotations and ClusterSecretStore references
needed for each cloud's pod identity model.

### `vault` — HashiCorp Vault

**Use when:** self-hosted enterprise customers who run Vault as their
single source of truth for secrets, often in regulated environments.

**Prerequisites:**

- Vault deployed and operational (out of scope for the chart)
- Vault Kubernetes auth method enabled
- Either Vault Agent injector OR Vault Secrets Operator installed in
  the cluster

**Operator workflow (Vault Agent injector mode):**

1. Customer creates the secret in Vault at a known path
2. Stronghold pods get annotations like
   `vault.hashicorp.com/agent-inject: "true"` and
   `vault.hashicorp.com/agent-inject-secret-litellm: "secret/data/stronghold/litellm"`
3. Vault Agent runs as a sidecar, fetches the secret, writes it to
   `/vault/secrets/<file>` in the pod
4. Stronghold reads the file at the standard
   `/var/run/secrets/stronghold/<name>` path (the chart's pod template
   handles the path mapping)

**Rotation:** Vault's lease + renewal handles this; the agent re-fetches
on lease expiry.

### Pre-install validation

The chart's pre-install hook validates the selected backend's
prerequisites and fails fast if they're missing. For example:

- `secretsBackend: sealed-secrets` → check that the sealed-secrets
  controller is running in `stronghold-system`
- `secretsBackend: eso` → check that ESO is installed and that the
  configured `ClusterSecretStore` exists and is in `Ready` state
- `secretsBackend: vault` → check that the Vault Agent injector
  webhook is installed and reachable

This catches "wrong backend selected" before the pods come up with
empty secret mounts.

### What the chart does NOT do

- Provision the secrets backend itself. The operator (or the customer's
  platform team) installs sealed-secrets, ESO, or Vault separately. The
  chart only consumes secrets, never provisions the secret-management
  infrastructure.
- Rotate secrets automatically. Each backend has its own rotation
  workflow; the chart documents them but does not orchestrate them.
- Migrate secrets between backends. A customer who switches from
  sealed-secrets to ESO must export and re-import out of band. We
  document the runbook in `docs/INSTALL.md`.

## Alternatives considered

**A) Single backend (e.g., always sealed-secrets).**

- Rejected per ADR-K8S-003 alternative D. Different environments need
  different backends; forcing one creates friction for everyone except
  the small population it fits.

**B) Auto-detect the backend at install time based on what's installed in
the cluster.**

- Rejected: too magical. The operator should explicitly state which
  backend they want. Auto-detection makes diagnostics harder when the
  wrong backend is selected.

**C) Provision the secrets backend ourselves as part of the chart.**

- Rejected: scope creep. We're not in the secret-management-platform
  business. The customer's platform team owns sealed-secrets / ESO /
  Vault installation, and they should — those tools have their own
  upgrade lifecycles, their own RBAC requirements, and their own
  backup needs.

**D) Skip the pre-install validation and let secret-mount failures
manifest as pod CrashLoopBackOff.**

- Rejected: that's the worst possible failure mode for a customer
  evaluating Stronghold. The first install should either succeed or
  fail with a clear message, never come up half-broken.

## Consequences

**Positive:**

- Customers on every common environment (homelab, cloud-managed,
  on-prem enterprise) get a workflow that fits their existing tools.
- Per-backend workflows are documented in one place
  (`docs/INSTALL.md`), with the same conceptual model applied to each.
- Pre-install validation catches "wrong backend" errors before they
  become "why are my pods crashing".
- Per-tenant isolation works in all four backends.

**Negative:**

- Four backends to document and test. Mitigated by the per-PR validate
  workflow rendering all four backends and running kubeconform.
- Each backend has its own rotation workflow that the operator must
  learn. Acceptable: the operator already knows whichever backend they
  picked.

**Trade-offs accepted:**

- Documentation surface in exchange for operator flexibility.
- Per-backend test matrix in exchange for portability across
  environments.

## References

- Kubernetes documentation: "Secrets"
- Bitnami sealed-secrets project documentation
- External Secrets Operator documentation — external-secrets.io
- HashiCorp Vault documentation: "Vault Agent Injector for Kubernetes"
- HashiCorp Vault documentation: "Vault Secrets Operator"
- AWS IAM Roles for Service Accounts (IRSA) documentation
- Google Cloud Workload Identity documentation
- Azure AD Workload Identity documentation
- OWASP Secrets Management Cheat Sheet
- ADR-K8S-003 (secrets approach — high-level decision)
