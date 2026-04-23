# Spec 32 — Memory mirroring for self-model writes

*Every self-model write has a specced "and mirror as an OBSERVATION/AFFIRMATION/LESSON memory" clause. None of them currently fire. This spec wires them. Closes F38 (critical).*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [write-paths.md](./write-paths.md), [self-tool-registry.md](./self-tool-registry.md).
**Depended on by:** [warden-on-self-writes.md](./warden-on-self-writes.md), [operator-review-gate.md](./operator-review-gate.md), and every guardrail spec that consumes mirrored observations.

---

## Current state

Specs 23, 24, 25, 26, 27, 29 each name a memory mirror for specific self-model actions — e.g. spec 24 AC-24.8 ("writes an OBSERVATION-tier memory with the notes"), spec 27 AC-27.9 ("writes an OBSERVATION-tier memory"), spec 29 AC-29.17 ("writes a LESSON-tier episodic memory"). The sketch contains zero calls to any such mirror from self-model modules. Only `daydream.py` invokes a memory writer.

## Target

Introduce a `self_memory_bridge.py` that wraps the existing write-paths (`write_paths.py`) with self-model-shaped helpers. Every self-model write-site calls the appropriate helper in the same transaction. The mirror memory carries `context.self_id`, `context.request_hash` (when available), and the originating tool/event in `intent_at_time`.

## Acceptance criteria

### Bridge API

- **AC-32.1.** `self_memory_bridge.py` exposes `mirror_observation`, `mirror_opinion`, `mirror_affirmation`, `mirror_lesson`, `mirror_regret`. Each accepts `(self_id, content, intent_at_time, context=None)` and returns the created `memory_id`. Test.
- **AC-32.2.** `content` is truncated to `MIRROR_CONTENT_MAX = 1000` chars at the bridge boundary; `intent_at_time` is ≤ 120 chars. Over-max raises at the bridge, not silently truncated. Test.
- **AC-32.3.** `context` always includes `self_id` (redundant with the column, retained for downstream query convenience) and the current `request_hash` if available via a `contextvars.ContextVar` (spec 39 adds the forensic-tag pipe). Test.

### Write-site wiring

For each spec AC that calls for a memory mirror, the corresponding code path invokes the bridge in the same transaction. Exhaustive list:

- **AC-32.4.** Spec 23 AC-23.9 — bootstrap answers (200 of them) each write an OBSERVATION via `mirror_observation(intent_at_time="personality bootstrap")`.
- **AC-32.5.** Spec 23 AC-23.17 — retest answers (20/week) each write an OBSERVATION via `mirror_observation(intent_at_time="personality retest")`.
- **AC-32.6.** Spec 23 AC-23.19 — `record_personality_claim` writes an OPINION via `mirror_opinion(intent_at_time="narrative personality revision")`.
- **AC-32.7.** Spec 24 AC-24.8 — `note_engagement(hobby_id, notes)` writes an OBSERVATION via `mirror_observation(intent_at_time="engage hobby")`.
- **AC-32.8.** Spec 24 AC-24.10 — `practice_skill` writes an OBSERVATION via `mirror_observation(intent_at_time="practice skill")`.
- **AC-32.9.** Spec 25 AC-25.19 — `write_contributor(origin=self)` writes an OBSERVATION via `mirror_observation(intent_at_time="write contributor")`.
- **AC-32.10.** Spec 26 AC-26.12 — `complete_self_todo` writes an AFFIRMATION via `mirror_affirmation(intent_at_time="complete self todo")`; the AFFIRMATION's `memory_id` is then used as the source of the +0.3 reinforcement contributor (spec 26 AC-26.14) — removes the caller-supplied-memory-id workaround in the current sketch.
- **AC-32.11.** Spec 27 AC-27.9 — every `nudge_mood` writes an OBSERVATION via `mirror_observation(intent_at_time="mood nudge")` with `context = {dim, delta, reason}`.
- **AC-32.12.** Spec 29 AC-29.17 — bootstrap `finalize` writes a LESSON via `mirror_lesson(intent_at_time="self bootstrap complete")`.
- **AC-32.13.** Spec 36 (Warden-on-self-writes) blocked attempts write an OBSERVATION `"warden blocked self write"` — see spec 36.

### Transactionality

- **AC-32.14.** A self-model write and its mirror succeed-or-fail atomically. A mirror failure after a successful write rolls back the write. Test with an induced failure in the bridge.
- **AC-32.15.** The bridge never mutates existing memories; it only inserts. Test over all five helpers.

### Observability

- **AC-32.16.** Every mirrored memory is tagged via `context.mirror = True`. Queries that count self-originated memories filter on this. Test.

### Counter assertions

- **AC-32.17.** After running the full sketch test suite, the count of episodic+durable memories for any bootstrapped `self_id` equals the count of self-model mutations plus 200 (bootstrap answers) plus 1 (finalize LESSON). Integration test.

## Implementation

```python
# self_memory_bridge.py

def mirror_observation(
    self_id: str, content: str, intent_at_time: str,
    context: dict | None = None,
) -> str:
    _validate_lengths(content, intent_at_time)
    ctx = _augment_context(self_id, context)
    return write_paths.write_observation(
        self_id=self_id,
        content=content[:MIRROR_CONTENT_MAX],
        intent_at_time=intent_at_time,
        context=ctx,
    )


def _augment_context(self_id: str, ctx: dict | None) -> dict:
    out = dict(ctx or {})
    out.setdefault("self_id", self_id)
    out["mirror"] = True
    rh = _request_hash_var.get(default=None)
    if rh is not None:
        out["request_hash"] = rh
    ptc = _perception_tool_call_id_var.get(default=None)
    if ptc is not None:
        out["perception_tool_call_id"] = ptc
    return out
```

Each of the named write-sites adds exactly one bridge call in the same `with repo.transaction():` scope. A helper `@with_mirror(intent_at_time, tier)` decorator is optional but not required; explicit calls keep the call-site readable.

## Open questions

- **Q32.1.** 200 bootstrap answers each write an OBSERVATION. That's 200 memory rows on day one, dominating the memory store for a fresh self. An alternative is one LESSON summarizing bootstrap with `context.answer_ids = [...]` and no per-answer mirror. Current spec follows the per-answer design because AC-23.9 is explicit; worth revisiting if memory volume becomes a retrieval-quality concern.
- **Q32.2.** Should `nudge_mood` mirror even when the delta clamps to zero (no effective change)? Current spec says yes — the attempt is history; the result is incidental. Drop if it produces noise.
- **Q32.3.** Mirror failures roll back the write. An alternative is "log and continue" — the self still updates its model, but the memory is lost. Rolling-back is the safer default for research posture; production may prefer the other.
