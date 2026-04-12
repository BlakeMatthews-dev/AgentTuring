# ADR-K8S-016 — GitOps controller: OpenShift GitOps (Argo CD)

**Status:** Proposed
**Date:** 2026-04-08
**Deciders:** Stronghold core team

## Context

Per ADR-K8S-006, the Stronghold chart at `deploy/helm/stronghold` is the
source of truth for cluster state. `helm install` and `helm upgrade`
apply that chart, and `helm diff` can preview the effect of a chart
change. This pipeline is sufficient for an operator sitting at a
terminal intentionally running Helm commands. It is not sufficient for
a governance platform.

Two concrete gaps motivate adding a GitOps controller.

**Drift goes undetected.** `helm install` is an imperative one-shot.
Once it finishes, the chart and the live cluster are related only by
whatever `helm` recorded in its release history. If someone runs
`oc edit deployment stronghold-api` at 2 AM to bump a replica count
during an incident, Helm does not know the cluster drifted from the
chart. The next `helm upgrade` will overwrite the edit (possibly at an
inconvenient time), and in the meantime nobody has a standing answer
to the question "does the live cluster match what the chart says?"
without a manual `helm diff` on every install target.

**Answering "is this cluster in the state the chart describes" is
expensive and ad-hoc.** Running `helm diff` against every installation
takes O(N) operator attention per check. A drift between chart and
cluster is only visible if someone thinks to run the diff. A platform
team with more than one install target needs continuous reconciliation
of intent (chart) vs state (cluster), and the answer needs to show up
on a dashboard, not in the operator's terminal history.

A continuous reconciler that watches the git repository and compares it
to the live cluster solves both gaps. The question is which reconciler
and how much autonomy it gets.

## Decision

**We install OpenShift GitOps Operator (Red Hat-packaged Argo CD) via
OperatorHub and configure it to track the Stronghold chart with manual
sync.** The operator installs into a dedicated namespace
(`openshift-gitops`). Argo CD `Application` custom resources point at
`deploy/helm/stronghold` in the Stronghold repo, with one Application
per environment: `stronghold-prod`, `stronghold-dev`, `stronghold-e2e`.

### Sync policy

Every Application uses:

```yaml
syncPolicy:
  automated: null          # manual sync
  syncOptions:
    - CreateNamespace=true
    - ApplyOutOfSyncOnly=true
  retry: null
```

Specifically:

- **`automated: null`** — no auto-sync. An operator (or a CI job) must
  click Sync in the Argo CD UI or run `argocd app sync <name>` to apply
  a change.
- **`selfHeal: false`** — no auto-revert of out-of-band edits. If an
  oncall operator runs `oc edit` during an incident, Argo CD shows the
  resource as `OutOfSync` but does not overwrite it.
- **`prune: false`** — manual sync does not delete resources that were
  removed from the chart. Pruning is a separate deliberate action.

Drift is **visible**, never **auto-corrected**. Every Application's
Sync status in the UI answers the "does the live cluster match the
chart?" question in O(1) human time. Every out-of-band edit shows up as
a diff that the operator can inspect, decide on, and either revert
(via Sync) or fold back into the chart (via a PR).

### Why Red Hat-packaged Argo CD specifically

OpenShift GitOps is Red Hat's packaging of upstream Argo CD as an
OperatorHub-installable operator. Choosing it rather than the upstream
Helm chart gives us:

1. **One-click install from the OpenShift Web Console.** No Helm-of-
   Helms wrangling for the GitOps tool itself — OperatorHub handles
   install, upgrade, and lifecycle. This follows the
   OpenShift-first principle from ADR-K8S-006.
2. **Integrated OpenShift OAuth.** The Argo CD Web UI authenticates
   against OpenShift's own OAuth server, so cluster-admin users get
   full GitOps access automatically and non-admins inherit the cluster
   RBAC they already have. No second identity provider to configure.
3. **Red Hat support is available if Stronghold customers deploy on
   paid OpenShift Container Platform.** The same operator runs on
   OKD (our homelab) and OCP (customers), so the GitOps story does not
   fork between the two.
4. **Operator-managed upgrades.** When a new Argo CD version lands,
   OpenShift GitOps handles the upgrade as an operator reconciliation,
   not as a Helm chart bump.

### Why manual sync rather than auto-sync

Manual sync is a deliberate choice for a governance platform, and the
decision turns on one specific scenario.

Scenario: an oncall operator is investigating a production incident at
2 AM. They run `oc edit configmap stronghold-api-config` to add a
debug logging flag. They are reading the resulting logs to diagnose
the failure.

With auto-sync (`automated: { prune: true, selfHeal: true }`), Argo CD
detects the drift within its reconcile interval (default 3 minutes),
reverts the ConfigMap to the chart's version, and restarts the pods
that consumed it. The operator loses their diagnostic context, the
debug flag is gone, and the logs they were reading stop flowing. The
reconcile loop has actively sabotaged the debugging session.

With manual sync, Argo CD marks the ConfigMap as `OutOfSync`, leaves
it alone, and the operator's diagnostic window stays open until they
explicitly reconcile. Once the incident is resolved, either:

- The operator folds the debug flag into the chart via a PR and
  reconciles (normal path), or
- The operator runs `argocd app sync` to revert the edit, knowing
  exactly why that is safe.

Either way, the state transition is auditable and intentional, and the
debug window was not yanked out from under a human investigating a
live issue. **In a governance platform, every state transition must be
auditable — and that includes the state transition that reverts an
edit.** Auto-sync hides that transition inside a reconcile loop.

### What auto-sync would cost

Auto-sync is attractive for its "cluster is always in git-declared
state" property. For Stronghold's homelab reference deployment, we give
that up in exchange for the debugging-safety property above. Customers
who want auto-sync on their own Stronghold deployment can set it on
their Application resource; the Stronghold chart does not prescribe it
for them. The decision in this ADR is only about the reference
deployment's default.

## Alternatives considered

**A) Flux v2 as the GitOps controller.**

- Rejected: no native OpenShift packaging via OperatorHub. Installing
  Flux on OKD means maintaining its own Helm install, managing its
  upgrade cycle by hand, and wiring OpenShift OAuth to its UI as a
  secondary integration. Flux is an excellent GitOps controller in its
  own right, but on an OpenShift distro it is second-class compared to
  the operator that ships in OperatorHub. The
  OpenShift-first principle from ADR-K8S-006 says pick the tool the
  platform packages.

**B) Vanilla Argo CD via its upstream Helm chart.**

- Rejected: bypasses OperatorHub lifecycle management, forces us to
  manage Argo CD upgrades by hand, and does not get the OpenShift OAuth
  integration out of the box. We would be reinventing the operator's
  packaging for no benefit — the underlying Argo CD binary is the same
  in both cases.

**C) No GitOps controller; rely on `helm diff` and operator discipline
to catch drift.**

- Rejected: addresses neither of the motivating gaps. Drift is only
  caught if an operator thinks to run `helm diff`, which turns
  reconciliation into a manual O(N) polling loop. The Argo CD resource
  tree and field-level diff view answers the same question in O(1)
  human time. The operator-discipline approach is the current state
  and the reason for this ADR.

**D) Auto-sync with `selfHeal: true` and `prune: true` everywhere.**

- Rejected: silently overwrites `oc edit` changes that operators make
  during incidents. Hostile to debugging. A governance platform cannot
  afford a reconcile loop that undoes deliberate operator actions
  without their knowledge.

**E) A custom reconciler written specifically for Stronghold.**

- Rejected: Argo CD has been solving this problem for years across
  thousands of deployments. Writing a custom reconciler means
  reinventing the diff engine, the resource tree visualization, the
  RBAC model, the sync-hooks framework, and the failure-handling
  machinery. The effort is enormous and the result would be worse than
  what Argo CD already does.

## Consequences

**Positive:**

- "Does the live cluster match the chart?" is answered continuously on
  a dashboard, not on demand in a terminal.
- Out-of-band edits are visible as diffs rather than invisible until
  the next `helm upgrade` surprises someone.
- OpenShift OAuth integration means cluster RBAC flows into GitOps RBAC
  without duplicating identity.
- OperatorHub handles lifecycle so the platform team does not maintain
  the GitOps tool itself.
- The same tool (and the same Application CRs) work on customer OCP
  deployments with a Red Hat support contract.

**Negative:**

- One more operator running in the cluster (`openshift-gitops`), with
  its own Postgres-backed state. Modest resource cost on the homelab
  hardware.
- Operators must learn the Argo CD UI and CLI in addition to `helm`
  and `oc`. Mitigated by the fact that Argo CD UI is straightforward
  once an operator understands the sync/diff model.
- Manual sync means operators must remember to reconcile after a chart
  merge. Mitigated by a CI job that posts a Slack message when an
  Application is `OutOfSync` for more than N hours.

**Trade-offs accepted:**

- We accept manual sync (and the operator-burden of reconciling) in
  exchange for never surprising an incident responder with a silent
  revert of their `oc edit`.
- We accept the operator footprint of OpenShift GitOps in exchange for
  continuous drift visibility across all install targets.

## References

- OpenShift Container Platform 4.14 documentation: "OpenShift GitOps"
- Argo CD documentation: "Argo CD Application"
- Argo CD documentation: "Automated Sync Policy" and "Sync Options"
- Kubernetes documentation: "Declarative Management of Kubernetes
  Objects Using Configuration Files"
- Helm documentation: "Helm diff plugin"
- Google SRE Book, chapter 8 ("Release Engineering") — on the value of
  continuous state reconciliation
- ADR-K8S-006 (runtime selection), ADR-K8S-008 (prod/dev isolation),
  ADR-K8S-017 (architecture diagram pipeline)
