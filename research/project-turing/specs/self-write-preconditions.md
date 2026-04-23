# Spec 35 — Self-write preconditions: bootstrap-complete + active_now cache + cross-self guards

*Three small invariants on the self-write path that together close F33 (bootstrap-check on tools), F29 (active_now cache), and F24 partial (repo-level cross-self guards).*

**Depends on:** [self-schema.md](./self-schema.md), [self-bootstrap.md](./self-bootstrap.md), [self-surface.md](./self-surface.md), [activation-graph.md](./activation-graph.md).
**Depended on by:** [warden-on-self-writes.md](./warden-on-self-writes.md), [self-write-budgets.md](./self-write-budgets.md), [repo-self-id-enforcement.md](./repo-self-id-enforcement.md).

---

## Current state

- `note_passion`, `write_self_todo`, etc. do not check whether the self's bootstrap is complete. A mid-bootstrap crash followed by arbitrary writes leaves a half-specced self that passes later `recall_self()` checks only because facets happen to exist — but answers and mood may not.
- `active_now` recomputes every call; no caching. Every `recall_self()` pays `O(nodes × contributors)` of table scans.
- Repo methods accept `SelfNode` rows without validating that `acting_self_id == node.self_id` — the tool-surface layer does these checks inconsistently.

## Target

1. A `_bootstrap_complete(self_id)` predicate, called from every write-tool entry, raising `SelfNotReady` pre-bootstrap.
2. A 30-second in-process cache for `active_now`, keyed by `(node_id, ctx.hash)`, invalidated on any contributor write/retraction touching the node or any of its sources.
3. An `acting_self_id` parameter on every `SelfRepo.update_*`, `SelfRepo.insert_contributor`, `SelfRepo.insert_todo_revision`, and related methods; mismatch raises `CrossSelfAccess`.

## Acceptance criteria

### Bootstrap-complete precondition

- **AC-35.1.** `_bootstrap_complete(repo, self_id)` returns True iff `count_facets == 24` AND `count_answers == 200` AND `has_mood`. Test for each False branch.
- **AC-35.2.** Every write-tool — `note_passion`, `note_hobby`, `note_interest`, `note_preference`, `note_skill`, `write_self_todo`, `revise_self_todo`, `complete_self_todo`, `archive_self_todo`, `practice_skill`, `downgrade_skill`, `rerank_passions`, `write_contributor`, `record_personality_claim`, `retract_contributor_by_counter`, `note_engagement`, `note_interest_trigger` — calls `_bootstrap_complete` first; failure raises `SelfNotReady`. Test per tool.
- **AC-35.3.** `recall_self` and `render_minimal_block` already enforce this (spec 28 AC-28.25). Behavior unchanged.
- **AC-35.4.** Internal calls made by the bootstrap procedure itself — writing facets, items, answers, mood — do NOT go through these tools; they use the repo directly. The precondition does not fire on bootstrap. Test: bootstrap completes without raising.

### Active-now cache

- **AC-35.5.** `ActivationCache` is a process-local dict keyed by `(node_id, ctx.hash)` with TTL `ACTIVATION_CACHE_TTL = timedelta(seconds=30)`. Hit returns cached float; miss computes and stores. Test asserts ≤ 1 row-read for two consecutive `active_now` calls on the same node.
- **AC-35.6.** Writing a contributor (via `insert_contributor`, `mark_contributor_retracted`, or by a retrieval-contributor GC pass) invalidates cache entries for `target_node_id`. Test.
- **AC-35.7.** Mutating a source node (facet score update, skill practice, mood tick, passion strength change) invalidates cache entries for every target that has a contributor pointing from this source. Test with a small graph.
- **AC-35.8.** Cache is keyed on `ctx.hash`. The hash includes `self_id`, `now` rounded to the minute, and `retrieval_similarity` hash. Different retrieval contexts produce different cache entries. Test.
- **AC-35.9.** Cache size is bounded at `ACTIVATION_CACHE_MAX_ENTRIES = 1024` with LRU eviction. Test.

### Cross-self enforcement at the repo

- **AC-35.10.** Every `SelfRepo.update_*` method accepts `acting_self_id: str` as a keyword-only parameter and asserts `row.self_id == acting_self_id`; mismatch raises `CrossSelfAccess`. Tool-surface callers pass `self_id` through. Test per mutator.
- **AC-35.11.** `SelfRepo.insert_contributor(c, *, acting_self_id)` asserts `c.self_id == acting_self_id`. Test.
- **AC-35.12.** `SelfRepo.insert_todo_revision(r, *, acting_self_id)` asserts `r.self_id == acting_self_id`. Test.
- **AC-35.13.** Bootstrap-time inserts (facets, items, answers) pass `acting_self_id` too (they happen to always match). No regression in bootstrap flow.

### Edge cases

- **AC-35.14.** `active_now` concurrent reads on the same key don't double-fetch. An advisory lock per key is overkill; a thread-local first-writer-wins is acceptable (research scale). Test with a threaded harness.
- **AC-35.15.** Cache does not persist across restarts. Cold reads after restart see an empty cache. Test.
- **AC-35.16.** `_bootstrap_complete` itself does not go through the cache — it's a cheap count query. Test.

## Implementation

```python
# self_surface.py additions

class SelfNotReady(Exception):
    pass


def _bootstrap_complete(repo: SelfRepo, self_id: str) -> bool:
    return (
        repo.count_facets(self_id) == 24
        and repo.count_answers(self_id) == 200
        and repo.has_mood(self_id)
    )


def _require_ready(repo: SelfRepo, self_id: str) -> None:
    if not _bootstrap_complete(repo, self_id):
        raise SelfNotReady(self_id)


# Every write-tool begins with:
#     _require_ready(repo, self_id)
```

```python
# self_activation.py additions

_cache: dict[tuple[str, str], tuple[float, datetime]] = {}
ACTIVATION_CACHE_TTL = timedelta(seconds=30)
ACTIVATION_CACHE_MAX_ENTRIES = 1024


def active_now(repo, node_id, ctx):
    key = (node_id, ctx.hash)
    entry = _cache.get(key)
    if entry is not None and entry[1] > ctx.now - ACTIVATION_CACHE_TTL:
        return entry[0]
    ... # existing computation
    _cache[key] = (value, ctx.now)
    _evict_lru_if_needed()
    return value


def invalidate_cache_for(node_ids: Iterable[str]) -> None:
    keys = [k for k in _cache if k[0] in set(node_ids)]
    for k in keys:
        del _cache[k]
```

```python
# self_repo.py — every update_* and insert_contributor gains:
def update_skill(self, s: Skill, *, acting_self_id: str) -> None:
    if s.self_id != acting_self_id:
        raise CrossSelfAccess(f"{s.self_id} vs {acting_self_id}")
    ...
```

## Open questions

- **Q35.1.** Cache invalidation on source-node mutation requires knowing "every target that points at this source." A forward index `contributors_by_source[source_id] -> [target_node_id, ...]` avoids a full scan; worth maintaining.
- **Q35.2.** Thread-local cache is process-local. For multi-process deployments (e.g., a web server with workers), caches diverge. Research-branch is single-process; production port would need Redis or similar.
- **Q35.3.** `acting_self_id` on repo methods is verbose at every call-site. A context-variable based alternative (`with self_context(self_id): ...`) is cleaner but hides intent. Current spec keeps explicit parameter for auditability.
