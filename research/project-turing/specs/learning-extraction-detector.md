# Spec 63 — Learning-extraction detector

*A background detector that finds fail → later-succeed patterns in routing history and proposes LESSON memories encoding what the self learned. Closes the `learning_extraction` deferred item from `specs/README.md`.*

**Depends on:** [detectors/README.md](./detectors/README.md), [motivation.md](./motivation.md), [self-reflection-ritual.md](./self-reflection-ritual.md), [memory-mirroring.md](./memory-mirroring.md), [activation-graph.md](./activation-graph.md).
**Depended on by:** [affirmation-candidacy-detector.md](./affirmation-candidacy-detector.md), [mood-affects-decisions.md](./mood-affects-decisions.md) (specialist preference derivation).

---

## Current state

Stronghold's self-improving-memory model extracts fail→succeed corrections from **tool-call** history (ARCHITECTURE.md). The Turing branch doesn't yet port that pattern to the **routing** history the self accumulates — a routing fails (REGRET minted), later a similar routing succeeds (AFFIRMATION or clean completion), and the pairing is never explicitly learned.

## Target

A detector that pairs REGRET / AFFIRMATION events by request similarity, extracts the routing choice that changed between them, and proposes a LESSON: `"For requests like X, routing to Y failed; routing to Z succeeded."` LESSONs feed into spec 11's tuning pipeline and the activation graph's specialist biases.

## Acceptance criteria

### Detector registration

- **AC-63.1.** Register a detector `learning_extraction` in the existing detector registry (spec D). Runs on a P40 schedule every 6 hours (configurable). Test detector is registered and fires on the schedule.
- **AC-63.2.** Per-run budget: `LEARNING_EXTRACTION_SAMPLE_SIZE = 100` most-recent REGRETs; `LEARNING_EXTRACTION_TIMEOUT_SEC = 30`. Test.

### Pattern detection

- **AC-63.3.** For each sampled REGRET memory with a routing context (`context.decision = "delegate"`), compute:
  - `regret_request_embedding` (via spec 16's embedding layer).
  - Semantic neighbors within a 30-day window, filtered to `context.decision = "delegate"` AND outcome memory is AFFIRMATION or clean completion.
  - Similarity threshold `LEARNING_SIMILARITY_MIN = 0.75`.
  Test.
- **AC-63.4.** If at least one match exists with a **different** `context.target` (specialist), the detector has found a learning. Record:
  ```
  {
    regret_memory_id,
    succeeded_memory_id,
    failed_specialist,
    succeeded_specialist,
    request_similarity,
  }
  ```
  Test.
- **AC-63.5.** A REGRET with no better-outcome match is skipped; the pattern requires evidence of a successful alternative. Test.

### Candidacy

- **AC-63.6.** Matches enter a `learning_candidates` queue:
  ```sql
  CREATE TABLE learning_candidates (
      id              TEXT PRIMARY KEY,
      self_id         TEXT NOT NULL,
      regret_memory_id TEXT NOT NULL,
      succeeded_memory_id TEXT NOT NULL,
      failed_specialist TEXT NOT NULL,
      succeeded_specialist TEXT NOT NULL,
      similarity      REAL NOT NULL,
      hits            INTEGER NOT NULL DEFAULT 1,
      proposed_at     TEXT NOT NULL,
      promoted_lesson_id TEXT,
      dismissed_at    TEXT
  );
  ```
  Test.
- **AC-63.7.** Repeated detections of the same `(failed_specialist, succeeded_specialist)` within `LEARNING_COALESCE_WINDOW = 14 days` increment `hits` on the existing row instead of creating a new one. Test.
- **AC-63.8.** A candidate reaches promotion threshold when `hits >= LEARNING_PROMOTION_FLOOR = 3`. Promotion is a LESSON-memory write:
  ```
  content = f"For requests like '{regret summary}', I've now observed {hits} times that routing to {succeeded} succeeds where {failed} doesn't. I lean toward {succeeded} for this shape."
  intent_at_time = "learning extracted"
  context = {hits, failed_specialist, succeeded_specialist}
  ```
  Test.

### Activation-graph integration

- **AC-63.9.** Promotion also adds a rule-origin contributor targeting the `succeeded_specialist` specialist node (spec 62 AC-62.8) with `weight = +0.1 × log(hits)`, `source_kind = "rule"`, `rationale = "learning: {regret summary}"`. Test.
- **AC-63.10.** Correspondingly, an inhibitory contributor on the `failed_specialist` specialist node with `weight = -0.05 × log(hits)`. Test.

### Dismissal

- **AC-63.11.** `stronghold self dismiss-learning <candidate_id> --reason TEXT` marks the candidate `dismissed_at`; removes any promoted LESSON memory (if already promoted); retracts the contributors via counter-contributors. Test.
- **AC-63.12.** Dismissed candidates do not re-emerge from subsequent detector runs — they're excluded by `dismissed_at IS NOT NULL`. Test.

### Observability

- **AC-63.13.** Prometheus counter `turing_learning_candidates_created_total{self_id}`, `turing_learning_candidates_promoted_total{self_id}`. Test.
- **AC-63.14.** `stronghold self digest` surfaces learning candidates pending promotion. Test.

### Edge cases

- **AC-63.15.** A REGRET with no embedding (embedding failure) is skipped with a log line. Test.
- **AC-63.16.** The detector never writes a LESSON that contradicts an existing un-dismissed LESSON for the same `(specialist pair, request-shape)` — detects and merges via `hits` increment instead. Test.
- **AC-63.17.** Promotion respects per-request write budget when firing during the detector's dispatch — detector runs at P40, budget-free. Test that no budget is consumed.
- **AC-63.18.** Similarity computation is bounded: comparing a REGRET against up to `LEARNING_NEIGHBOR_CAP = 50` candidate-success memories; beyond that, lowest-similarity are pruned. Test.

## Implementation

```python
# detectors/learning_extraction.py

LEARNING_SIMILARITY_MIN: float = 0.75
LEARNING_PROMOTION_FLOOR: int = 3
LEARNING_COALESCE_WINDOW: timedelta = timedelta(days=14)
LEARNING_NEIGHBOR_CAP: int = 50


def run(repo, self_id: str, now: datetime) -> int:
    regrets = repo.recent_regrets_with_routing_context(
        self_id=self_id, limit=100,
    )
    created = 0
    for regret in regrets:
        embedding = _embed_request(regret)
        neighbors = _semantic_neighbors(
            repo, self_id, embedding,
            filter={"decision": "delegate", "outcome_tier": ("affirmation", "observation")},
            since=now - timedelta(days=30),
            k=LEARNING_NEIGHBOR_CAP,
        )
        for n in neighbors:
            if n.similarity < LEARNING_SIMILARITY_MIN:
                continue
            if n.context["target"] == regret.context["target"]:
                continue
            existing = repo.find_learning_candidate(
                self_id=self_id,
                failed=regret.context["target"],
                succeeded=n.context["target"],
                within=LEARNING_COALESCE_WINDOW,
            )
            if existing:
                repo.increment_learning_candidate(existing.id)
                if existing.hits + 1 >= LEARNING_PROMOTION_FLOOR and not existing.promoted_lesson_id:
                    _promote(repo, self_id, existing)
            else:
                repo.insert_learning_candidate(
                    self_id=self_id, regret_memory_id=regret.id,
                    succeeded_memory_id=n.memory_id,
                    failed_specialist=regret.context["target"],
                    succeeded_specialist=n.context["target"],
                    similarity=n.similarity,
                )
                created += 1
            break
    return created
```

## Open questions

- **Q63.1.** Promotion floor at 3 hits — first match is anecdotal; three is pattern. Tune once real traffic exists.
- **Q63.2.** `+0.1 × log(hits)` for activation weight: small but accumulates. At 10 hits, weight ≈ +0.1; at 100 hits, ≈ +0.2. Tunable.
- **Q63.3.** The detector reads from memory; if mirror-to-memory (spec 32) falters, the detector gets less signal. Dependency chain is tight — note for implementors.
- **Q63.4.** Coalescing by `(failed_specialist, succeeded_specialist)` ignores request-shape differences. A more granular version coalesces by `(failed, succeeded, request-cluster-id)` if we add request clustering. Deferred.
