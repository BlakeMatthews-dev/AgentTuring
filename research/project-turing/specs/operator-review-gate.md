# Spec 46 — Operator review gate on facet/passion contributors (G12)

*Self-authored `write_contributor` into `personality_facet` or `passion` targets routes through a `pending` staging table; operator ACK moves rows to live. Decline patterns surface in the same weekly digest. Closes F18, F22.*

**Depends on:** [activation-graph.md](./activation-graph.md), [self-tool-registry.md](./self-tool-registry.md), [memory-mirroring.md](./memory-mirroring.md), [forensic-tagging.md](./forensic-tagging.md).
**Depended on by:** —

---

## Current state

`write_contributor(origin=self, target_kind=personality_facet or passion)` writes directly into `self_activation_contributors` and immediately influences `active_now`. The self programs its own ontology with no human in the loop. Separately, `decline` decisions leave only OPINION memories; nothing reviews accumulating patterns.

## Target

1. New staging table `self_contributor_pending` for self-authored facet and passion contributors. Unacked rows have no activation effect.
2. New table `self_routing_review` for `ask_clarifying` and `decline` decisions — surfaces patterns for operator review.
3. CLI: `stronghold self digest`, `stronghold self ack`.

## Acceptance criteria

### Staging table

- **AC-46.1.** `CREATE TABLE self_contributor_pending` with the same columns as `self_activation_contributors` plus `proposed_at TEXT NOT NULL`, `reviewed_at TEXT`, `review_decision TEXT CHECK (review_decision IN ('approve', 'reject', NULL))`, `reviewed_by TEXT`. Test.
- **AC-46.2.** `write_contributor(origin=self)` with `target_kind IN {personality_facet, passion}` inserts into `self_contributor_pending` instead of `self_activation_contributors`. Target kinds hobby/interest/preference/skill go to the live table (not gated) — preserves the self's daily autonomy for mundane structure. Test per kind.
- **AC-46.3.** Unacked pending rows are invisible to `active_now`. Test.

### Routing-review table

- **AC-46.4.** `CREATE TABLE self_routing_review(id, self_id, decision_kind, target, reason, request_hash, created_at, reviewed_at, reviewed_by)`. `decision_kind IN {ask_clarifying, decline}`. Test.
- **AC-46.5.** Every `ask_clarifying` and `decline` decision in the conduit writes a `self_routing_review` row in addition to the existing OPINION memory. Test.

### Digest CLI

- **AC-46.6.** `stronghold self digest [--since DATE] [--format md|json]` emits a structured report containing:
  - Pending contributors (count + per-target-kind breakdown + per-row details).
  - Routing-review entries: top-N decline targets by frequency; top-N clarification patterns.
  - Recently-archived nodes (from spec 51).
  - Warden-blocked self-write count (from spec 36).
  Default `--since = 7d`. Test with fabricated rows.
- **AC-46.7.** `stronghold self ack <pending_id> --approve|--reject [--note TEXT]`:
  - Approve: move row from `self_contributor_pending` to `self_activation_contributors`, set `reviewed_at`, `review_decision = approve`, `reviewed_by`. Mirror an OBSERVATION memory citing the operator's note.
  - Reject: leave in pending, set `review_decision = reject`, `reviewed_at`. Mirror an OBSERVATION.
  Test both.
- **AC-46.8.** `stronghold self ack-all --since DATE --approve` bulk-approves every pending row proposed before the date. Dry-run preview available via `--dry-run`. Test.

### Activation-graph consistency

- **AC-46.9.** Moving an approved pending row to the live table invalidates `active_now` caches for the target. Test.
- **AC-46.10.** A rejected pending row never becomes visible to `active_now`. Test.

### Operator-review-required lifetime

- **AC-46.11.** A pending row older than `PENDING_MAX_AGE = 30 days` with `review_decision IS NULL` is auto-rejected with `reviewed_by = "system:timeout"` at the next digest run. The self receives an OBSERVATION `"a contributor I proposed against {target} was not acted on and has timed out"`. Test.
- **AC-46.12.** Auto-rejected rows are listed in the next digest under a `"timed-out"` section. Test.

### Per-request budget interaction

- **AC-46.13.** Gated writes DO consume the per-request budget (spec 37) — the self tried to write, regardless of whether operator ACKs. Test.

### Observability

- **AC-46.14.** Prometheus gauge `turing_contributor_pending_count{self_id}`. Test.
- **AC-46.15.** Counter `turing_contributor_approved_total{target_kind, self_id}` and `turing_contributor_rejected_total{target_kind, self_id}`. Test.

### Edge cases

- **AC-46.16.** Narrative-revision claims (spec 31 AC-31.11) produce facet contributors, so they go through the gate. Test that `record_personality_claim` produces a pending row, not a live row.
- **AC-46.17.** A pending row's source node being archived before ACK — edge becomes meaningless. Auto-reject with `review_decision = reject` and `reviewed_by = "system:dangling-source"`. Test.
- **AC-46.18.** Bulk-approve must respect the target's contributor cap (spec 51) — if approving would exceed cap, refuse and report in the digest. Test.

## Implementation

```sql
CREATE TABLE IF NOT EXISTS self_contributor_pending (
    node_id         TEXT PRIMARY KEY,
    self_id         TEXT NOT NULL,
    target_node_id  TEXT NOT NULL,
    target_kind     TEXT NOT NULL,
    source_id       TEXT NOT NULL,
    source_kind     TEXT NOT NULL,
    weight          REAL NOT NULL CHECK (weight BETWEEN -1.0 AND 1.0),
    origin          TEXT NOT NULL DEFAULT 'self',
    rationale       TEXT NOT NULL,
    expires_at      TEXT,
    proposed_at     TEXT NOT NULL,
    reviewed_at     TEXT,
    review_decision TEXT CHECK (review_decision IN ('approve', 'reject')),
    reviewed_by     TEXT,
    CHECK (target_node_id <> source_id)
);

CREATE TABLE IF NOT EXISTS self_routing_review (
    id           TEXT PRIMARY KEY,
    self_id      TEXT NOT NULL,
    decision_kind TEXT NOT NULL CHECK (decision_kind IN ('ask_clarifying', 'decline')),
    target       TEXT,
    reason       TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    reviewed_at  TEXT,
    reviewed_by  TEXT
);
```

```python
# self_contributors.py

_GATED_TARGET_KINDS = {NodeKind.PERSONALITY_FACET, NodeKind.PASSION}


def write_contributor(repo, self_id, target_node_id, target_kind,
                      source_id, source_kind, weight, rationale, new_id,
                      origin=ContributorOrigin.SELF):
    _require_ready(repo, self_id)
    _warden_gate_self_write(rationale, "write contributor", self_id=self_id)
    _consume("contributors")

    if origin == ContributorOrigin.RETRIEVAL:
        raise ValueError("write_contributor cannot create retrieval edges")

    row = ActivationContributor(...)
    if origin == ContributorOrigin.SELF and target_kind in _GATED_TARGET_KINDS:
        repo.insert_pending_contributor(row, acting_self_id=self_id)
    else:
        repo.insert_contributor(row, acting_self_id=self_id)
        invalidate_cache_for([target_node_id])

    memory_bridge.mirror_observation(
        self_id=self_id,
        content=f"I proposed a contributor {source_id} -> {target_node_id} weight={weight}",
        intent_at_time="write contributor",
        context={...},
    )
    return row
```

## Open questions

- **Q46.1.** 30-day auto-reject is a default. Operators who monitor less frequently may prefer 90 days. Config.
- **Q46.2.** `ask_clarifying` appearing in the routing-review is a minor surveillance surface — the operator sees what users are asking about. Scope to `decline` only if privacy is a concern.
- **Q46.3.** Narrative claims all become pending. A self's reflective "I notice I've become more curious this week" doesn't auto-take-effect. Operator approval gates all trait updates from narrative. Friction, but the whole point. Revisit after a month of operator experience.
- **Q46.4.** Bulk-approve is convenient but circumvents the gate's safety. Consider a maximum batch size (e.g. ≤ 10 rows per `ack-all` call) to nudge operators toward review-in-detail.
