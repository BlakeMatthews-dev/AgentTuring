# Spec 66 — Operator coaching channel

*A dedicated path for the operator to write directly to the self's memory as `I_WAS_TOLD` observations. Distinct from the review gate (which approves self-authored proposals); this is one-way operator → self teaching.*

**Depends on:** [schema.md](./schema.md), [write-paths.md](./write-paths.md), [memory-mirroring.md](./memory-mirroring.md), [operator-review-gate.md](./operator-review-gate.md), [forensic-tagging.md](./forensic-tagging.md).
**Depended on by:** —

---

## Current state

Operators can reject or approve self-authored proposals via the review gate (spec 46). They cannot proactively **tell** the self anything. A deployment where the operator notices "the self keeps missing X" has no direct channel to say so — only indirect nudges via Sentinel rules, Warden config, or post-hoc writes to the raw DB (out-of-band provenance, spec 39).

## Target

A CLI-invoked command `stronghold self coach <content>` and a corresponding API endpoint that writes an `I_WAS_TOLD` memory with `intent_at_time = "operator coaching"`. Memories carry the operator's identity, are signed (spec 48's operator key pattern), and surface in the self's retrieval pipeline per the normal `I_WAS_TOLD` source rules.

## Acceptance criteria

### CLI

- **AC-66.1.** `stronghold self coach "<content>" [--tier {observation,opinion,lesson}] [--weight W] [--tag K=V]*` writes a memory of the given tier (default `OPINION`), `source = I_WAS_TOLD`, `intent_at_time = "operator coaching"`, weight per the tier's default range. Test each tier.
- **AC-66.2.** Content length capped at `COACHING_CONTENT_MAX = 2000` chars. Over-cap rejects with a usage error. Test.
- **AC-66.3.** `--tag K=V` flags populate `context` as key-value pairs. `--tag specialist=artificer --tag topic=reviews` becomes `context = {specialist: "artificer", topic: "reviews", ...}`. Test.
- **AC-66.4.** Operator identity: the command reads `OPERATOR_IDENTITY` env var (required; startup fails if unset in `CONDUIT_MODE=self`). Value is stored as `context.operator_id`. Test.

### Signing

- **AC-66.5.** Every coaching memory is signed with the operator key (spec 48's HMAC). Signature covers `{self_id, content, intent_at_time, created_at, operator_id}`. Stored in `context.signature`. Test.
- **AC-66.6.** Verification at read time: retrieval that surfaces a coaching memory verifies its signature. Tamper → memory is treated as deleted + a REGRET-tier "a coaching memory I held was tampered" is minted. Test.

### Durable vs non-durable

- **AC-66.7.** `--tier lesson` produces a durable-tier LESSON memory (per spec 2's tier-set). Durable memories cannot be rescinded (spec 3 invariants) but can be superseded by a later coaching with `--supersedes <memory_id>`. Test.
- **AC-66.8.** Non-durable tiers (`observation`, `opinion`) follow standard decay rules. Test.
- **AC-66.9.** Bulk mode: `stronghold self coach --file coaching.yaml` reads a list of entries from a YAML file. Each row becomes a memory. Useful for seeding. Test with a fixture file.

### Retrieval integration

- **AC-66.10.** Coaching memories participate in spec 16 semantic retrieval normally. They can become retrieval contributors (spec 25) on any target — no special privilege beyond what any `I_WAS_TOLD` memory has. Test.
- **AC-66.11.** Coaching memories are explicitly visible in `recall_self()` under a new `recent_coaching` section (top-5 most recent). Test.

### Mood interaction

- **AC-66.12.** A coaching memory that gets written optionally nudges mood via `apply_event_nudge(self_id, "operator_coaching_received", reason=...)`. Event default nudge: `(focus, +0.05)` — "my teacher spoke; I pay a bit more attention." Test.
- **AC-66.13.** `--no-mood` flag on the CLI skips the nudge for silent corrections that don't warrant an emotional beat. Test.

### Self-observability of coaching

- **AC-66.14.** A new `self_coaching_log` table (distinct from memory) records every coaching event with a timestamp, operator, tier, memory_id, and an index on `recorded_at`. Used for auditing and detecting over-coaching. Test.
- **AC-66.15.** If the operator writes `> OPERATOR_COACHING_BUDGET = 5` coachings in a rolling 24 hours, subsequent coaching attempts emit a warning (but still proceed). Signals over-steer. Test.

### API endpoint

- **AC-66.16.** `POST /v1/self/coach` accepts JSON `{content, tier, weight?, tags?}` + the operator key in an auth header. Returns the memory_id. Test.
- **AC-66.17.** The endpoint is the only path outside the CLI that can write operator-coaching memories. Rate-limited at `COACHING_API_RATE = 10/minute`. Test.

### Forensic trail

- **AC-66.18.** Coaching memories persist `context.provenance = "operator-coaching"` instead of the default `request_hash` or `out_of_band`. Spec 39 schema trigger allows this provenance value. Test.

### Edge cases

- **AC-66.19.** Coaching during bootstrap (pre-finalize) is allowed but carries `context.bootstrap_phase = True`. Useful for setting baseline norms before the self is live. Test.
- **AC-66.20.** Empty content rejected at the CLI and API. Test.
- **AC-66.21.** A coaching memory's signature check failing at retrieval does not block the request that triggered retrieval — it warns, skips the memory, and logs a security incident. Test.
- **AC-66.22.** Coaching memories are NOT surfaced to the minimal prompt block automatically. The self must call `recall_self` or retrieval must select them. Rationale: keep the minimal block stable; coaching influences thought via deeper consultation. Test.

## Implementation

```python
# self_coaching.py

COACHING_CONTENT_MAX: int = 2000
OPERATOR_COACHING_BUDGET: int = 5  # per 24h


def coach_self(
    repo, self_id: str, *, content: str, tier: MemoryTier = MemoryTier.OPINION,
    weight: float | None = None, tags: dict | None = None,
    operator_id: str, skip_mood: bool = False,
) -> str:
    if not content.strip():
        raise ValueError("content required")
    if len(content) > COACHING_CONTENT_MAX:
        raise ValueError(f"content exceeds {COACHING_CONTENT_MAX} chars")

    now = datetime.now(UTC)
    mem_context = {
        **(tags or {}),
        "operator_id": operator_id,
        "provenance": "operator-coaching",
    }
    canonical = _canonical_form(self_id, content, "operator coaching", now, operator_id)
    mem_context["signature"] = _sign(canonical)

    memory_id = write_paths.write(
        self_id=self_id, tier=tier,
        content=content,
        weight=weight or _default_weight_for_tier(tier),
        source=SourceKind.I_WAS_TOLD,
        intent_at_time="operator coaching",
        context=mem_context,
    )
    repo.insert_coaching_log(
        self_id=self_id, memory_id=memory_id, operator_id=operator_id,
        tier=tier.value, recorded_at=now,
    )
    _maybe_warn_over_budget(repo, self_id, operator_id, now)
    if not skip_mood:
        apply_event_nudge(repo, self_id, "operator_coaching_received",
                          reason=f"from {operator_id}")
    return memory_id


EVENT_NUDGES["operator_coaching_received"] = [("focus", +0.05)]
```

## Open questions

- **Q66.1.** Coaching is one-way. A two-way "the self pushes back on a coaching" mechanism is plausible but out of scope — the self can respond in natural language during the next request, but the coaching memory itself is immutable-by-self.
- **Q66.2.** Bulk mode via YAML file is useful for seeding but risks large-batch misconfiguration. A dry-run mode (`--dry-run`) that prints what would be written before writing. Recommend adding.
- **Q66.3.** Signing coaching memories is a check against tamper from outside the runtime — useful for compliance, overkill for casual deployments. Signature verification on read is the hot path; cache signatures per process to avoid per-read HMAC cost.
- **Q66.4.** Operator over-coaching detection (AC-66.15) is a hint. A self that relies heavily on coaching may lose its own agency. Flag for future study.
- **Q66.5.** Writing to `recent_coaching` section of `recall_self` vs. distributing coaching memories evenly through retrieval — current spec does both. The dedicated section makes coaching inspectable; retrieval makes it operational.
