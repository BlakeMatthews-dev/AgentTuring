# ADR-K8S-009 — Migration sequence to OKD

**Status:** Proposed
**Date:** 2026-04-07
**Deciders:** Stronghold core team

## Context

The current production Stronghold instance runs on a prior single-node
Kubernetes deployment alongside a legacy docker-compose stack on the
homelab host. Both have known problems:

- The single-node Kubernetes runtime uses a CNI that does not enforce
  NetworkPolicy. Storage is hostPath inside a container. Several MCP pods
  have been in `ImagePullBackOff` for over a week with nobody watching.
- The docker-compose stack runs in parallel with the Kubernetes deployment,
  with several containers in restarting / unhealthy states. It is not
  serving production traffic, but it consumes resources and confuses the
  picture.
- The Stronghold instance currently fronted by a Cloudflared tunnel routes
  through one of these stacks. The exact target has drifted over time.

ADR-K8S-006 commits us to OKD single-node OpenShift on a new dedicated VM
as the production runtime. We need a migration sequence that:

- Cuts over production traffic safely with a rollback path at every step
- Runs both old and new in parallel for long enough to catch latent
  issues
- Decommissions the old runtime cleanly without leaving orphaned state
- Does not lose production data

## Decision

We will execute a **6-step parallel-run + DNS cutover with a 7-day soak**
between cutover and decommission. Both the old runtime and the new OKD
cluster run concurrently throughout, with rollback achievable at any step
by flipping the Cloudflared tunnel target.

### The six steps

**Step 1 — Build the chart and validate against OKD**

- Phase 2 PRs land (helm chart with OpenShift-first templates)
- Run `helm template -f values-prod-homelab.yaml | oc apply --dry-run=server -f -`
  against the new OKD cluster
- Verify all resources render cleanly and pass server-side dry-run
- **Rollback at this step:** trivial — no production change yet, just abort

**Step 2 — Stand up `stronghold-prod` on OKD**

- `helm install stronghold deploy/helm/stronghold -f values-prod-homelab.yaml -n stronghold-prod`
- The new namespace and workloads come up alongside the existing prior
  runtime
- Postgres StatefulSet starts empty — we restore the prod data via Velero
  (or pg_dump / pg_restore) from a fresh backup of the prior runtime taken
  immediately before this step
- Sealed-secrets keypair generated for `stronghold-prod`; secrets resealed
  from the prior runtime's plaintext values (one-time operator action,
  documented as a runbook in PR-2)
- Cloudflared tunnel still pointing at the prior runtime — no production
  user sees the new cluster yet
- **Rollback at this step:** `helm uninstall stronghold -n stronghold-prod`,
  no production impact

**Step 3 — Smoke test the OKD instance via private hostname**

- Add a temporary private hostname (`stronghold-okd-test.internal.<domain>`)
  routed to the OKD Route via a separate Cloudflared tunnel or via
  in-cluster `oc port-forward`
- Run the smoke test suite: health checks, basic API exercises, MCP tool
  calls, agent runs
- Verify all NetworkPolicies enforcing (probe pod from a separate namespace
  fails)
- Verify Velero backup of the prod namespace runs successfully and the
  resulting backup restores cleanly into a scratch namespace
- Verify all OperatorHub-managed operators (cert-manager, sealed-secrets,
  OADP) are healthy
- **Rollback at this step:** delete the temporary hostname, leave the OKD
  instance running for further investigation

**Step 4 — DNS cutover**

- Update the Cloudflared tunnel config (`/root/docker/cloudflared/`) to
  point at the OKD cluster's Route hostname instead of the prior runtime's
  service endpoint
- This is the actual cutover. Production traffic now hits OKD.
- The prior runtime is left running (idle but warm) for fast rollback
- **Rollback at this step:** flip the Cloudflared tunnel target back to
  the prior runtime. Total rollback time: ~30 seconds (Cloudflared config
  reload).

**Step 5 — Soak (7 days)**

- Both the OKD cluster (serving prod) and the prior runtime (idle, warm)
  remain alive for 7 calendar days
- Daily checks on the OKD side: pod health, error rates, latency
  percentiles, Phoenix traces, Velero backup success
- Any production-affecting issue triggers immediate rollback (Step 4 in
  reverse)
- After 7 days with no rollback events, proceed to Step 6
- This soak period is intentionally non-negotiable. The PR that performs
  the cutover (PR-16) is followed by a documentation-only PR (PR-17) that
  adds soak observations to `INFRASTRUCTURE-BACKLOG.md`. PR-17 cannot
  merge for 7 days. This holds the merge train and forces the soak.

**Step 6 — Decommission**

- After the 7-day soak, with no rollback events:
- Stop the prior runtime workloads
- Delete the prior runtime cluster
- `docker compose down -v` for the legacy compose stack
- Remove the broken/restarting compose containers
- Remove the broken MCP pods (`ImagePullBackOff`-stuck pods that have been
  unwatched)
- Run `docker system prune -af` on the host to reclaim disk
- Update `INFRASTRUCTURE-BACKLOG.md` with the decommission session log
- Reconfigure Cloudflared tunnel to remove the prior-runtime fallback
  endpoint (or migrate the tunnel itself into the OKD cluster as a
  Deployment)

### What stays unchanged across the migration

- The Cloudflared tunnel domain and the public hostname users hit
- Postgres data (restored via Velero / pg_dump in Step 2)
- The set of MCP servers running in production
- The set of model providers configured in LiteLLM

### What changes

- The Kubernetes runtime under the hood (prior single-node → OKD SNO)
- Storage backing (ephemeral hostPath inside a container → real PVCs on the
  new VM disk)
- Backups (none → daily Velero schedules)
- NetworkPolicy enforcement (none → OVN-Kubernetes)
- Secrets handling (mixed → sealed-secrets per ADR-K8S-003)
- Observable cluster health (none → OperatorHub-managed cert-manager,
  Velero, monitoring)

## Alternatives considered

**A) In-place upgrade of the prior runtime to add a real CNI and proper
storage.**

- Rejected: the prior runtime is a CI tool, not a production runtime. No
  amount of CNI swapping makes it cluster-grade. The ADR-K8S-006 decision
  was specifically that the runtime itself is wrong; replacing it is the
  right move, not patching it.

**B) Big-bang cutover — stop the prior runtime, install OKD in its place,
restore data.**

- Rejected: no rollback path. If the OKD instance has a problem we don't
  catch immediately, we have no working production to fall back to. The
  parallel-run + DNS cutover is the standard playbook for exactly this
  situation.

**C) Migrate the docker-compose stack first, then the prior runtime cluster.**

- Rejected: the docker-compose stack is not currently serving production
  traffic (the prior runtime cluster is, per the audit). The compose stack is
  legacy that should be torn down, not migrated. Including it in the
  migration sequence treats it as more important than it is.

**D) Skip the 7-day soak and decommission immediately after the cutover
smoke tests pass.**

- Rejected: the soak is the most valuable part of the sequence. Latent
  issues (memory leaks, slow PVC fill, certificate expiry edge cases,
  Velero backup chain corruption, off-hours traffic patterns) only show
  up over days, not minutes. Saving a week here means catching those
  issues in production after rollback is no longer cheap.

**E) Soak for 30 days instead of 7.**

- Rejected: diminishing returns. Most latent issues appear within the
  first week. 30 days adds operational drag (two clusters running, prior
  runtime consuming resources, decommission calendar slipping) without
  proportional confidence gain.

## Consequences

**Positive:**

- Zero customer-visible downtime if the cutover goes smoothly.
- 30-second rollback at any point during the cutover and soak.
- The 7-day soak catches the latent failure modes that synthetic smoke
  tests don't.
- Decommission is a deliberate step, not an afterthought — broken pods
  and orphaned containers get cleaned up explicitly.

**Negative:**

- 7 calendar days of dual-cluster resource consumption. On the homelab
  hardware (i9-13900K / 128GB RAM) this is comfortably within budget.
- The PR-16 → PR-17 → PR-18 sequence holds the merge train for at least
  a week, blocking other k8s work from landing during the soak. Mitigated
  by parking k8s work and continuing other Stronghold work on the
  builders branch in parallel.
- Velero / pg_dump restore of the prod data is a one-time operator
  action that needs a runbook. Mitigated by documenting it in PR-2.

**Trade-offs accepted:**

- We accept temporary dual-cluster resource cost in exchange for a
  rollback-at-every-step migration.
- We accept a one-week merge-train pause in exchange for catching latent
  issues before decommission.

## References

- Kubernetes documentation: "Cluster migration"
- Velero documentation: "Backup and Restore"
- Cloudflared documentation: "Configuration"
- Google SRE Book, chapter 8 ("Release Engineering")
- Charity Majors et al., "Database Reliability Engineering" chapter 9
  (data migration patterns)
- Martin Fowler, "BlueGreenDeployment" — martinfowler.com/bliki/BlueGreenDeployment.html
- ADR-K8S-006 (runtime selection), ADR-K8S-008 (prod/dev isolation)
