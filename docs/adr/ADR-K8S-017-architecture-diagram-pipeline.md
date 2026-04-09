# ADR-K8S-017 — Architecture diagram pipeline

**Status:** Proposed
**Date:** 2026-04-08
**Deciders:** Stronghold core team

## Context

Stronghold's Kubernetes architecture has grown past the point where a
single hand-drawn diagram can stay accurate. With the namespace
topology from ADR-K8S-001, the four secrets backends from
ADR-K8S-003, the NetworkPolicy matrix from ADR-K8S-004, the two
execution surfaces from ADR-K8S-013, the six priority tiers from
ADR-K8S-014, and the GitOps controller from ADR-K8S-016, the cluster
has enough moving parts that any static diagram committed to the repo
goes stale within a few sprints unless it is regenerated from the
chart itself.

At the same time, a fully auto-generated diagram is a poor
communication tool. Tools that render Helm output to a diagram
enumerate every Deployment, Service, ConfigMap, Secret, Route, and
ServiceAccount the chart produces. The result is structurally accurate
but visually noisy: the eye cannot pick out the request-flow shape
from the mass of boxes, and the reader cannot tell which components
are hot paths and which are auxiliary. A generated diagram answers
"what does the chart produce?" but not "what story does the chart
tell?"

We need both: accurate structural diagrams that track the chart, and
narrative diagrams that convey intent, layering, and request flow.
Neither alone is enough.

Separately, the OpenShift Web Console already handles the
**runtime** visualization need — an operator debugging a live cluster
can use the Topology view to see running pods, their connections, and
their health. This ADR does not address that use case. It addresses
the **documentation** visualization need: what ships in the repo so
that a reader who has never seen the cluster can understand what the
chart deploys and how the pieces fit together.

## Decision

**Stronghold uses a two-track architecture diagram pipeline, both
tracks rendered by a single `make diagrams` target and both committed
to the repo under `docs/diagrams/`.**

### Track 1 — generated (ground truth)

A single command regenerates the authoritative structural diagram from
the Helm chart:

```
helm template deploy/helm/stronghold \
  -f deploy/helm/stronghold/values-prod-homelab.yaml \
  | kubediagrams -o docs/diagrams/generated/live-architecture.svg
```

Characteristics:

- **Accuracy guarantee** — the diagram is a function of the chart. If
  the chart changes, the diagram changes; if the diagram does not
  change, the chart has not changed structurally.
- **Scope** — every Deployment, StatefulSet, Service, Route,
  ConfigMap, Secret, ServiceAccount, and NetworkPolicy the chart
  renders.
- **Visual cost** — dense. Good for auditing "is there a Service for
  this Deployment?" and for PR review of structural changes. Poor for
  explaining the request flow to a reader new to the system.
- **Committed to the repo** — the SVG lives at
  `docs/diagrams/generated/live-architecture.svg` and is part of every
  PR that changes the chart. PR diffs of the SVG track structural
  changes concretely: a new Deployment shows up as a new node in the
  diff, a removed NetworkPolicy shows up as a removed edge.

### Track 2 — authored (narrative)

Hand-written diagram sources in D2 live under `docs/diagrams/authored/`.
Examples of what belongs here:

- `component-architecture.d2` — the layered view of ingress → Conduit
  → Router → LiteLLM → model providers, with the data plane (Postgres,
  Phoenix) as a separate band underneath.
- `request-flow-conversational.d2` — the hot path for a chat request
  from user-agent through oauth2-proxy, Conduit, classifier, router,
  LiteLLM, response stream.
- `request-flow-agentic.d2` — the cold path for a mission submission:
  Conduit enqueues, mission controller spawns a pod, pod streams
  progress events back through Postgres.
- `namespace-topology.d2` — ADR-K8S-001's four namespace classes
  rendered as a layout diagram.
- `priority-tiers.d2` — ADR-K8S-014's six tiers rendered as a
  columnar view showing surface, routing weight, and eviction order.

Characteristics:

- **Narrative strength** — hand-laid-out, highlights hot paths, uses
  color and size to signal importance, omits the noise that would
  obscure the story.
- **Staleness risk** — can and will drift from the chart. Mitigated
  by the ADR-first workflow: any architectural change that needs a
  new diagram starts with an ADR, and the ADR's PR includes the
  diagram update.
- **Rendered by the same `make diagrams` target** — D2 sources are
  compiled to SVG via the `d2` CLI during the make run, so contributors
  do not need to check in the SVG separately.

### Why both

The two tracks cover complementary axes.

- Track 1 is **accurate** and **noisy**. It answers "what exists?"
- Track 2 is **clear** and **potentially stale**. It answers "what
  story does it tell?"

A reader new to the codebase starts with the authored narrative
diagrams to understand the shape of the system, then falls through to
the generated diagram when they need to confirm a specific structural
claim. A reviewer of a chart PR checks the generated diagram's diff
to see what structurally changed, then updates the authored diagrams
if the change affects one of the narrative views.

Neither track alone does both jobs. Generated-only misses the
narrative. Authored-only misses the accuracy guarantee.

### CI gate

A GitHub Actions workflow check enforces the accuracy half of the
pipeline. A PR that modifies any file under
`deploy/helm/stronghold/templates/` must also update
`docs/diagrams/generated/live-architecture.svg` in the same diff. The
workflow:

1. Checks out the PR branch.
2. Runs `make diagrams` with a fixed `helm` and `kubediagrams`
   version.
3. Diffs the regenerated SVG against the committed one.
4. Fails the PR if the diff is non-empty and the PR also modified the
   chart templates.

The authored diagrams are not gated the same way — they are checked
manually during ADR review, because there is no deterministic function
from chart-state to narrative-story.

### What this pipeline does **not** cover

- **Runtime state.** The OpenShift Web Console Topology view handles
  that. A reader looking at the cluster should use the console, not
  static diagrams in the repo.
- **Per-tenant diagrams.** Tenant workloads live in
  `stronghold-tenant-<id>` namespaces that do not exist in the chart
  itself. They are managed by a separate per-tenant workflow and are
  outside the scope of this ADR.
- **Sequence diagrams at a call-by-call level.** Those belong in
  per-component READMEs or ADR illustrations, not in the top-level
  architecture diagrams. They use the same D2 pipeline if authored.

## Alternatives considered

**A) Hand-authored diagrams only.**

- Rejected: diagrams drift from the chart within weeks of any active
  development. Prior experience with hand-drawn architecture pictures
  on this project shows they are trustworthy for about one sprint and
  misleading after that. Without an accuracy-guaranteed track, the
  reader can never be sure whether a diagram is current or historical.

**B) Generated diagrams only.**

- Rejected: the generated output is too noisy and too component-level
  to tell the story. A reader looking at 80 boxes connected by 200
  edges cannot extract the "chat hot path vs mission cold path" story,
  nor the "which components are shared and which are per-tier" story.
  The narrative diagrams exist precisely because the chart's full
  structure is not self-explanatory.

**C) Third-party runtime visualization dashboards (Headlamp,
Kubevious, or similar).**

- Rejected: duplicates functionality already provided by the OpenShift
  Web Console Topology view on our runtime (ADR-K8S-006). Adding
  another tool means another component to install, upgrade, secure,
  and keep in sync with cluster RBAC. The Topology view is good
  enough for the runtime use case, and this ADR is about
  documentation, not runtime observability.

**D) Embed diagrams in each ADR inline, with no central
`docs/diagrams/` directory.**

- Rejected: several ADRs reference the same architecture view (chat
  hot path, namespace topology). Inlining means each ADR has its own
  drifting copy. A central directory with stable filenames lets
  multiple ADRs reference the same canonical diagram, and updating the
  canonical diagram updates every reference.

**E) Mermaid instead of D2 for the authored track.**

- Rejected on balance, not strongly. Mermaid is more widely understood
  and renders inline on GitHub without a build step, which is
  genuinely attractive. D2 is chosen because its layout engine
  produces cleaner results for the specific kind of layered
  architecture diagrams Stronghold needs, and because D2 supports
  container/grouping primitives that Mermaid does not. Teams that
  prefer Mermaid for their own ADRs can use it — the `make diagrams`
  target can accept either source format.

## Consequences

**Positive:**

- Structural accuracy is guaranteed by the generated track; the CI
  gate prevents chart changes from silently drifting away from the
  committed diagram.
- Narrative clarity is preserved in the authored track; new readers
  get a story, not a wall of boxes.
- PR review of chart changes gets a concrete visual diff of the
  structure, which catches "I accidentally removed a NetworkPolicy"
  issues at review time.
- The ADR set has a single place to reference architecture diagrams
  from, with stable filenames.

**Negative:**

- `make diagrams` becomes a required build step that must be
  reproducible in CI. Requires pinning versions of `helm`,
  `kubediagrams`, and the `d2` CLI. Mitigated by treating the diagram
  toolchain as a pinned dev-dependency in the repo.
- Two tracks mean two places to update when a major refactor happens.
  The generated track updates itself; the authored track is a manual
  burden. Acceptable cost for the clarity benefit.
- SVG diffs in PRs are hard for humans to read. Mitigated by the CI
  workflow rendering the before/after side-by-side in a PR comment on
  structural changes.

**Trade-offs accepted:**

- We accept the toolchain pinning cost in exchange for CI-enforced
  diagram accuracy.
- We accept the manual burden of the authored track in exchange for
  readable narrative diagrams that communicate intent.

## References

- Kubernetes documentation: "Viewing Pods and Nodes"
- OpenShift Container Platform 4.14 documentation: "Viewing cluster
  topology"
- kubediagrams project documentation
- D2 documentation (d2lang.com)
- Mermaid documentation (mermaid.js.org) — considered as alternative
- Simon Brown, "The C4 model for visualising software architecture" —
  c4model.com (on the value of layered, audience-specific diagrams)
- ADR-K8S-001 (namespace topology), ADR-K8S-006 (runtime selection),
  ADR-K8S-013 (hybrid execution model), ADR-K8S-014 (priority tiers),
  ADR-K8S-016 (GitOps controller)
