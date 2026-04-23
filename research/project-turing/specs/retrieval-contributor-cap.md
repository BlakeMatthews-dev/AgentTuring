# Spec 38 — Retrieval-contributor cap (G5)

*Bounded per-target count AND bounded weight-sum for `origin = retrieval` contributors materialized per request. Closes F4.*

**Depends on:** [activation-graph.md](./activation-graph.md), [semantic-retrieval.md](./semantic-retrieval.md), [conduit-runtime.md](./conduit-runtime.md).
**Depended on by:** —

---

## Current state

Spec 25 AC-25.11 specifies top-K (default 8) retrieval contributors per target per request. The implementation does not exist yet (to be shipped in Tranche 7.3). No cap on the **sum** of retrieval weights into a single target is specified.

## Target

Add a weight-sum cap: for any target node, `Σ |weight|` across `origin = retrieval` contributors within one request is bounded by `RETRIEVAL_SUM_CAP = 1.0`. Once the cap would be exceeded, lower-similarity matches are dropped rather than materialized. Count cap remains `K_RETRIEVAL_CONTRIBUTORS = 8`.

## Acceptance criteria

### Materialization

- **AC-38.1.** `materialize_retrieval_contributors(self_id, target_ids, similarity_map)` takes a per-target dict of `{source_id: similarity}` and inserts at most `K_RETRIEVAL_CONTRIBUTORS` contributors per target. Test.
- **AC-38.2.** Contributors are inserted in descending similarity order; ties broken by lexical `source_id` for determinism. Test.
- **AC-38.3.** For each target, insertion stops once the running `Σ |weight|` would exceed `RETRIEVAL_SUM_CAP`. The current row is dropped; lower-similarity rows are not tried (they would be smaller and still fit — but the cap's intent is "limit total influence," so we stop). Test.
- **AC-38.4.** If no contributor fits (very high similarities mapped to high weights), at least one is still inserted at the reduced weight `RETRIEVAL_SUM_CAP` to preserve the "something matched" signal. Test.

### Weight transform

- **AC-38.5.** `weight = similarity × RETRIEVAL_WEIGHT_COEFFICIENT` where `RETRIEVAL_WEIGHT_COEFFICIENT = 0.4` (spec 25 default). Clamped to `[0.0, RETRIEVAL_WEIGHT_COEFFICIENT]`. Test.
- **AC-38.6.** `expires_at = now() + RETRIEVAL_TTL` (spec 25 default 5 minutes). Test.

### Per-request scope

- **AC-38.7.** Retrieval materialization runs once per request, at the perception step start (spec 44). Test that two requests in the same minute materialize independently.
- **AC-38.8.** Materialization writes through the same repo path that `write_contributor` uses; `origin=retrieval`, `expires_at` set. Forensic tags (spec 39) attach per request. Test.

### Aggregate bounds

- **AC-38.9.** After materialization, for any `target_node_id`: `count(origin='retrieval', non-expired) ≤ K_RETRIEVAL_CONTRIBUTORS` AND `Σ |weight| ≤ RETRIEVAL_SUM_CAP`. Property test over 100 randomized similarity fixtures.
- **AC-38.10.** Count cap and sum cap are both enforced — a fixture with 50 low-similarity hits (each weight 0.05) stops at 8 even though their sum would fit. A fixture with 3 high-similarity hits (each 0.4) stops at 2 (sum 0.8 + third = 1.2 > 1.0 → drop third). Test both shapes.

### Metrics

- **AC-38.11.** Prometheus gauge `turing_retrieval_contributors_active{self_id}` reports current active retrieval-contributor count. Test.
- **AC-38.12.** Counter `turing_retrieval_contributors_dropped_total{reason, self_id}` increments on each drop — `reason in {count_cap, sum_cap}`. Test.

### Edge cases

- **AC-38.13.** Zero retrieval hits into a target: no rows inserted; `active_now` falls back to durable contributors only. Test.
- **AC-38.14.** A similarity above 1.0 (cosine outside expected range due to numerical error) clamps to 1.0 before weight computation. Test.
- **AC-38.15.** Materialization is idempotent within a request; calling it twice inserts no duplicates (second call is a no-op, logged). Test.

## Implementation

```python
# self_retrieval_materialize.py (new module)

K_RETRIEVAL_CONTRIBUTORS: int = 8
RETRIEVAL_SUM_CAP: float = 1.0


def materialize_retrieval_contributors(
    repo, self_id: str, now: datetime,
    per_target: dict[str, dict[str, float]],
    new_id,
) -> dict[str, int]:
    expires = now + RETRIEVAL_TTL
    inserted: dict[str, int] = {}
    for target_id, hits in per_target.items():
        sorted_hits = sorted(
            hits.items(), key=lambda kv: (-kv[1], kv[0]),
        )
        running_sum = 0.0
        count = 0
        for source_id, sim in sorted_hits:
            if count >= K_RETRIEVAL_CONTRIBUTORS:
                metrics.dropped_total.labels(reason="count_cap", self_id=self_id).inc()
                break
            sim_clamped = min(1.0, max(0.0, sim))
            weight = sim_clamped * RETRIEVAL_WEIGHT_COEFFICIENT
            if running_sum + weight > RETRIEVAL_SUM_CAP:
                if count == 0:
                    weight = RETRIEVAL_SUM_CAP  # AC-38.4
                else:
                    metrics.dropped_total.labels(reason="sum_cap", self_id=self_id).inc()
                    break
            repo.insert_contributor(ActivationContributor(
                node_id=new_id("contrib"),
                self_id=self_id,
                target_node_id=target_id,
                target_kind=_kind_for(target_id),
                source_id=source_id,
                source_kind="retrieval",
                weight=weight,
                origin=ContributorOrigin.RETRIEVAL,
                rationale="retrieval",
                expires_at=expires,
            ), acting_self_id=self_id)
            running_sum += weight
            count += 1
        inserted[target_id] = count
    return inserted
```

## Open questions

- **Q38.1.** AC-38.4 guarantees at least one contributor per target when hits exist. This can **slightly exceed** `RETRIEVAL_SUM_CAP` when the single retained contributor is re-weighted to the cap. The sum-over-all-targets is not bounded by this rule; only per-target. Fine for the "per-target influence" semantics.
- **Q38.2.** Tie-break by lexical `source_id` is deterministic but slightly arbitrary. An alternative is memory creation time (newer wins), which is closer to "most recent relevant experience." Deferred.
- **Q38.3.** The `target_ids` parameter is the set of nodes the perception step considers. That set could be large (24 facets + N passions + ...). Per-target materialization scales as O(targets × K). Cap total contributors per request at `MAX_RETRIEVAL_CONTRIBUTORS_PER_REQUEST = 200` if this becomes a performance issue.
