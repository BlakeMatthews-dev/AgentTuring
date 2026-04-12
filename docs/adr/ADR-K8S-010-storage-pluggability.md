# ADR-K8S-010 — Storage backend pluggability

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

Stronghold's persistent state lives in Postgres + pgvector:

- Memory and RAG embeddings
- Trace metadata and Phoenix data
- Strike state (post BACKLOG R22 fix in PR-4)
- Tenant configuration and policy versions
- Agent-as-data definitions

How and where this Postgres lives is a deployment decision that varies by
customer:

- A homelab single-operator wants in-cluster Postgres on local disk —
  simple, free, no cloud account required
- An EKS customer probably wants RDS for managed backups, PITR, and
  multi-AZ
- A GKE customer wants Cloud SQL
- An AKS customer wants Azure Database for PostgreSQL
- An OpenShift on-prem customer may have a corporate Postgres-as-a-Service
  fronted by Vault or service catalog
- A regulated customer may be required to use a specific certified database
  product

The chart cannot pick one backend and force all customers onto it. We need
a pluggable model with a sensible default for v0.9 and a clear path to
external Postgres in v1.0+.

## Decision

We adopt a **two-mode storage backend** with values-driven selection:

### Mode 1: in-cluster Postgres StatefulSet (default for v0.9)

- Postgres + pgvector runs as a StatefulSet in `stronghold-data` namespace
- Persistent storage via the cluster's default StorageClass (local-path on
  the homelab; gp3 / pd-ssd / managed-csi on the cloud distros)
- Single replica for v0.9 (HA Postgres in v1.0+)
- Backups via Velero scheduled snapshots of the namespace + PVCs
- Credentials managed via the secrets backend selected in ADR-K8S-003
- Connection string assembled at chart install time and stored as a
  Secret

`values.yaml`:

```yaml
postgres:
  mode: in-cluster
  inCluster:
    image: pgvector/pgvector:pg17
    storage:
      size: 50Gi
      storageClassName: ""   # default StorageClass
    resources:
      requests:
        cpu: 1
        memory: 2Gi
      limits:
        cpu: 4
        memory: 8Gi
```

### Mode 2: external Postgres (v1.0+)

- Customer's existing Postgres (RDS, Cloud SQL, Azure DB, on-prem managed
  Postgres, …) is referenced by host + credentials
- The chart does NOT provision Postgres in this mode
- The chart MUST verify at install time that the external Postgres has
  the pgvector extension installed (the chart's pre-install hook runs
  `SELECT * FROM pg_extension WHERE extname='vector'` and fails fast if
  missing)
- Credentials are read from a Secret referenced by name, not from values
  directly (so they can come from any of the secrets backends in
  ADR-K8S-003)
- Backups are owned by the customer's existing database backup tooling,
  NOT by Velero

`values.yaml`:

```yaml
postgres:
  mode: external
  external:
    host: my-rds-instance.us-east-1.rds.amazonaws.com
    port: 5432
    database: stronghold
    sslMode: require
    credentialsSecretRef:
      name: stronghold-postgres-creds   # Secret with keys "username" and "password"
    pgvectorRequired: true   # pre-install hook verifies the extension
```

### Schema migrations

Stronghold runs Alembic migrations on startup (via the existing
`alembic upgrade head` flow in `src/stronghold/db/`). This is the same in
both modes — the chart does not own migration logic.

In external mode, the operator must grant the Stronghold credential the
ability to create tables and indexes in its database. The chart's
`docs/INSTALL.md` includes the SQL grants.

### Storage class selection on the homelab

For the homelab OKD cluster (in-cluster mode):

- Prod Postgres PVC uses a fast StorageClass backed by NVMe (`local-path-
  nvme-prod` or whatever the OKD installer creates by default on the
  Fedora CoreOS root disk)
- Dev branch Postgres PVCs use a separate StorageClass with quota
- Velero schedules a daily backup of the prod namespace's PVCs to
  `/mnt/storage/k8s-backups`, picked up by PBS via the existing backup
  pipeline

### Migration from in-cluster to external

A customer who starts on in-cluster Postgres and later moves to external
follows this runbook (documented in `docs/INSTALL.md`):

1. `pg_dump` the in-cluster instance
2. `pg_restore` into the external instance (with pgvector extension
   pre-installed)
3. Update `values.yaml` to set `postgres.mode: external` and configure
   `postgres.external.*`
4. `helm upgrade stronghold ...`
5. The chart's pre-install hook verifies pgvector exists in the external
   DB
6. The Stronghold pods restart and connect to the external DB
7. After verification, delete the now-orphaned in-cluster PVC

This is documented as a v1.0+ feature. v0.9 ships in-cluster only.

## Alternatives considered

**A) Always in-cluster Postgres, never support external.**

- Rejected: enterprise customers will not adopt a product that forces
  them onto an in-cluster database. RDS / Cloud SQL / Azure DB are the
  default for any production deployment in the cloud. We must support
  external from v1.0 at the latest.

**B) Always external Postgres, never bundle one.**

- Rejected: forces every customer to provision a separate database
  before they can install Stronghold. Bad first-run experience. The
  homelab single-operator wants `helm install` to just work without
  setting up RDS first.

**C) Bundle Postgres as a sub-chart from a community Helm chart (e.g.,
Bitnami).**

- Rejected: adds an external dependency, ties our release cadence to a
  third-party chart's release cadence, and inherits whatever default
  values that chart picks (which may not match our security posture). We
  ship our own minimal StatefulSet template under our own values
  control.

**D) Use a Postgres operator (Crunchy, Zalando, CloudNativePG) instead of
a hand-rolled StatefulSet.**

- Rejected for v0.9: operators add platform complexity and a CRD
  surface that the customer's platform team has to approve and install.
  v0.9 ships the simplest possible single-replica StatefulSet. Operator-
  managed Postgres becomes an option in v1.1+ for customers who want
  HA + automated failover, as a third mode alongside in-cluster and
  external.

## Consequences

**Positive:**

- Homelab single-operator gets `helm install` and a working database
  with no extra setup.
- Cloud customers can point at managed Postgres without modifying the
  chart.
- Backup ownership is clear: in-cluster mode → Velero, external mode →
  customer's tooling.
- pgvector requirement is verified at install time, not at first query
  time.

**Negative:**

- Two modes means two code paths in the chart templates. Mitigated by
  isolating mode-specific logic in `_helpers.tpl`.
- v0.9 customers on external Postgres are out of scope until v1.0
  ships. Acceptable: v0.9 is the homelab milestone, not the
  cloud-customer milestone.
- Operator-managed Postgres (Crunchy, etc.) is a third mode we don't
  ship in v0.9. Acceptable: customers who need it can still use the
  external mode and point at an operator-managed instance.

**Trade-offs accepted:**

- Template complexity in exchange for portability.
- Delayed cloud-customer support (v1.0 not v0.9) in exchange for
  shipping the homelab milestone on schedule.

## References

- Kubernetes documentation: "StatefulSets"
- Kubernetes documentation: "Persistent Volumes"
- pgvector project documentation
- Postgres documentation: "Schema modifications"
- Alembic documentation: "Auto generating migrations"
- AWS RDS for PostgreSQL documentation
- Google Cloud SQL for PostgreSQL documentation
- Azure Database for PostgreSQL documentation
- ADR-K8S-001 (namespace topology — `stronghold-data`)
- ADR-K8S-003 (secrets approach — credential management)
