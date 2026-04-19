# Project Turing — Kubernetes manifests

Single-instance deployment. Project Turing's autonoetic premise (one self
per deployment) means we don't horizontally scale — `replicas: 1` and the
`Recreate` strategy ensure no two pods ever write the same SQLite database.

## Apply order

```bash
kubectl apply -f namespace.yaml
kubectl apply -f configmap.yaml             # turing-config + turing-pools
kubectl apply -f scenarios-configmap.yaml   # optional
kubectl apply -f pvc.yaml

# Create the secret OUT-OF-BAND. Do not commit a real virtual key.
# Example for plain kubectl (replace the value):
kubectl -n turing create secret generic turing-secrets \
    --from-literal=LITELLM_VIRTUAL_KEY=sk-real-virtual-key

# Or use sealed-secrets / external-secrets / SOPS — anything but the
# example file in this directory.

kubectl apply -f deployment.yaml
kubectl apply -f service.yaml
```

## Verify

```bash
kubectl -n turing get pods
kubectl -n turing logs deploy/turing -f
kubectl -n turing port-forward svc/turing 9100:9100 9101:9101
# In another terminal:
curl http://127.0.0.1:9100/metrics
open http://127.0.0.1:9101/        # chat UI
```

## Inspect persistent state

```bash
kubectl -n turing exec deploy/turing -- \
    python -m turing.runtime.inspect --db /data/turing.db summarize

kubectl -n turing exec deploy/turing -- \
    python -m turing.runtime.inspect --db /data/turing.db daydream-sessions
```

## Editing pools without rebuilding

Edit `configmap.yaml`'s `turing-pools` entry, `kubectl apply -f`, and
restart the pod (`kubectl -n turing rollout restart deploy/turing`).
The new pool config takes effect on next start.

## Editing scenarios without rebuilding

Edit `scenarios-configmap.yaml`, apply, and restart. If you didn't apply
the scenarios ConfigMap, the runtime falls back to the image's bundled
scenarios.

## Resource sizing

The defaults (cpu: 100m–1, memory: 128Mi–512Mi) are sized for the
research workload. If you raise tick rate, add many providers, or wire
heavier tools, adjust limits.

## What's NOT in here

- Ingress / TLS — bring your own (cert-manager + nginx-ingress is
  conventional). The chat port is plain HTTP; do not expose it directly
  to the public internet.
- Monitoring stack — assumes you already run Prometheus + Grafana. Point
  Prometheus at the `turing` Service's `metrics` port; standard scrape
  config.
- Backups — SQLite file lives on the PVC. Snapshot / volume-backup
  whatever you already use for stateful workloads.
- Multi-tenancy — Project Turing is single-self by design. Don't run
  multiple replicas; don't share the PVC between deployments.
