# Decommission kind Cluster

**Issue:** #808
**Date:** 2026-04-09
**Context:** The k3s cluster on VM 301 (stronghold-k3s-host, 10.10.42.31) is now the
production target for Stronghold. The old kind cluster is no longer needed. See
ADR-K8S-006 addendum (2026-04-09) for the k3s pivot rationale.

---

## Prerequisites

- SSH access to the k3s host: `ssh ubuntu@10.10.42.31`
- KUBECONFIG for k3s: `/root/okd-install/k3s-kubeconfig`
- `kind` binary installed on the machine where the kind cluster was created

## Step 1: Verify k3s cluster health

Confirm the k3s cluster is fully operational before removing anything.

```bash
export KUBECONFIG=/root/okd-install/k3s-kubeconfig

kubectl get nodes
# Expect: stronghold-k3s  Ready

kubectl get pods -A
# All pods should be Running / Completed

helm list -A
# Expect: calico (tigera-operator), argocd (argocd), stronghold (stronghold-platform)
```

## Step 2: Verify Argo CD Application is synced

```bash
kubectl get applications -n argocd
# Status should show Synced / Healthy

# Or via the Argo CD UI at https://10.10.42.31:30443/
```

## Step 3: Delete the kind cluster

```bash
kind get clusters
# If "stronghold" is listed:

kind delete cluster --name stronghold
```

If the kind cluster was already removed or never existed on the current host, skip
this step.

## Step 4: Remove kind binary (optional)

Only remove if no other projects depend on kind.

```bash
which kind
sudo rm -f "$(which kind)"
```

## Step 5: Clean up kubeconfig contexts

Remove stale kubeconfig entries that pointed to the old kind cluster.

```bash
# List all contexts
kubectl config get-contexts

# Delete the kind context
kubectl config delete-context kind-stronghold 2>/dev/null
kubectl config delete-cluster kind-stronghold 2>/dev/null
kubectl config delete-user kind-stronghold 2>/dev/null

# Verify the current context still points to k3s
kubectl config current-context
```

## Step 6: Update CI/CD pipelines

Review any CI/CD configurations that referenced the kind cluster and update them
to target k3s:

- GitHub Actions workflows using kind for integration tests
- Argo CD ApplicationSets or AppProjects referencing a kind cluster URL
- Any scripts that run `kind load docker-image` (k3s uses `ctr` or a registry)

## Step 7: Archive kind provisioning scripts

Move (do not delete) any kind cluster setup scripts to an archive directory so
they remain available for reference.

```bash
mkdir -p _archive/kind-cluster
git mv scripts/kind-*.sh _archive/kind-cluster/ 2>/dev/null
git mv deploy/kind/ _archive/kind-cluster/ 2>/dev/null
```

Commit the archive with a message referencing issue #808.

---

## Verification

After completing all steps, confirm:

- [ ] `kind get clusters` returns empty (or kind is uninstalled)
- [ ] `kubectl config get-contexts` has no kind-related entries
- [ ] k3s cluster responds to `kubectl get nodes` with Ready status
- [ ] Argo CD shows all applications Synced and Healthy
