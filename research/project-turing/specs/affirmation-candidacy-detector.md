# Spec 64 — Affirmation-candidacy detector

*A detector that identifies consistently-succeeding routing patterns and proposes AFFIRMATION commitments. Closes the `affirmation_candidacy` deferred item.*

**Depends on:** [detectors/README.md](./detectors/README.md), [learning-extraction-detector.md](./learning-extraction-detector.md), [write-paths.md](./write-paths.md), [memory-mirroring.md](./memory-mirroring.md), [operator-review-gate.md](./operator-review-gate.md).
**Depended on by:** —

---

## Current state

AFFIRMATIONs in the 7-tier memory model are durable commitments. They're currently minted by specific write-path events (todo completion, WISDOM consolidation, etc.). No detector proposes AFFIRMATIONs from pattern — "I keep succeeding at X; I commit to always doing X."

## Target

A detector that runs alongside `learning_extraction` (spec 63) and looks for `(request-shape, specialist, outcome=success)` triples repeating N times. Proposes an AFFIRMATION: `"I commit to routing {request-shape} requests to {specialist}."` AFFIRMATIONs are durable-tier, so the commitment is structurally unforgettable. Promotion requires operator ACK via the review gate (spec 46) — unlike learning LESSONs which auto-promote, AFFIRMATIONs are too high-commitment for autopromotion.

## Acceptance criteria

### Detector registration

- **AC-64.1.** Register `affirmation_candidacy` detector. Runs on a P40 schedule every 12 hours. Test.
- **AC-64.2.** Budget: sample `AFFIRMATION_CANDIDATE_LOOKBACK = 100` most recent routing-decision memories in the last 30 days.

### Pattern detection

- **AC-64.3.** For each `(request-shape-cluster, specialist)` pair in the sample, compute `success_rate = count(affirmation or clean observation outcomes) / count(total)`. Request-shape-clustering uses request-embedding K-means or equivalent (spec assumes embedding infrastructure). Test.
- **AC-64.4.** A pair qualifies for a candidate if:
  - `hits >= AFFIRMATION_PROMOTION_FLOOR = 7` (the routing happened 7+ times).
  - `success_rate >= AFFIRMATION_SUCCESS_FLOOR = 0.85` (≥85% success).
  - No AFFIRMATION already exists for this pair.
  Test.

### Candidacy

- **AC-64.5.** Candidates enter a queue:
  ```sql
  CREATE TABLE affirmation_candidates (
      id              TEXT PRIMARY KEY,
      self_id         TEXT NOT NULL,
      request_shape   TEXT NOT NULL,    -- cluster id or canonical shape
      specialist      TEXT NOT NULL,
      hits            INTEGER NOT NULL,
      success_rate    REAL NOT NULL,
      proposed_at     TEXT NOT NULL,
      reviewed_at     TEXT,
      review_decision TEXT CHECK (review_decision IN ('approve', 'reject')),
      promoted_memory_id TEXT
  );
  ```
  Test.
- **AC-64.6.** Candidates are NOT auto-promoted — they enter the weekly operator digest (spec 46). Operator ACK minting path: `stronghold self ack-affirmation <candidate_id> --approve` mints the AFFIRMATION memory and retires the candidate. Test.

### Operator digest entry

- **AC-64.7.** Digest lists candidates with:
  - A sample regurgitated request for the cluster.
  - The specialist.
  - Hits and success rate.
  - Operator-readable proposed text: `"I commit to routing {shape} to {specialist}."`
  Test.
- **AC-64.8.** Rejected candidates are marked `review_decision = reject`; re-proposed after `AFFIRMATION_REJECTION_COOLDOWN = 30 days` if the pattern persists. Rejected-twice produces an OPINION memory `"I keep proposing this commitment; operator keeps declining."` for the self's own reflection. Test.

### AFFIRMATION shape on approval

- **AC-64.9.** Approved AFFIRMATION:
  ```
  content = f"I commit to routing requests like '{shape summary}' to {specialist}. Observed success rate: {rate:.0%} over {hits} instances."
  intent_at_time = "affirmation from pattern"
  tier = AFFIRMATION
  source = I_DID
  context = {shape_cluster_id, specialist, hits, success_rate, candidate_id}
  ```
  Test.
- **AC-64.10.** Approved AFFIRMATION writes a contributor edge to the specialist node (spec 62 AC-62.8) with `weight = +0.3`, `origin = "rule"`, `rationale = "affirmation commitment"`. Unlike learning's `-0.05×log(hits)` weight, AFFIRMATION's weight is static and substantial. Test.

### Revocation

- **AC-64.11.** An AFFIRMATION can be later revoked via `stronghold self revoke-affirmation <memory_id> --reason TEXT`. Revocation mints a REGRET: `"I revoked my commitment to {specialist} for {shape}: {reason}"` and retracts the contributor. Revocation is operator-authored. Test.
- **AC-64.12.** Revoked AFFIRMATIONs do NOT mean the pattern is re-proposed — the detector re-examines and may propose a fresh candidate only if the underlying pattern holds. Test.

### Observability

- **AC-64.13.** Prometheus counters: `turing_affirmation_candidates_created_total`, `turing_affirmation_candidates_approved_total`, `turing_affirmation_candidates_rejected_total`. Test.

### Edge cases

- **AC-64.14.** Request-shape clustering with sparse data (few memories) yields too-small clusters. A cluster of size < 3 is ignored (not useful evidence of a pattern). Test.
- **AC-64.15.** AFFIRMATION memories are immutable (spec 22-ish invariant). Revocation does not delete them — it writes a superseding REGRET. Test.
- **AC-64.16.** Spec 46's contributor-review-gate does NOT apply to AFFIRMATION contributors here — the AFFIRMATION ITSELF was operator-approved, so its contributor is implicitly approved. Test.
- **AC-64.17.** Concurrent approval of the same candidate is serialized by PK; second call returns the existing promoted memory id. Test.

## Implementation

```python
# detectors/affirmation_candidacy.py

AFFIRMATION_PROMOTION_FLOOR: int = 7
AFFIRMATION_SUCCESS_FLOOR: float = 0.85
AFFIRMATION_REJECTION_COOLDOWN: timedelta = timedelta(days=30)


def run(repo, self_id: str, now: datetime) -> int:
    routings = repo.recent_routing_decisions(self_id, limit=100,
                                              since=now - timedelta(days=30))
    clusters = _cluster_by_request_embedding(routings)
    created = 0
    for cluster in clusters:
        for specialist in _unique_specialists(cluster):
            rows = [r for r in cluster if r.context["target"] == specialist]
            if len(rows) < AFFIRMATION_PROMOTION_FLOOR:
                continue
            successes = sum(1 for r in rows if _outcome_is_success(repo, r))
            rate = successes / len(rows)
            if rate < AFFIRMATION_SUCCESS_FLOOR:
                continue
            if _existing_affirmation(repo, self_id, cluster.id, specialist):
                continue
            repo.insert_affirmation_candidate(AffirmationCandidate(
                self_id=self_id, request_shape=cluster.id,
                specialist=specialist, hits=len(rows),
                success_rate=rate, proposed_at=now,
            ))
            created += 1
    return created
```

## Open questions

- **Q64.1.** Request-shape clustering is assumed but not specced in detail. Cluster stability matters — a cluster that splits between runs would break candidate coalescing. Defer clustering spec until the detector is implemented with a fixed seed-clustering approach.
- **Q64.2.** 85% success floor / 7 hits threshold are seeds. Higher floor catches only strong patterns; lower floor surfaces candidates earlier. Tunable.
- **Q64.3.** AFFIRMATION contributors at +0.3 are 3× the learning-LESSON default. Rationale: an operator-approved commitment is load-bearing; learning is advisory. Consider asymmetry when these stack.
- **Q64.4.** Revocation via superseding REGRET matches ARCHITECTURE's immutability rule. Operators who want clean removal would need to `--retire-self` — out of scope.
