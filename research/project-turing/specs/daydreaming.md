# Spec 7 — Daydreaming: Reactor-driven micro-idleness imagination

*The Conduit uses every scrap of idle compute and every unused free-tier token to generate I_IMAGINED hypotheticals from its durable memory. Integrated with the 1000Hz Reactor so idleness windows as short as a few ticks can be exploited. No free Gemini (or other free-tier) call is ever wasted.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md), [retrieval.md](./retrieval.md), [write-paths.md](./write-paths.md).
**Depended on by:** —

**Interacts with:** the 1000Hz Reactor (`main` component), the model router / free-tier quota tracker (new component).

---

## Current state

- `main` has the Reactor but no daydreaming consumer of it.
- `main` has a `QuotaTracker` for paid-tier routing; no explicit tracking of free-tier headroom per provider.
- No code writes `I_IMAGINED` memories today.

## Target

Daydreaming is an always-on Reactor trigger. When it fires (every tick, at 1000Hz), it evaluates in constant time whether it can run a micro-pass: is there idle compute, and is there unused free-tier quota about to expire? If yes, it launches a bounded asynchronous pass that writes `I_IMAGINED` memories at the HYPOTHESIS or OBSERVATION tier. The pass preempts itself the instant a real request arrives. Nothing the daydreamer produces can enter a durable tier.

The design intent: **free-tier tokens have an expiration clock, and an idle pipeline is wasted self-knowledge**. Daydreaming closes both gaps simultaneously.

## Acceptance criteria

### Source and tier locks (hard guarantees)

- **AC-7.1.** A daydream pass can only write memories with `source = SourceKind.I_IMAGINED`. Any attempt to write `I_DID` from the daydream code path raises. Enforced by a dedicated `DaydreamWriter` object whose write API physically cannot emit `I_DID`. Negative test exists.
- **AC-7.2.** A daydream pass cannot write into REGRET, ACCOMPLISHMENT, or WISDOM tiers, regardless of `source`. Negative test exists for each tier.
- **AC-7.3.** A daydream pass cannot mutate any existing memory. Read-only against the durable store; write-only against `I_IMAGINED` HYPOTHESIS/OBSERVATION. Test asserts this via repository mock.

### Reactor integration

- **AC-7.4.** Daydreaming registers a trigger on the Reactor. The trigger's per-tick evaluation is O(1) and completes in ≤ 1 ms on reference hardware (matching the Reactor's blocking-gate contract). Benchmark test.
- **AC-7.5.** If the Reactor detects an incoming request while a daydream pass is in flight, the pass is preempted within ≤ 1 tick (≤ 1 ms). In-flight LLM calls are cancelled; any memory not yet committed is discarded. Integration test with forced pre-emption.
- **AC-7.6.** A preempted pass does not commit partial output. Test asserts that interrupted passes produce zero writes.

### Free-tier token consumption

- **AC-7.7.** Daydreaming prefers free-tier models. The `DaydreamModelRouter` selects the highest-quality free-tier model with remaining quota; paid models are only selected if explicitly enabled. Default is free-only. Test over a fixture with mixed free/paid providers.
- **AC-7.8.** When a free-tier provider's daily quota window is nearing reset with unused headroom, daydreaming escalates its launch rate to consume the remaining headroom before the reset. Test asserts launch rate increases within the configured pre-reset window.
- **AC-7.9.** A free-tier quota tracker records consumption per provider per window and is consulted on every trigger evaluation. Test asserts the tracker updates after each pass.
- **AC-7.10.** If no free-tier provider has remaining quota, daydreaming does not fall back to paid models (by default) and skips the tick. Test.

### Bounds

- **AC-7.11.** `DAYDREAM_TOKENS_PER_PASS` (default 2,000) is honored. A pass that would exceed it halts at the boundary and keeps whatever it has written. Test.
- **AC-7.12.** `DAYDREAM_WRITES_PER_PASS` (default 5) is honored. Test.
- **AC-7.13.** A micro-pass — single retrieval, single LLM call, single write — completes in ≤ `DAYDREAM_MICRO_PASS_MAX_MS` (default 500 ms). Benchmark.

### Determinism and auditability

- **AC-7.14.** Re-running a daydream pass with the same seed and same memory snapshot produces identical I_IMAGINED entries (modulo timestamp). Deterministic test (pins LLM to a recorded response).
- **AC-7.15.** Every daydream session writes a single `tier = OBSERVATION`, `source = I_DID` marker memory recording: start/end timestamps, provider used, tokens consumed, write count, seed memory_id. The Conduit remembers that it daydreamed. Integration test.

### Promotion

- **AC-7.16.** An I_IMAGINED memory can be referenced from a later I_DID memory via `origin_episode_id` when a real event matches the daydream. The I_IMAGINED memory's source is *never* upgraded; it remains I_IMAGINED forever. Test asserts the upgrade path does not exist.

## Implementation

### 7.1 Reactor trigger

A new trigger type registered with the Reactor:

```python
class DaydreamTrigger:
    """Evaluates on every tick; launches a pass if conditions allow."""

    def evaluate(self, tick_state: TickState) -> TriggerDecision:
        # Fast path: < 1ms gate
        if tick_state.request_queue_depth > 0:
            return TriggerDecision.skip()
        if not self.free_quota_tracker.has_headroom():
            return TriggerDecision.skip()
        if not self.cooldown.elapsed():
            return TriggerDecision.skip()
        if self.in_flight_pass is not None:
            return TriggerDecision.skip()
        return TriggerDecision.fire(priority=IDLE)

    def fire(self) -> None:
        pass_handle = self.launcher.start_async(
            budget_tokens=self.budget_for_this_tick(),
            provider=self.free_quota_tracker.select_provider(),
        )
        self.in_flight_pass = pass_handle
```

Preemption is handled by the Reactor: when a request arrives, any in-flight pass registered as `IDLE` priority is cancelled.

### 7.2 Micro-pass vs full pass

The pass size adapts to the available window:

- **Micro-pass** (default when idle window is brief). Single seed retrieval → single LLM call → up to 1 write. ≤ 500 ms wall clock.
- **Full pass** (when idle window is sustained — e.g., nights or weekends). Up to `DAYDREAM_WRITES_PER_PASS` writes, richer retrieval, multi-step imagination.

The trigger picks the mode based on observed recent-idle patterns.

### 7.3 Free-tier quota tracker

A new component that tracks per-provider free-tier consumption:

```python
@dataclass
class FreeTierWindow:
    provider: str                # e.g. "gemini"
    model: str                   # e.g. "gemini-2.0-pro"
    window_start: datetime
    window_end: datetime          # when quota resets
    tokens_allowed: int
    tokens_used: int

    @property
    def headroom(self) -> int:
        return self.tokens_allowed - self.tokens_used

    @property
    def time_to_reset(self) -> timedelta:
        return self.window_end - datetime.now(UTC)
```

The tracker exposes:

- `has_headroom() -> bool` — any provider with `headroom > 0`.
- `select_provider() -> FreeTierWindow` — highest-quality provider with headroom, with bias toward those closest to reset.
- `record_usage(provider, tokens)` — called after every pass.

Pre-reset escalation: when `time_to_reset < ESCALATION_WINDOW` (default 30 min) and `headroom > 0`, the trigger's cooldown shrinks and the pass budget grows, so the remaining tokens get used.

### 7.4 DaydreamWriter

A dedicated writer class whose API cannot produce anything but I_IMAGINED. Enforced structurally:

```python
class DaydreamWriter:
    """The only writer permitted during a daydream pass."""

    def write_hypothesis(self, content: str, context: dict) -> None:
        self._repo.insert(EpisodicMemory(
            tier=MemoryTier.HYPOTHESIS,
            source=SourceKind.I_IMAGINED,   # hardcoded
            self_id=self._self_id,
            content=content,
            # ... other fields
        ))

    def write_observation(self, content: str, context: dict) -> None:
        self._repo.insert(EpisodicMemory(
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_IMAGINED,   # hardcoded
            # ...
        ))

    # No write_regret / write_accomplishment / write_wisdom methods exist.
```

The repository also double-checks: any insert from a `DaydreamWriter` context with `source != I_IMAGINED` or `tier in DURABLE_TIERS` raises before reaching the DB.

### 7.5 Pass sequence

A pass (micro or full):

1. **Seed.** Pick a seed memory from the durable store, weighted by recency of last access and a bias toward unresolved REGRETs (REGRETs with no superseding LESSON). Counter-weight toward ACCOMPLISHMENT seeds to avoid rumination (see Q7.1).
2. **Retrieve.** Related memories by `intent_at_time` family and topic cluster.
3. **Imagine.** Bounded LLM call. System prompt bakes in `source=I_IMAGINED` so the model knows it is simulating, and the prompt structure constrains output.
4. **Encode.** Write result as HYPOTHESIS (if testable) or OBSERVATION (if descriptive). `intent_at_time` records the seed; `origin_episode_id` points to a synthetic daydream-session marker.
5. **Mark.** Session marker memory written at pass end (I_DID, OBSERVATION) with provenance — see AC-7.15.

### 7.6 Configuration constants

```python
# Per-pass bounds
DAYDREAM_TOKENS_PER_PASS:      int = 2_000
DAYDREAM_WRITES_PER_PASS:      int = 5
DAYDREAM_MICRO_PASS_MAX_MS:    int = 500

# Trigger
DAYDREAM_COOLDOWN_MS:          int = 0     # 0 means "every tick if conditions allow"
DAYDREAM_QUEUE_THRESHOLD:      int = 0     # only when genuinely idle

# Free-tier escalation
ESCALATION_WINDOW:             timedelta = timedelta(minutes=30)
ESCALATION_COOLDOWN_MS:        int = 0
ESCALATION_TOKENS_PER_PASS:    int = 8_000

# Provider policy
DAYDREAM_ALLOW_PAID:           bool = False  # default: free-tier only
```

## Open questions

- **Q7.1.** Seed bias toward unresolved REGRETs risks rumination — the pipeline spending its idle compute re-chewing failures. Counter-weight toward ACCOMPLISHMENT seeds mitigates but doesn't resolve. What's the right ratio, and does it need to adapt to the current self-model?
- **Q7.2.** Pre-reset escalation is aggressive by design. If a provider's quota resets daily at midnight and the Conduit has 30 min of idle evening, the escalation window fires hard. Instrumentation should let operators see the spike; alarm threshold TBD.
- **Q7.3.** Daydream retrieval patterns could subtly bias what the live pipeline notices — exposure effects. Is there an instrumentation story that measures whether daydream topic-clusters are seeping into live routing behavior?
- **Q7.4.** The `DaydreamModelRouter` needs a quality signal for free-tier models. Most free tiers are capped to one or two model options; ranking across providers (Gemini vs. free OpenRouter vs. Groq free) requires a benchmark. Deferred to instrumentation spec.
- **Q7.5.** When all free-tier quotas are exhausted across all providers, daydreaming goes quiet. Should there be a "very low" paid-tier budget that keeps minimal daydreaming alive as a floor, or is quiet the right behavior? Default is quiet.
- **Q7.6.** Per-tick O(1) evaluation is the contract with the Reactor. The quota tracker needs to support O(1) `has_headroom()` and `select_provider()` — likely a cached best-provider pointer updated on record_usage.
- **Q7.7.** What happens if a free-tier provider silently degrades quality (rate-limits, returns less-capable variant)? The daydream writes are I_IMAGINED so the correctness cost is bounded, but the instrumentation should catch it.
