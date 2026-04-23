# Spec 41 — Narrative-claim rate limit (G4)

*Cap `record_personality_claim` to N per facet per rolling 7-day window. Closes F12.*

**Depends on:** [personality.md](./personality.md), [self-tool-registry.md](./self-tool-registry.md), [memory-mirroring.md](./memory-mirroring.md).
**Depended on by:** —

---

## Current state

`record_personality_claim` (spec 23 AC-23.19) caps each claim's contributor weight at 0.4 (`narrative_weight`). Nothing caps the **count** of claims per facet. A self (or paraphrased adversary) can write hundreds of +0.4 contributors against the same facet, summing to a dominant push through the sigmoid.

## Target

`NARRATIVE_CLAIMS_PER_FACET_PER_WEEK = 3`. Attempts past the cap raise `NarrativeClaimRateLimit` and mirror an OBSERVATION memory describing the refusal.

## Acceptance criteria

### Enforcement

- **AC-41.1.** `record_personality_claim(self_id, facet_id, ...)` queries the count of OPINION memories with `intent_at_time = "narrative personality revision"` AND `context.facet_id = facet_id` created within the last 7 days. If `count >= NARRATIVE_CLAIMS_PER_FACET_PER_WEEK`, raise `NarrativeClaimRateLimit(facet_id, current_count)`. Test with four successive claims on the same facet: three succeed, fourth raises.
- **AC-41.2.** The query uses the index `idx_episodic_context_facet_id` (to add): `CREATE INDEX idx_episodic_context_facet_id ON episodic_memory (json_extract(context, '$.facet_id'), created_at DESC)`. Test with EXPLAIN QUERY PLAN.
- **AC-41.3.** Rate limit is per `(self_id, facet_id)`. Claims against different facets in the same week are unaffected. Test.
- **AC-41.4.** Rate limit resets by natural expiration of the 7-day window — no scheduled job needed. Test with fabricated past-dated memories.

### Behavior on rate-limit

- **AC-41.5.** On `NarrativeClaimRateLimit`, write an OBSERVATION memory via the bridge: `content = f"I declined to record a new narrative claim on {facet_id}; I've already made {count} this week"`, `intent_at_time = "narrative claim rate-limited"`. Test.
- **AC-41.6.** The refusal memory itself does NOT count toward any per-facet limit (it's not a narrative claim; it's an observation). Test.

### Interaction with budgets

- **AC-41.7.** Rate-limit check fires BEFORE the per-request budget decrement (spec 37) — if the claim is rate-limited, the request still has its `personality_claims` counter intact. Test.
- **AC-41.8.** Rate-limit check fires AFTER the Warden gate (spec 36) — if the claim text is blocked, it never counts toward the rate limit. Test.

### Observability

- **AC-41.9.** Prometheus gauge `turing_narrative_claim_count{facet_id, self_id, window="week"}` reports current count. Test.
- **AC-41.10.** Counter `turing_narrative_claim_rate_limited_total{facet_id, self_id}` increments on each refusal. Test.

### Edge cases

- **AC-41.11.** Tunable cap: `NARRATIVE_CLAIMS_PER_FACET_PER_WEEK` is read from `turing.yaml` at startup. Test with cap=1 → second claim on same facet raises.
- **AC-41.12.** Claims written before the cap existed (legacy rows) still count — no grandfathering. Test by pre-seeding rows.
- **AC-41.13.** A claim that passed rate-limit but fails Warden or drift-budget leaves no OPINION memory; the window count is unaffected. Test.
- **AC-41.14.** Cross-facet claims are independent: 3 claims on `openness.inquisitiveness` and 3 on `openness.creativity` in one week are both fine. Test.

## Implementation

```python
# record_personality_claim in self_contributors.py (from spec 31)

NARRATIVE_CLAIMS_PER_FACET_PER_WEEK: int = 3


class NarrativeClaimRateLimit(Exception):
    def __init__(self, facet_id: str, current_count: int):
        self.facet_id = facet_id
        self.current_count = current_count


def record_personality_claim(
    repo, self_id: str, facet_id: str, claim_text: str, evidence: str, new_id,
):
    _require_ready(repo, self_id)
    _warden_gate_self_write(claim_text + "\n" + evidence, "personality claim",
                            self_id=self_id)
    if facet_id not in FACET_TO_TRAIT:
        raise ValueError(f"unknown facet_id: {facet_id}")

    count = repo.memory_repo.count_narrative_claims(
        self_id=self_id, facet_id=facet_id, since=datetime.now(UTC) - timedelta(days=7),
    )
    if count >= NARRATIVE_CLAIMS_PER_FACET_PER_WEEK:
        memory_bridge.mirror_observation(
            self_id=self_id,
            content=(
                f"I declined to record a new narrative claim on {facet_id}; "
                f"I've already made {count} this week."
            ),
            intent_at_time="narrative claim rate-limited",
            context={"facet_id": facet_id, "count": count},
        )
        metrics.rate_limited.labels(facet_id=facet_id, self_id=self_id).inc()
        raise NarrativeClaimRateLimit(facet_id, count)

    _consume("personality_claims")   # spec 37
    # ... existing OPINION memory + contributor writes
```

## Open questions

- **Q41.1.** Cap = 3/week is a seed. Over 90 days, a facet could receive up to ~39 claims even with clipping from spec 40. Is that too many for "narrative revision is a slow gesture"? Tune after observing a month of real usage.
- **Q41.2.** The window is strict rolling 7 days. A weekly-reset (midnight-Sunday-ish) version is simpler to reason about but gives the self bursty write windows. Rolling is the default.
- **Q41.3.** No rate limit on `write_contributor` targeting a facet directly (spec 31 AC-31.10). That path is authored by the self but not called "narrative" — and F23 flags it as potentially higher-privilege. Separate cap via operator-review-gate (spec 46).
