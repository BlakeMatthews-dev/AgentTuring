# Spec 51 — Per-kind node caps with activation-eviction (G8)

*Hard caps per kind per self; at-cap `note_*` archives the lowest-`active_now` existing row. Closes F15.*

**Depends on:** [self-nodes.md](./self-nodes.md), [activation-graph.md](./activation-graph.md), [memory-mirroring.md](./memory-mirroring.md), [self-write-preconditions.md](./self-write-preconditions.md).
**Depended on by:** [operator-review-gate.md](./operator-review-gate.md) (bulk-approve respects caps, AC-46.18).

---

## Current state

The self can accumulate unlimited passions, hobbies, interests, preferences, skills. Each adds to `recall_self()` payload and activation-graph compute. No eviction.

## Target

Hard caps per kind:
- passions ≤ 100
- hobbies ≤ 100
- interests ≤ 200
- preferences ≤ 500
- skills ≤ 200

At-cap `note_*` call archives the lowest-`active_now` existing same-kind row with `rationale = "capped"`, then inserts the new row.

## Acceptance criteria

### Cap values

- **AC-51.1.** Caps defined as constants in `self_nodes.py`; each is tunable via `turing.yaml`. Test defaults.
- **AC-51.2.** `NODE_CAP_BY_KIND: dict[NodeKind, int]` exposes the caps. Lookup returns the configured or default cap. Test.

### Eviction semantics

- **AC-51.3.** `note_passion(...)` when count is at cap:
  1. Rank every existing passion by `active_now(p, ctx)`.
  2. Archive the lowest-activation row by setting `strength = 0.0` and updating `updated_at`.
  3. Mirror an OBSERVATION `"I archived passion '{text}' (active_now={score:.3f}) to make room for '{new_text}'"`, `intent_at_time = "cap-evict"`.
  4. Proceed with the insert.
  Test.
- **AC-51.4.** Analogous paths for `note_hobby`, `note_interest`, `note_preference`, `note_skill`. Test per kind.
- **AC-51.5.** `note_skill` eviction specifically sets `stored_level = 0.0` AND `decay_rate_per_day = MAX_DECAY` — "the skill is archived and decays fast if somehow resurrected." Test.
- **AC-51.6.** `note_preference` eviction sets `strength = 0.0`. Test.
- **AC-51.7.** `note_hobby` and `note_interest` have no strength field; eviction sets `description = "[archived]"` AND `last_engaged_at = None` / `last_noticed_at = None`. Test.

### Tie-breaking

- **AC-51.8.** If multiple rows tie on `active_now`, evict the one with the oldest `created_at` (oldest acquisition loses). Test.
- **AC-51.9.** Evicted rows remain queryable for audit (soft archive). No hard delete. Test.

### Cap reporting

- **AC-51.10.** `stronghold self inspect caps` lists per-kind current count / cap / %full. Test.
- **AC-51.11.** Prometheus gauge `turing_self_nodes_count{kind, self_id}` exposes current count per kind. Test.

### Edge cases

- **AC-51.12.** Eviction happens BEFORE the new insert in the same transaction. If the new insert fails (e.g., duplicate text via spec 24 AC-24.1), the eviction rolls back too. Test.
- **AC-51.13.** Evicting a row that is the motivator of live todos: the todos remain but `list_active_todos` surfaces them with `motivator_state = "archived"` (spec 26 AC-26.21). Test.
- **AC-51.14.** Evicting a row with self-authored contributors pointing from it: the contributors are NOT retracted automatically. They become low-signal (source_state ≈ 0 because source strength = 0). Operator may retract via `stronghold self digest`. Test.
- **AC-51.15.** Per-request budget (spec 37) still applies — eviction + insert still counts as one `new_nodes` consumption. Test.
- **AC-51.16.** `contributes_to` kwarg on a note call that triggers eviction: the new node's contributors materialize normally; the evicted node's contributors are untouched. Test.

## Implementation

```python
# self_nodes.py

from .self_activation import active_now, ActivationContext

NODE_CAP_BY_KIND: dict[NodeKind, int] = {
    NodeKind.PASSION: 100,
    NodeKind.HOBBY: 100,
    NodeKind.INTEREST: 200,
    NodeKind.PREFERENCE: 500,
    NodeKind.SKILL: 200,
}


def _evict_if_at_cap(repo, self_id: str, kind: NodeKind, new_text: str) -> None:
    cap = NODE_CAP_BY_KIND[kind]
    existing = _list_by_kind(repo, self_id, kind)
    if len(existing) < cap:
        return
    ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
    ranked = sorted(
        existing,
        key=lambda node: (active_now(repo, node.node_id, ctx), node.created_at),
    )
    victim = ranked[0]
    _archive(repo, kind, victim, acting_self_id=self_id)
    memory_bridge.mirror_observation(
        self_id=self_id,
        content=(
            f"I archived {kind.value} '{_display(victim)}' "
            f"(active_now={active_now(repo, victim.node_id, ctx):.3f}) "
            f"to make room for '{new_text}'."
        ),
        intent_at_time="cap-evict",
        context={"kind": kind.value, "evicted_id": victim.node_id,
                 "incoming_label": new_text},
    )
```

## Open questions

- **Q51.1.** Caps are generous (100–500). The intent is "room to accrete over months without hitting the ceiling for normal users." Observation over time will tell us whether the self churns nodes rather than deepening them.
- **Q51.2.** `MAX_DECAY` for archived skills is a stronger signal than `stored_level = 0`; it means any accidental `practice_skill` call requires proportionally more attention to revive. Tunable.
- **Q51.3.** Eviction by lowest-activation is meritocratic; alternatives are LRU-on-engagement (passions haven't moved), oldest-by-creation (rotate out seniors), or operator-selected. Meritocratic default is easy to reason about.
- **Q51.4.** No cap on personality facets (always 24) or todos (soft threshold in spec 26). Cap applies to the five accreting node kinds only.
