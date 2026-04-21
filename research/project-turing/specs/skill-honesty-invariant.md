# Spec 43 — Skill-honesty invariant (G10)

*`practice_skill` can raise `stored_level` only when a same-request memory cites the supporting practice event. Closes F17.*

**Depends on:** [self-nodes.md](./self-nodes.md), [memory-mirroring.md](./memory-mirroring.md), [forensic-tagging.md](./forensic-tagging.md).
**Depended on by:** —

---

## Current state

`practice_skill(skill_id, new_level=...)` accepts any `new_level ≥ stored_level`. Nothing requires evidence. The self can ratchet skills upward on reflection alone, and only `downgrade_skill` can reduce (which the self is unlikely to reach for).

## Target

A `practice_skill(new_level=...)` call that **raises** `stored_level` requires a same-request OBSERVATION or ACCOMPLISHMENT memory with `context.skill_id = skill_id`. A pure `last_practiced_at` reset (no level change) remains unrestricted. A monthly "skill inflation" check runs in the tuner (spec 11).

## Acceptance criteria

### Level-raise precondition

- **AC-43.1.** `practice_skill(skill_id, new_level=X)` with `X > stored_level` requires at least one memory row for this `self_id` with `context.skill_id = skill_id` AND `intent_at_time` starting with `"practice "` OR tier in `{ACCOMPLISHMENT, OBSERVATION}` AND `context.request_hash = current_request_hash`. If none exists, raise `PracticeUnsupported(skill_id)`. Test both paths.
- **AC-43.2.** `practice_skill(skill_id, new_level=None, notes=...)` — a pure practice reset with no level change — is unchanged. No memory required. Test.
- **AC-43.3.** `practice_skill(skill_id, new_level=X)` with `X == stored_level` is also unrestricted (no-op on level). Test.

### Downgrade path unchanged

- **AC-43.4.** `downgrade_skill(skill_id, new_level, reason)` still works as specced; no memory requirement change. Test.

### Detection

- **AC-43.5.** Implementation queries the memory store at call-time:
  ```sql
  SELECT 1 FROM episodic_memory
  WHERE self_id = ?
    AND json_extract(context, '$.skill_id') = ?
    AND json_extract(context, '$.request_hash') = ?
    AND (intent_at_time LIKE 'practice %' OR tier = 'observation')
  LIMIT 1
  ```
  Index on `(self_id, json_extract(context, '$.skill_id'), created_at)` supports this. Test with EXPLAIN.

- **AC-43.6.** When no request scope is active (tests, scripts), the check falls back to looking at memories from the last 60 seconds. This allows unit tests to seed a memory then call `practice_skill` without a full request pipeline. Test both modes.

### Observability

- **AC-43.7.** Prometheus counter `turing_skill_practice_unsupported_total{skill_id, self_id}` increments on each `PracticeUnsupported`. Test.
- **AC-43.8.** Monthly scheduled check (runs in the tuner, spec 11): if a self has `>10` skills raised AND `0` downgrades in the last 90 days, emit a `turing_skill_inflation_detected{self_id}` gauge = 1 and write an OPINION memory `"skill inflation pattern detected"`. Test with fabricated skill history.

### Interaction with other specs

- **AC-43.9.** Level raise is subject to the per-request budget (spec 37) because it's effectively a self-state mutation. Counts against `contributors`... actually, `practice_skill` is specifically EXEMPT from the budget per spec 37 AC-37.8. Confirm with a test: budget is unchanged before/after `practice_skill`.
- **AC-43.10.** Supporting memory can be written in the same request but **before** the `practice_skill` call. Spec 30's pipeline allows the self to call tools in sequence; honesty is satisfied if the memory exists at `practice_skill` time. Test.

### Edge cases

- **AC-43.11.** A supporting memory with `context.skill_id` matching an ARCHIVED skill still counts. The self can revive a skill through practice. Test.
- **AC-43.12.** A `practice_skill(new_level=0.9)` where the skill was at 0.89 — tiny raise — still requires supporting memory. No noise-floor exemption (the principle is "evidence before claim," regardless of size). Test.
- **AC-43.13.** Test-fixture mode (no request scope, 60s window) is documented and not available in production: the conduit runtime always sets a request scope (spec 39). Test that with `CONDUIT_MODE = "self"`, the 60s fallback is disabled.

## Implementation

```python
# self_nodes.py

class PracticeUnsupported(Exception):
    def __init__(self, skill_id: str):
        self.skill_id = skill_id


def practice_skill(
    repo, self_id, skill_id,
    new_level: float | None = None, notes: str = "",
) -> Skill:
    s = repo.get_skill(skill_id)
    if s.self_id != self_id:
        raise PermissionError("cross-self practice forbidden")

    if new_level is not None and new_level > s.stored_level:
        if not _has_supporting_memory(repo, self_id, skill_id):
            raise PracticeUnsupported(skill_id)
        s.stored_level = new_level

    s.last_practiced_at = datetime.now(UTC)
    repo.update_skill(s, acting_self_id=self_id)
    memory_bridge.mirror_observation(
        self_id=self_id,
        content=f"[practice skill] {s.name}: {notes}",
        intent_at_time="practice skill",
        context={"skill_id": skill_id, "notes": notes},
    )
    return s


def _has_supporting_memory(repo, self_id: str, skill_id: str) -> bool:
    request_hash = _request_hash_var.get(default=None)
    if request_hash is not None:
        return repo.memory_repo.has_skill_memory(
            self_id=self_id, skill_id=skill_id, request_hash=request_hash,
        )
    # Test-fixture fallback: last 60 seconds.
    return repo.memory_repo.has_skill_memory_recent(
        self_id=self_id, skill_id=skill_id,
        since=datetime.now(UTC) - timedelta(seconds=60),
    )
```

## Open questions

- **Q43.1.** The 60-second fallback is generous for tests but leaks into production if a request scope is ever accidentally unset. Stricter: no fallback; tests must always wrap in `request_scope`. Stricter is better but requires a larger test-refactor.
- **Q43.2.** Detection uses `intent_at_time LIKE 'practice %'`. A more structured alternative is `context.evidence_for = 'skill:X'` as a dedicated field. Deferred.
- **Q43.3.** Monthly inflation check runs in the tuner. If the tuner is not yet running in a deployment, inflation goes undetected. Log a one-time warning at startup if the tuner is disabled.
