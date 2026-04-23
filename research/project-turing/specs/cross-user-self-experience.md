# Spec 67 — Cross-user self-experience

*With one global self and N users (spec 54 threads), how does experience with User A affect routing for User B? This spec makes the policy explicit rather than default-shared.*

**Depends on:** [conversation-threads.md](./conversation-threads.md), [activation-graph.md](./activation-graph.md), [semantic-retrieval.md](./semantic-retrieval.md), [session-scoped-mood.md](./session-scoped-mood.md), [forensic-tagging.md](./forensic-tagging.md), [self-as-conduit.md](./self-as-conduit.md).
**Depended on by:** —

---

## Current state

The research branch deploys a single global self across all users (DESIGN.md §6.5). Spec 54 adds per-user conversation threads and per-user quotas. Spec 58 adds per-conversation mood. But the self's **memories** and **activation graph** are shared — a bad experience with User A's request taints routing for User B if their requests semantically overlap.

This is a feature in the research posture (one self, continuous experience), but it's unbounded. Nothing prevents the self from saying to User B "I've learned to be wary of requests like this" when the evidence comes from an unrelated User A.

## Target

Make the cross-user-influence policy explicit with three dials:

1. **Memory scope propagation:** by default, memories born from one user's request carry `context.source_user_id`; retrieval during another user's request applies a `CROSS_USER_DAMPENING` multiplier on their weight.
2. **Activation-graph propagation:** contributors born from cross-user retrieval respect the dampening.
3. **User-scoped memory tier:** a new tier marker `USER_SCOPED` (orthogonal to memory tier) means "do not surface this memory across user boundaries." Self writes to this marker by default when observing a user-specific detail; default is permissive (cross-user share) except when explicitly scoped.

## Acceptance criteria

### Memory tagging

- **AC-67.1.** Schema addition: every memory table adds a nullable column `source_user_id TEXT` and a non-null boolean `user_scoped` (default `False`). Test.
- **AC-67.2.** When a memory is written inside a conversation scope (spec 54 `conversation_scope` variable extended to carry `owner_user_id`), `source_user_id` is populated from the conversation's owner. Test.
- **AC-67.3.** Memories written outside a conversation (scheduled tasks, reflection, bootstrap) have `source_user_id IS NULL`. Test.

### `user_scoped` marker

- **AC-67.4.** The `user_scoped: bool` column defaults `False` — the research-branch default is "shared self." Writes opt in to scoping.
- **AC-67.5.** The self can mark a memory `user_scoped` via an optional `scope_to_user` flag on the write-paths. Example: `write_paths.write_observation(..., scope_to_user=True)` sets `user_scoped = True`, `source_user_id = current_user_id`. Test.
- **AC-67.6.** Memory mirror helpers (spec 32) take an optional `scope_to_user: bool`. Default `False`. Any memory from a conversation context has `source_user_id` populated regardless. Test.

### Retrieval damping

- **AC-67.7.** Semantic retrieval (spec 16) applies cross-user dampening:
  ```
  effective_weight = memory.weight × (
      1.0                      if source_user_id IS NULL
      or source_user_id == current_user_id,
      CROSS_USER_DAMPENING     otherwise
  )
  ```
  `CROSS_USER_DAMPENING = 0.6` (runtime-configurable). A `user_scoped = True` memory returns `effective_weight = 0` when cross-user (fully hidden). Test each branch.

### Activation-graph propagation

- **AC-67.8.** Retrieval contributors (spec 25) born from cross-user memories carry a `cross_user: bool` annotation in their `context` (JSON column addition on the contributor row). Their `weight` is further scaled by `CROSS_USER_DAMPENING` at materialization. Test.
- **AC-67.9.** Durable `origin=self` contributors are NOT dampened. The self's own durable authorship reflects its consolidated self-view, independent of the user triggering retrieval. Test.
- **AC-67.10.** Rule-origin contributors are not dampened. Test.

### Revealed via `recall_self()`

- **AC-67.11.** `recall_self()` output includes a `cross_user_memory_ratio` stat: fraction of top-K retrieval contributors whose source is a different user. Test.
- **AC-67.12.** The self can identify: "I've been thinking about {user_count} users today." Test.

### Operator knobs

- **AC-67.13.** `turing.yaml` option `cross_user_policy: "shared" | "dampened" | "isolated"`:
  - `shared`: `CROSS_USER_DAMPENING = 1.0` — full cross-user sharing (legacy).
  - `dampened`: `CROSS_USER_DAMPENING = 0.6` (default).
  - `isolated`: `CROSS_USER_DAMPENING = 0.0` — cross-user retrieval returns zero weight. Effectively per-user memory.
  Test each policy.
- **AC-67.14.** Changing `cross_user_policy` at runtime requires a process restart. Logged on startup. Test.

### Per-user activation view

- **AC-67.15.** New function `active_now_for_user(repo, node_id, ctx, user_id)` — computes activation with per-user dampening applied. The default `active_now` continues to apply whatever `conversation_scope.owner_user_id` is set to; this function is an explicit override for scheduled tasks or analysis. Test.

### Observability

- **AC-67.16.** Prometheus counter `turing_memory_cross_user_reads_total{source_user, current_user}`. Test.
- **AC-67.17.** Gauge `turing_memory_by_scope{user_scoped="true"|"false"}`. Test.

### Edge cases

- **AC-67.18.** A request without a `user` field (anonymous, per spec 54 AC-54.4) — the self treats `anonymous` as a distinct user. Cross-user dampening applies between `anonymous` and any other user. Test.
- **AC-67.19.** A `user_scoped = True` memory authored by User A and later retrieved in a request from User A: full weight (not dampened). Test.
- **AC-67.20.** Spec 63 `learning_extraction` and spec 64 `affirmation_candidacy` detectors should avoid proposing learnings/commitments from cross-user patterns unless the pattern is robust **within** each user. New AC on those detectors: respect `source_user_id` — require hits to span at least 2 users before promoting. Test.
- **AC-67.21.** `recall_self` itself is not user-scoped — it reports the self's global state. But the `active_now` values it reports respect the current user context. Test.
- **AC-67.22.** Per-user mood is NOT introduced here — that would be spec 68+. Session mood (spec 58) handles the per-conversation tilt; user-level mood would need its own design.

### Bootstrap memories

- **AC-67.23.** Bootstrap memories (200 HEXACO answers, finalize LESSON) have `source_user_id IS NULL` — they belong to the self, not any user. Test.

## Implementation

```python
# self_cross_user.py

class CrossUserPolicy(StrEnum):
    SHARED = "shared"
    DAMPENED = "dampened"
    ISOLATED = "isolated"


_POLICY_DAMPENING: dict[CrossUserPolicy, float] = {
    CrossUserPolicy.SHARED: 1.0,
    CrossUserPolicy.DAMPENED: 0.6,
    CrossUserPolicy.ISOLATED: 0.0,
}


def cross_user_dampening(policy: CrossUserPolicy) -> float:
    return _POLICY_DAMPENING[policy]


def effective_memory_weight(
    memory_weight: float, memory_source_user_id: str | None,
    memory_user_scoped: bool, current_user_id: str, policy: CrossUserPolicy,
) -> float:
    if memory_source_user_id is None or memory_source_user_id == current_user_id:
        return memory_weight
    if memory_user_scoped:
        return 0.0
    return memory_weight * cross_user_dampening(policy)
```

Schema migration adds `source_user_id TEXT` and `user_scoped INTEGER NOT NULL DEFAULT 0` to `episodic_memory` and `durable_memory`. Index on `source_user_id` for efficient per-user queries.

Semantic retrieval (spec 16) augments its query with per-row dampening post-processing.

## Open questions

- **Q67.1.** Default `dampened` vs `shared`: the research posture ("one continuous self") argues for `shared`. The reality ("I shouldn't leak User A's concerns into User B's routing") argues for `dampened`. Defaulting to `dampened` is defensive; operators can switch to `shared` for the maximal-autonoetic experiment.
- **Q67.2.** 0.6 dampening is a guess. A value of 1.0 is "full sharing"; 0.0 is "isolation." 0.6 says "cross-user memory is relevant but de-emphasized." Empirical tune.
- **Q67.3.** Self-authored durable memories are NOT dampened (AC-67.9). Rationale: AFFIRMATIONs like "I route writing tasks to Scribe" should hold across users. But a durable memory with a specific user reference embedded in content is leaky by its content, not by its mechanism. Content-level leakage is out of scope.
- **Q67.4.** Learning-detector extension (AC-67.20) requires cross-user robustness. May starve the detector on low-user deployments (single user → no cross-user evidence ever). Operator can tune `LEARNING_USER_DIVERSITY_MIN = 1` for single-user deployments.
- **Q67.5.** The `cross_user_memory_ratio` stat in `recall_self` gives the self a meta-view of how much of its current thinking comes from other users. Useful self-knowledge or creepy self-surveillance? Operator-visible in any case.
