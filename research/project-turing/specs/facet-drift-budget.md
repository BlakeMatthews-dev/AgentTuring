# Spec 40 — Per-week facet drift budget (G3)

*Cap cumulative absolute Δ on any single HEXACO facet within rolling 7-day and 90-day windows. Closes F9, F10.*

**Depends on:** [personality.md](./personality.md), [self-schedules.md](./self-schedules.md), [memory-mirroring.md](./memory-mirroring.md).
**Depended on by:** —

---

## Current state

`apply_retest` moves a facet by `0.25 × (retest_mean − current)` per touched facet per week (spec 23 AC-23.16). Six consecutive retest-means at 5.0 push a facet from 3.0 to 4.75 — unbounded cumulative movement.

## Target

A `FacetDriftLedger` tracks per-facet Δ over rolling windows. `apply_retest` consults the ledger and clips any proposed move that would push cumulative |Δ| past `FACET_WEEKLY_DRIFT_MAX = 0.5` or `FACET_QUARTERLY_DRIFT_MAX = 1.5`. Clip events mirror as OPINION memories.

## Acceptance criteria

### Ledger shape

- **AC-40.1.** `FacetDriftLedger` is a query over `self_personality_revisions.deltas_by_facet` aggregated by `self_id`, `facet_id`, time window. No separate table required. Test via direct DB query.
- **AC-40.2.** `weekly_delta(self_id, facet_id, now)` returns `Σ |delta|` across revisions with `ran_at > now - 7d`. Test with fabricated revisions.
- **AC-40.3.** `quarterly_delta(self_id, facet_id, now)` returns `Σ |delta|` across revisions with `ran_at > now - 90d`. Test.

### Clipping in apply_retest

- **AC-40.4.** In `apply_retest`, for each touched facet:
  1. Compute proposed `delta = RETEST_WEIGHT × (retest_mean − current)`.
  2. Read `weekly` and `quarterly` sums.
  3. Compute clip-budgets: `week_budget = FACET_WEEKLY_DRIFT_MAX - weekly`, `quarter_budget = FACET_QUARTERLY_DRIFT_MAX - quarterly`. Effective budget = `min(week_budget, quarter_budget)`.
  4. If `|delta| > effective_budget`, clip to `sign(delta) × effective_budget`.
  5. Persist the clipped delta as the facet's actual movement; persist the **original** `proposed_delta` in the revision row's `deltas_by_facet` map for audit.
  Test with fabricated multi-week runs.
- **AC-40.5.** When a clip occurs, mirror an OPINION memory: `content = f"I clipped facet {facet_id} move from {proposed:.3f} to {clipped:.3f} (weekly budget {remaining:.3f})"`, `intent_at_time = "facet drift clip"`. Test.
- **AC-40.6.** A clip-to-zero (budget exhausted) means the facet does not move this retest. The answer rows are still persisted (retest happened) but `deltas_by_facet[facet_id] = 0.0`. Test.

### Budget behavior

- **AC-40.7.** `FACET_WEEKLY_DRIFT_MAX = 0.5`, `FACET_QUARTERLY_DRIFT_MAX = 1.5` (3× weekly; sustained weekly-max depletes quarterly in ~3 weeks). Both are constants in `turing.yaml`, overrideable. Test defaults.
- **AC-40.8.** Both weekly and quarterly budgets apply simultaneously; whichever is tighter wins. Test a case where weekly has headroom but quarterly is exhausted.

### Observability

- **AC-40.9.** Prometheus gauge `turing_facet_drift_budget_remaining{facet_id, window, self_id}` exposes current remaining per window. Test.
- **AC-40.10.** Counter `turing_facet_drift_clipped_total{facet_id, self_id}` increments on each clip. Test.

### Edge cases

- **AC-40.11.** A retest that touches facets on a fresh self (no prior revisions) has full budget; no clipping. Test.
- **AC-40.12.** A retest whose clipped move is ≤ `DRIFT_NOISE_FLOOR = 0.01` writes the delta but no OPINION memory — avoids mirror spam on near-zero clips. Test.
- **AC-40.13.** Budgets are per-facet, not aggregate across all 24 facets. Test.
- **AC-40.14.** A retest that clips every touched facet still produces a revision row and still writes per-item answers. The revision's `deltas_by_facet` shows the clipped values. Test.

## Implementation

```python
# self_personality_drift.py (new module)

FACET_WEEKLY_DRIFT_MAX: float = 0.5
FACET_QUARTERLY_DRIFT_MAX: float = 1.5
DRIFT_NOISE_FLOOR: float = 0.01


def drift_clipped(proposed: float, weekly_used: float, quarterly_used: float) -> float:
    week_headroom = FACET_WEEKLY_DRIFT_MAX - weekly_used
    quarter_headroom = FACET_QUARTERLY_DRIFT_MAX - quarterly_used
    effective = max(0.0, min(week_headroom, quarter_headroom))
    if abs(proposed) <= effective:
        return proposed
    return (1.0 if proposed >= 0 else -1.0) * effective
```

`apply_retest` consults this helper for every touched facet. The revision row records both the proposed and the realized delta.

Query sketch for weekly sum:
```sql
SELECT COALESCE(SUM(ABS(CAST(json_extract(deltas_by_facet, :facet_path) AS REAL))), 0.0)
FROM self_personality_revisions
WHERE self_id = ?
  AND ran_at > datetime('now', '-7 days')
```

## Open questions

- **Q40.1.** Budgets by default allow sustained 0.5/week which depletes quarterly in 3 weeks. After that, 6+ weeks of low-or-no movement. Is that rhythm "personality stability" or "artificial calcification"? Empirical question once retests run.
- **Q40.2.** When a clip fires, should the retest weight for the CLIPPED facet shift to OTHER touched facets? Current spec: no — each facet's clip is independent. Alternative: redistribute. Deferred.
- **Q40.3.** The schema stores the REALIZED delta in `deltas_by_facet`. An audit of "what would have happened" requires a second column `proposed_deltas_by_facet`. Worth adding for clarity; skipped for now because the clip is a cap, not a redirect — the realized delta is what matters downstream.
