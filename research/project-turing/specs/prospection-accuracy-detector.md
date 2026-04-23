# Spec 65 — Prospection-accuracy detector

*Consumes spec 60's prospective predictions, computes cumulative prediction error, and flags systematic miscalibration. Closes the `prospection` deferred item.*

**Depends on:** [detectors/README.md](./detectors/README.md), [prospective-simulation.md](./prospective-simulation.md), [memory-mirroring.md](./memory-mirroring.md), [tuning.md](./tuning.md).
**Depended on by:** —

---

## Current state

Spec 60 produces `prospective_predictions` rows carrying predicted vs. actual outcome summaries and a surprise delta. Nothing reads the aggregate. If the self is systematically wrong about its predictions (always too optimistic, always too pessimistic about a specific specialist), nobody notices.

## Target

A detector that:
1. Runs daily and computes rolling statistics over resolved predictions.
2. Emits aggregate metrics.
3. Writes LESSON memories when specific miscalibration patterns pass threshold.
4. Proposes tuner adjustments (spec 11) if a specialist's prediction error is systematic.

## Acceptance criteria

### Detector registration

- **AC-65.1.** `prospection_accuracy` detector registered at P40, runs every 24 hours. Test.

### Aggregate computation

- **AC-65.2.** For each `(self_id, specialist)` pair, compute over the last 30 days of resolved predictions:
  - `mean_surprise` — average `surprise_delta`.
  - `std_surprise` — standard deviation.
  - `n` — number of resolved predictions.
  - `mean_confidence` — average `predicted_confidence`.
  - `confidence_calibration_error` — `abs(mean_confidence - (1 - mean_surprise))`.
  Store in a materialized view / running table:
  ```sql
  CREATE TABLE prospection_accuracy_agg (
      self_id     TEXT NOT NULL,
      specialist  TEXT NOT NULL,
      n           INTEGER NOT NULL,
      mean_surprise REAL NOT NULL,
      std_surprise REAL NOT NULL,
      mean_confidence REAL NOT NULL,
      confidence_calibration_error REAL NOT NULL,
      computed_at TEXT NOT NULL,
      PRIMARY KEY (self_id, specialist, computed_at)
  );
  ```
  Test.
- **AC-65.3.** Each detector run writes a new row; older rows are retained but indexed so the latest is easy to find. Test.

### Threshold-based LESSON minting

- **AC-65.4.** For a pair with `n >= 10`:
  - If `mean_surprise > 0.4`: mint LESSON `"I'm frequently surprised by outcomes when I route to {specialist}; my expectations may be off."` Test.
  - If `confidence_calibration_error > 0.3`: mint LESSON `"My confidence doesn't match reality for {specialist}."` Specifying direction:
    - `mean_confidence > 1 - mean_surprise`: "overconfident."
    - `mean_confidence < 1 - mean_surprise`: "underconfident."
  Test each.
- **AC-65.5.** LESSONs from this detector carry `intent_at_time = "prospection miscalibration"` and are consumed by spec 57's reflection for possible promotion to WISDOM. Test.
- **AC-65.6.** The detector mints at most `MAX_LESSONS_PER_RUN = 3` LESSONs per run to avoid spam. If more pairs qualify, only the highest `|calibration_error|` are emitted. Test.

### Tuner integration

- **AC-65.7.** For each pair with `n >= 20 AND mean_surprise > 0.35`, the detector proposes a tuner candidate (spec 11): reduce the weight of that specialist in the activation graph (via a `-0.1` rule-origin contributor, capped). Test.
- **AC-65.8.** Tuner proposals go through the standard spec 11 operator review pathway. Test.

### Observability

- **AC-65.9.** Prometheus gauges:
  - `turing_prospection_mean_surprise{specialist, self_id}`.
  - `turing_prospection_calibration_error{specialist, self_id}`.
  - `turing_prospection_n{specialist, self_id}`.
  Test.
- **AC-65.10.** `stronghold self inspect prospection [--specialist X]` prints the latest aggregate row per specialist. Test.

### Edge cases

- **AC-65.11.** `n < 10` — not enough data for confident LESSON minting; no LESSON, no tuner proposal, aggregate still recorded. Test.
- **AC-65.12.** A specialist with zero predictions (never chosen) — skipped entirely. Test.
- **AC-65.13.** Predictions older than 30 days fall out of the rolling window; the aggregate window is rolling. Test with fabricated older data.
- **AC-65.14.** Multiple selves (hypothetical) compute independently. Test with two selves.
- **AC-65.15.** A specialist retired from the roster still has its prediction aggregates computed until all resolved predictions fall out of the 30-day window. Test.

## Implementation

```python
# detectors/prospection_accuracy.py

MAX_LESSONS_PER_RUN: int = 3
SURPRISE_HIGH_THRESHOLD: float = 0.40
CALIBRATION_ERROR_THRESHOLD: float = 0.30
LESSON_MIN_N: int = 10
TUNER_MIN_N: int = 20


def run(repo, self_id: str, now: datetime) -> int:
    rows = repo.resolved_predictions_by_specialist(
        self_id=self_id, since=now - timedelta(days=30),
    )
    lessons_minted = 0
    tuner_proposals = []
    lesson_candidates = []

    for specialist, preds in rows.items():
        if len(preds) < LESSON_MIN_N:
            repo.insert_prospection_agg(
                self_id=self_id, specialist=specialist, n=len(preds),
                mean_surprise=_mean([p.surprise_delta for p in preds]) if preds else 0.0,
                std_surprise=_std([p.surprise_delta for p in preds]) if preds else 0.0,
                mean_confidence=_mean([p.predicted_confidence for p in preds]) if preds else 0.0,
                confidence_calibration_error=0.0,
                computed_at=now,
            )
            continue
        ms = _mean([p.surprise_delta for p in preds])
        mc = _mean([p.predicted_confidence for p in preds])
        cce = abs(mc - (1 - ms))
        repo.insert_prospection_agg(... n=len(preds), mean_surprise=ms,
                                     mean_confidence=mc,
                                     confidence_calibration_error=cce,
                                     computed_at=now)
        if ms > SURPRISE_HIGH_THRESHOLD:
            lesson_candidates.append((cce, specialist, "surprise"))
        if cce > CALIBRATION_ERROR_THRESHOLD:
            lesson_candidates.append((cce, specialist,
                                      "overconfident" if mc > 1 - ms else "underconfident"))
        if len(preds) >= TUNER_MIN_N and ms > 0.35:
            tuner_proposals.append((specialist, ms))

    lesson_candidates.sort(reverse=True)
    for cce, specialist, kind in lesson_candidates[:MAX_LESSONS_PER_RUN]:
        _mint_lesson(repo, self_id, specialist, kind, cce)
        lessons_minted += 1

    for specialist, ms in tuner_proposals:
        tuning.propose_specialist_weight_adjustment(
            self_id=self_id, specialist=specialist, delta=-0.1,
            rationale=f"prospection calibration ({ms:.2f} surprise)",
        )
    return lessons_minted
```

## Open questions

- **Q65.1.** Thresholds (0.4 surprise, 0.3 calibration error) are seeds. Real distributions will inform tuning.
- **Q65.2.** Confidence calibration uses a simple "confidence should equal 1 - surprise" heuristic. Proper calibration analysis (reliability diagrams) is richer; deferred as a second-pass refinement.
- **Q65.3.** The detector's tuner proposals and `learning_extraction`'s activation contributors could conflict. Operator review (spec 46) is the arbiter.
- **Q65.4.** Predictions from `chosen = 0` rows (unchosen alternatives) could be used for counterfactual calibration ("I would have been 90% confident if I'd chosen X; I don't know if I would have been right"). Deferred — the unchosen-counterfactual signal is noisy.
