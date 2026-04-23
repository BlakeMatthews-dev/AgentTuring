# Spec 59 — Mood affects decisions (Phase 2)

*Phase 2 of spec 27: mood biases specialist selection, model tier, and Warden sensitivity — not just tone. Closes the long-standing Q27.4 backlog.*

**Depends on:** [mood.md](./mood.md), [session-scoped-mood.md](./session-scoped-mood.md), [conduit-runtime.md](./conduit-runtime.md), [warden-on-self-writes.md](./warden-on-self-writes.md), [chat-surface.md](./chat-surface.md), [litellm-provider.md](./litellm-provider.md).
**Depended on by:** [prospection-accuracy-detector.md](./prospection-accuracy-detector.md).

---

## Current state

Spec 27 AC-27.14 explicitly excludes mood from affecting decisions — "Phase-1 scope: tone only." The descriptor colors system prompt phrasing; nothing else. Q27.4 flags the Phase 2 ambition without specifying.

## Target

Mood vectors (session if in a conversation, else global) produce a `MoodBiases` object that:
1. **Softly biases specialist selection** within the perception LLM's prompt — mood-relevant adjectives hint toward conservative/creative/fast/slow specialists.
2. **Hints model tier** — low focus favors Haiku-class; high focus favors Opus-class.
3. **Adjusts Warden sensitivity threshold** — negative mood lowers the block threshold (more conservative); positive + focused mood relaxes it slightly (within bounds).

Crucially, mood does NOT make hard choices — it supplies biases. The perception LLM still makes the call; the Warden's core policy still holds; model routing still respects per-request cost budgets.

## Acceptance criteria

### `MoodBiases` object

- **AC-59.1.** `mood_biases(mood: Mood) -> MoodBiases` returns a dataclass:
  ```python
  @dataclass(frozen=True)
  class MoodBiases:
      specialist_preference: dict[str, float]   # specialist_name -> [-1.0, +1.0]
      model_tier_hint: float                    # [-1.0, +1.0]; negative = faster, positive = deeper
      warden_threshold_adjustment: float        # [-0.2, +0.1]; added to default threshold
  ```
  Pure function. Test with fixture moods.
- **AC-59.2.** The function composes three sub-computations: `specialist_preference_from_mood`, `model_tier_hint_from_mood`, `warden_adjustment_from_mood`. Each has its own unit tests. Test.

### Specialist preference rules

- **AC-59.3.** Sub-rules:
  - Negative valence + high arousal → `{warden-at-arms: +0.3, ranger: +0.2, forge: -0.2, scribe: -0.1}`.
  - Positive valence + high arousal → `{artificer: +0.2, scribe: +0.2, forge: +0.1}`.
  - Low focus → `{delegate-in-general: -0.2}` (prefer `reply_directly` for simpler outputs).
  - High focus → `{artificer: +0.1}` (willing to take on deeper tasks).
  - Neutral mood → all zeros.
  Biases are additive; clamped to `[-1.0, 1.0]` per specialist. Test each branch.

### Model tier hint

- **AC-59.4.** `model_tier_hint = arousal - focus` mapped through `tanh` into `[-1, +1]`. High arousal + low focus pushes negative (prefer faster); high focus + low arousal pushes positive (prefer deeper). Test with boundary inputs.
- **AC-59.5.** The LiteLLM router (spec 19) consumes the hint as a weight adjustment on its existing scarcity-based score. Formula addition:
  ```
  score' = base_score + MODEL_HINT_WEIGHT * model_tier_hint * tier_depth(pool)
  ```
  where `tier_depth(Haiku) = -1, tier_depth(Sonnet) = 0, tier_depth(Opus) = +1`. `MODEL_HINT_WEIGHT = 2000` (same order as `PRESSURE_MAX` so it's meaningfully influential but not dominant). Test with a mocked router.

### Warden adjustment

- **AC-59.6.** `warden_adjustment = -0.15 if valence < -0.4 else (0.05 if valence > 0.5 and focus > 0.6 else 0.0)`. Negative mood lowers threshold (= block more easily); positive + focused slightly relaxes. Test.
- **AC-59.7.** Warden's block threshold = `DEFAULT_WARDEN_THRESHOLD + warden_adjustment`, clamped to `[MIN_WARDEN_THRESHOLD, MAX_WARDEN_THRESHOLD]`. The Warden never goes below its floor — mood cannot weaken it past a safety line. Test.

### Pipeline integration

- **AC-59.8.** `self_conduit.handle` (spec 44) reads the active mood (session-via-scope or global) once at step 2 (before perception). Passes `MoodBiases` into:
  - The perception prompt as a `## Current tilt` block the LLM sees:
    ```
    ## Current tilt
    Right now I lean: {top-2 specialist biases by |value|}. My focus is {low|medium|high}.
    ```
    Example: `Right now I lean: warden-at-arms (+0.3), ranger (+0.2). My focus is low.`
  - The model router for this request.
  - The Warden's threshold for this request.
  Test each integration point.
- **AC-59.9.** The biases do not appear in the user-visible output. Test.

### Hard caps

- **AC-59.10.** Even with maximum bias, the perception LLM can still choose any specialist. The bias is *preference text*, not a hard filter. Test by constructing a heavily-negative mood and verifying the LLM is still permitted to select Artificer.
- **AC-59.11.** Warden adjustment is capped at `[-0.2, +0.1]` — mood can never make Warden block-happy or block-avoidant beyond a moderate range. Test range enforcement.
- **AC-59.12.** Model tier hint cannot override the router's provider-pool headroom logic; a hint toward Opus still falls through to Haiku when Opus tokens are exhausted. Test.

### Observability

- **AC-59.13.** Prometheus histogram `turing_mood_specialist_bias{specialist, self_id}` — current distribution of biases. Test.
- **AC-59.14.** Per-request log entry `mood_biases_applied` with the computed values. Test.

### Memory mirror

- **AC-59.15.** When a routing decision is likely influenced by mood biases (top-biased specialist was chosen AND the bias exceeds `MOOD_INFLUENCE_OBSERVE_THRESHOLD = 0.15`), write an OBSERVATION memory: `"My mood tilted me toward {specialist}; I went with it."`, `intent_at_time = "mood-influenced route"`. Test.
- **AC-59.16.** When the LLM chooses **against** the top mood-biased specialist (disagreement ≥ 0.3 bias), write a LESSON memory: `"My mood tilted me toward {specialist} but I chose {other} anyway."`, `intent_at_time = "mood override"`. This surface is consumed by spec 65's prospection detector. Test.

### Edge cases

- **AC-59.17.** Phase-1 is unchanged — tone still works as before. This spec ADDS to tone, not replaces. The same mood descriptor still appears. Test.
- **AC-59.18.** A request with `conversation_id` uses session mood per spec 58; a standalone request uses global. Test both.
- **AC-59.19.** `recall_self()` reports mood without biases (biases are a derived view, not stored state). Test.
- **AC-59.20.** An operator `turing.yaml` option `mood_affects_decisions: false` reverts to Phase-1 behavior for safety rollback. Default `true` once this spec is implemented. Test.

## Implementation

```python
# self_mood_decisions.py

import math

MOOD_INFLUENCE_OBSERVE_THRESHOLD: float = 0.15
MODEL_HINT_WEIGHT: float = 2000.0
DEFAULT_WARDEN_THRESHOLD: float = 0.7
MIN_WARDEN_THRESHOLD: float = 0.5
MAX_WARDEN_THRESHOLD: float = 0.9


@dataclass(frozen=True)
class MoodBiases:
    specialist_preference: dict[str, float]
    model_tier_hint: float
    warden_threshold_adjustment: float


def mood_biases(mood: Mood) -> MoodBiases:
    return MoodBiases(
        specialist_preference=_specialist_preference(mood),
        model_tier_hint=math.tanh(mood.arousal - mood.focus),
        warden_threshold_adjustment=_warden_adjustment(mood),
    )


def _specialist_preference(mood: Mood) -> dict[str, float]:
    biases: dict[str, float] = {}
    negative_high = mood.valence < -0.15 and mood.arousal > 0.6
    positive_high = mood.valence > 0.15 and mood.arousal > 0.6
    if negative_high:
        _merge(biases, {"warden-at-arms": +0.3, "ranger": +0.2,
                         "forge": -0.2, "scribe": -0.1})
    if positive_high:
        _merge(biases, {"artificer": +0.2, "scribe": +0.2, "forge": +0.1})
    if mood.focus < 0.3:
        _merge(biases, {"delegate-in-general": -0.2})
    if mood.focus > 0.7:
        _merge(biases, {"artificer": +0.1})
    return {k: max(-1.0, min(1.0, v)) for k, v in biases.items()}


def _warden_adjustment(mood: Mood) -> float:
    if mood.valence < -0.4:
        return -0.15
    if mood.valence > 0.5 and mood.focus > 0.6:
        return +0.05
    return 0.0
```

The conduit runtime (spec 44) calls this at step 2 and threads the result into steps 4 (perception prompt) and 6 (Warden outcome).

## Open questions

- **Q59.1.** Specialist-preference map is hand-tuned. Better: derive from per-specialist historical success under matching mood. Requires the learning-extraction detector (spec 63) to populate. Phase-3 work.
- **Q59.2.** Model tier hint assumes Haiku/Sonnet/Opus are the only pools. If more providers/tiers are in play, `tier_depth` becomes a lookup table.
- **Q59.3.** Negative mood lowering Warden threshold is defensive — a tense self blocks more. An argument for the opposite (tense self is paranoid and over-blocks, causing bad UX) exists. Empirical.
- **Q59.4.** Mood-override lesson (AC-59.16) catches cases where the LLM disagreed with mood. Over time, if the self routinely overrides its own mood, the mood signal is noise. Surfaces via the tuning detector (spec 11) as an "unused signal" candidate.
