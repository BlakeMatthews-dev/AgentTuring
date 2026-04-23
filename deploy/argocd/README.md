# Stronghold GitOps via Argo CD

This directory wires Stronghold's two deploy environments to Argo CD.
Argo CD watches this repo and reconciles the cluster state to match.

## Layout

```
deploy/argocd/
├── README.md                                  (this file)
└── applications/
    ├── stronghold-integration.yaml            Argo Application: integration env
    └── stronghold-production.yaml             Argo Application: production env

deploy/helm/stronghold/
├── values.yaml                                Chart defaults
├── values-vanilla-k8s.yaml                    Disables OpenShift-specific resources
├── values-integration.yaml                    Integration overlay (small footprint)
├── values-production.yaml                     Production overlay (k3s today, AKS later)
├── values-integration-image.yaml              Auto-bumped by CI on push to integration
└── values-production-image.yaml               Auto-bumped by CI on push to main
```

## Environments

| Application                | Tracks branch | Namespace                | Sync policy |
|---------------------------|---------------|--------------------------|------------|
| `stronghold-integration`  | `integration` | `stronghold-integration` | **Auto** (prune + selfHeal) |
| `stronghold-production`   | `main`        | `stronghold-platform`    | **Manual** (approval gate) |

Both currently target the k3s cluster at `10.10.42.31`. Production migrates
to Azure AKS once blue-green is proven on k3s — at that point only
`destination.server` and the values overlay change; the workflow stays the same.

## Deploy flow

```
push to integration                 push to main
         │                                │
         ▼                                ▼
.github/workflows/deploy.yml runs:
  1. Build image, push to ghcr.io/agent-stronghold/stronghold:<env>-<sha>
  2. Bump image.tag in the matching values-{env}-image.yaml
  3. integration: bot commits directly to integration with [skip ci]
     production:  bot opens PR against main; operator approves + merges

         ↓                                ↓
Argo CD detects the commit:
  integration → auto-syncs immediately (~1 min)
  production  → waits for manual sync (operator runs `argocd app sync` or clicks UI)
```

## Bootstrap

Apply both Applications once against the cluster:

```bash
export KUBECONFIG=/root/okd-install/k3s-kubeconfig

kubectl apply -n argocd -f deploy/argocd/applications/stronghold-integration.yaml
kubectl apply -n argocd -f deploy/argocd/applications/stronghold-production.yaml

kubectl get applications -n argocd
```

## Verifying a deploy

Integration (after every merge):
```bash
kubectl get application stronghold-integration -n argocd \
  -o jsonpath='{.status.sync.status}{"\n"}{.status.health.status}{"\n"}'
# Expect: Synced / Healthy

kubectl get pods -n stronghold-integration
```

Production (after merging a `deploy(production):` PR):
```bash
# Stage 1: confirm Argo sees the new revision
argocd app get stronghold-production --refresh
# OutOfSync → expected; manual approval pending.

# Stage 2: approve + sync
argocd app sync stronghold-production
argocd app wait stronghold-production --health --timeout 300

kubectl get pods -n stronghold-platform
```

## Rollback

**Integration** — revert the offending bump commit on `integration`:
```bash
git revert <bump-sha>
git push origin integration
# Argo auto-syncs back within ~1 min.
```

**Production** — revert the bump commit on `main`, merge, then sync:
```bash
git revert <bump-sha>            # via PR or direct push if hotfix
git push origin main
argocd app sync stronghold-production
```

**Emergency (production)** — if you need to roll back faster than git:
```bash
helm history stronghold -n stronghold-platform
helm rollback stronghold <revision> -n stronghold-platform
# Then immediately fix git so Argo doesn't re-apply the bad version:
argocd app set stronghold-production --revision <known-good-sha>
```

## Migration to Azure AKS (future)

When the AKS cluster is ready and registered with Argo CD
(`argocd cluster add <ctx>`), edit `applications/stronghold-production.yaml`:

- Change `destination.server` to the AKS cluster URL.
- Append `values-aks.yaml` to `helm.valueFiles` (after `values-production.yaml`).

That's it. The workflow, bot PR pattern, and rollback procedure are unchanged.

## Why bot opens a PR for production (not a direct push)

The `main` branch enforces signed commits via branch protection. The
`github-actions[bot]` user can't sign commits. Rather than weaken the
signing requirement, the workflow opens a PR — operators review and
merge with their own signed commit, which preserves the audit chain.

Integration does not enforce signed commits, so the bot pushes directly.
