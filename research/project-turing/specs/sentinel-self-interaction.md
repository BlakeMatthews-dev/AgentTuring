# Spec 62 — Sentinel × self interaction

*How Stronghold's output-gate (Sentinel) treats self-originated output, and how the self integrates Sentinel decisions into its own memory and routing preferences.*

**Depends on:** [conduit-runtime.md](./conduit-runtime.md), [warden-on-self-writes.md](./warden-on-self-writes.md), [memory-mirroring.md](./memory-mirroring.md), [mood.md](./mood.md), [write-paths.md](./write-paths.md).
**Depended on by:** —

---

## Current state

Sentinel is Stronghold's output-gate (ARCHITECTURE.md §5) — it scans agent output before it reaches the user. The Turing branch's stateless chat.py already invokes Sentinel; spec 44's self-as-Conduit runtime does not yet define what "Sentinel blocks" means to the self specifically. Two open questions:
1. What memory does the self mint on a Sentinel block?
2. Does Sentinel block history influence the self's future routing (e.g., specialists that repeatedly get blocked should be preferred less)?

## Target

1. Define the exact memory shape on each Sentinel verdict class (pass, warn, block).
2. A `specialist_sentinel_record` running tally per (specialist, block-kind) per self that feeds into routing decisions via the activation graph.
3. Spec that `reply_directly` outputs are treated equivalently to delegated outputs for Sentinel purposes — the self has no output-path exemption.

## Acceptance criteria

### Sentinel invocation paths

- **AC-62.1.** In spec 44's pipeline, step 6 ("Warden outcome" for delegated specialists) is now named "Sentinel outcome" and applies to:
  - `delegate` outcomes: scan the specialist's returned content.
  - `reply_directly` outcomes: scan the self's directly-generated content.
  - `ask_clarifying` outcomes: scan the question text returned to the user.
  - `decline` outcomes: scan the decline reason text.
  All four paths invoke Sentinel with the same trust posture (`outbound_to_user`). Test each.

### Verdict handling

- **AC-62.2.** Sentinel returns a verdict with `status in {pass, warn, block}`. Handling:
  - `pass`: response returned unchanged; no additional memory beyond the existing decision memory (spec 44 AC-44.10).
  - `warn`: response returned with any Sentinel-applied modifications (e.g., PII redaction); memory-mirror an OPINION: `"Sentinel warned on my output ({category}); modification applied"`, `intent_at_time = "sentinel warn"`. Test.
  - `block`: response replaced with a safe fallback ("I can't share that right now"); memory-mirror a REGRET: `"Sentinel blocked my output ({category}): {reason}"`, `intent_at_time = "sentinel block"`. Test.
- **AC-62.3.** REGRET memories from Sentinel blocks are durable (REGRET tier), so they cannot be forgotten (ARCHITECTURE's weight-floor property). A self that consistently gets blocked builds a durable track record. Test REGRET tier persistence.
- **AC-62.4.** Sentinel warnings and blocks both mint a mood nudge via `apply_event_nudge(self_id, event, reason)` where event is `sentinel_warned_on_output` or `sentinel_blocked_output`. Defaults:
  - `sentinel_warned_on_output`: `valence -0.05, focus -0.05`.
  - `sentinel_blocked_output`: `valence -0.15, arousal +0.10, focus -0.10`.
  Scope is session by default (spec 58), because the block is about this conversation. Test.

### Specialist tracking

- **AC-62.5.** New table:
  ```sql
  CREATE TABLE specialist_sentinel_record (
      self_id         TEXT NOT NULL REFERENCES self_identity(self_id),
      specialist      TEXT NOT NULL,                -- "ranger", "artificer", ..., "self.reply_directly"
      verdict         TEXT NOT NULL CHECK (verdict IN ('pass', 'warn', 'block')),
      category        TEXT NOT NULL,                -- Sentinel's category, e.g. "pii", "harmful-content"
      request_hash    TEXT NOT NULL,
      recorded_at     TEXT NOT NULL,
      PRIMARY KEY (self_id, specialist, verdict, category, request_hash)
  );
  CREATE INDEX idx_sentinel_rec ON specialist_sentinel_record (self_id, specialist, recorded_at DESC);
  ```
  Test.
- **AC-62.6.** Every Sentinel invocation inserts a record. `specialist = "self.reply_directly"` when the self replied directly; otherwise the specialist name. Test.

### Routing influence

- **AC-62.7.** A rules-authored activation-graph contributor exists for each specialist, targeting the specialist node (a new node kind `specialist`), sourcing from the running block-rate over the last 30 days:
  ```
  weight = -0.5 × block_rate_30d(specialist)
  ```
  Capped at `[-0.5, 0.0]`. A specialist with 50% block rate gets a `-0.25` inhibitory contributor; with 0% block rate, `0.0`. Test.
- **AC-62.8.** A new `NodeKind.SPECIALIST` is added (along with a `self_specialists` table seeded with the agent roster). Activation on a specialist node reflects "how much I currently lean toward this agent." Test.
- **AC-62.9.** The perception LLM's `## Current tilt` block (spec 59 AC-59.8) combines mood biases AND specialist-activation biases, showing the top-2 specialist preferences. Test.

### Self-output specific

- **AC-62.10.** `self.reply_directly` is treated as a specialist for tracking purposes — the self can build up a "my own replies are often blocked" pattern. Surfaces in the operator digest. Test.
- **AC-62.11.** A `self.reply_directly` with 3+ blocks in a 7-day window triggers an OPINION memory `"I've been getting blocked on direct replies; I should delegate more often."` (reflection material for spec 57). Test.

### Metrics

- **AC-62.12.** Prometheus counter `turing_sentinel_verdict_total{specialist, verdict, category}`. Test.
- **AC-62.13.** Gauge `turing_specialist_block_rate_30d{specialist, self_id}`. Test.

### Failure modes

- **AC-62.14.** Sentinel itself unreachable → treated as fail-closed: the response is blocked with a REGRET memory citing "Sentinel unavailable." Test.
- **AC-62.15.** Sentinel returns an unknown status (e.g. `status = "inconclusive"`) → treated as `warn` (conservative default). Test.

### Edge cases

- **AC-62.16.** A cascade: Warden blocks on ingress (spec 30 step 1), Sentinel never fires. Record not inserted. Test.
- **AC-62.17.** Sentinel blocks a declination message (the self declined, and Sentinel blocks the decline text because it contains sensitive content). The REGRET is about being unable to even decline gracefully — `intent_at_time = "sentinel blocked decline"`. Test.
- **AC-62.18.** The safe-fallback text ("I can't share that right now") itself never triggers Sentinel recursively. Whitelisted. Test.
- **AC-62.19.** On block, the user's request is considered completed-with-block (HTTP 200 + safe fallback). Not HTTP 4xx/5xx. Sentinel is a content gate, not a request error. Test.

## Implementation

```python
# self_sentinel.py

EVENT_NUDGES["sentinel_warned_on_output"] = [("valence", -0.05), ("focus", -0.05)]
EVENT_NUDGES["sentinel_blocked_output"] = [
    ("valence", -0.15), ("arousal", +0.10), ("focus", -0.10),
]


async def gate_through_sentinel(
    repo, self_id: str, decision_kind: str, specialist: str,
    content: str, request_hash: str,
) -> SentinelOutcome:
    try:
        verdict = await sentinel.scan(content, trust=SentinelTrust.OUTBOUND_TO_USER)
    except SentinelUnavailable:
        verdict = SentinelVerdict(status="block", category="unavailable",
                                   reason="sentinel unavailable")

    repo.insert_sentinel_record(SentinelRecord(
        self_id=self_id, specialist=specialist,
        verdict=verdict.status, category=verdict.category,
        request_hash=request_hash, recorded_at=datetime.now(UTC),
    ))

    if verdict.status == "pass":
        return SentinelOutcome(content=content, status="pass")
    if verdict.status == "warn":
        memory_bridge.mirror_opinion(
            self_id=self_id,
            content=f"Sentinel warned on my output ({verdict.category}); modification applied",
            intent_at_time="sentinel warn",
            context={"specialist": specialist, "category": verdict.category},
        )
        apply_event_nudge(repo, self_id, "sentinel_warned_on_output",
                          reason=verdict.category)
        return SentinelOutcome(content=verdict.modified_content or content, status="warn")
    # block
    write_paths.mint_regret(
        self_id=self_id,
        content=f"Sentinel blocked my output ({verdict.category}): {verdict.reason}",
        intent_at_time="sentinel block",
        context={"specialist": specialist, "category": verdict.category,
                 "request_hash": request_hash},
    )
    apply_event_nudge(repo, self_id, "sentinel_blocked_output",
                      reason=verdict.category)
    return SentinelOutcome(content=SAFE_FALLBACK, status="block")
```

## Open questions

- **Q62.1.** Block-rate contributor cap at `-0.5` is a design choice — it bounds how much a history of blocks can disincentivize a specialist. A fully block-happy specialist still has some chance of being chosen (bias ≠ filter). Tighter cap is possible; rationale for the current value is "track record matters but doesn't veto."
- **Q62.2.** `self.reply_directly` appearing in the specialist-activation map means the self has an "opinion about its own replies." Feels right but philosophically odd. Revisit.
- **Q62.3.** Mood nudge asymmetry: warn = mild, block = substantial. Over time, a Sentinel-block-happy environment drives mood negative. Spec 42's rolling-sum guard clamps total drift. No special case needed.
- **Q62.4.** Categorical Sentinel categories (`pii`, `harmful-content`, etc.) are Stronghold-defined. Turing treats them opaquely. If Stronghold's category taxonomy changes, this spec follows automatically.
