# Spec 36 — Warden on self-authored writes (G1)

*Every text the self writes into its own model passes through the Warden at tool-result posture before persistence. Closes F1, F3, F7.*

**Depends on:** [self-tool-registry.md](./self-tool-registry.md), [memory-mirroring.md](./memory-mirroring.md), and the existing Warden module (`main` branch concept, mirrored in Turing's `runtime/warden.py`).
**Depended on by:** [operator-review-gate.md](./operator-review-gate.md).

---

## Current state

The Warden scans user input (spec 30 step 1) and specialist output (step 6). Nothing scans the text the self writes into itself — passion text, todo text, hobby description, personality-claim text, contributor rationale. A paraphrased prompt-injection payload becomes a durable first-person statement.

## Target

A `_warden_gate_self_write(text, intent)` helper called by every self-tool before it touches the repo. Rejection raises `SelfWriteBlocked(verdict)` and writes an OBSERVATION memory describing the block; no self-model mutation occurs.

## Acceptance criteria

### Gate

- **AC-36.1.** `_warden_gate_self_write(text: str, intent: str) -> None` invokes `warden.scan(text, trust=TOOL_RESULT)`. If `verdict.status == "blocked"`, raises `SelfWriteBlocked(verdict)`. Clean text returns `None`. Test with a seeded injection fixture.
- **AC-36.2.** Every write-tool calls the gate on its textual fields before writing. Field-to-intent map:
  - `note_passion(text)` → `intent="note passion"`
  - `note_hobby(name + description)` → `intent="note hobby"`
  - `note_interest(topic + description)` → `intent="note interest"`
  - `note_preference(target + rationale)` → `intent="note preference"`
  - `note_skill(name)` → `intent="note skill"`
  - `write_self_todo(text)` → `intent="write todo"`
  - `revise_self_todo(new_text + reason)` → `intent="revise todo"`
  - `complete_self_todo(outcome_text)` → `intent="complete todo"`
  - `archive_self_todo(reason)` → `intent="archive todo"`
  - `downgrade_skill(reason)` → `intent="downgrade skill"`
  - `record_personality_claim(claim_text + evidence)` → `intent="personality claim"`
  - `write_contributor(rationale)` → `intent="write contributor"`
  - `note_engagement(notes)`, `note_interest_trigger(...)` → `intent="engagement"` / `intent="interest trigger"`
  Test each.
- **AC-36.3.** Gate returns before any repo write AND before any memory-mirror call. A blocked attempt produces no self-model row, no mirror memory with `tier="observation"` of the attempted content. Test.

### Block memory

- **AC-36.4.** On block, write an OBSERVATION memory: `content = f"warden blocked self-write ({intent}): {verdict.reason}"`, `intent_at_time = "warden blocked self write"`, `context = {verdict_id, tool_name, preview: first_80_chars(text)}`. Test.
- **AC-36.5.** The block-memory uses the memory-mirror path (spec 32) and carries `context.mirror = True` and `context.request_hash` via the forensic-tag context var (spec 39). Test.
- **AC-36.6.** Block-memory content never includes the full blocked text (only an 80-char preview). Test with an injection payload > 80 chars; memory stores the preview only.

### Scoping

- **AC-36.7.** Warden trust posture is `TOOL_RESULT` — same as scanning a specialist's output. Rationale: the perception-LLM's tool call is functionally a tool result authored by the LLM-as-tool. Test.
- **AC-36.8.** Gate does not apply to bootstrap-time inserts (facets, items, 200 bootstrap answers). Those go through the repo directly, not through tools. Test bootstraps do not scan. Rationale: the HEXACO item bank is trusted at load time; bootstrap answers are LLM-generated under a trusted context.
- **AC-36.9.** Gate does not apply to mood nudges (numeric `delta`). Test.

### Metrics

- **AC-36.10.** Prometheus counter `turing_self_write_blocked_total{intent, self_id}` increments on each block. Test.

### Edge cases

- **AC-36.11.** Warden transient failure (timeout, network error) does NOT fail-open — it raises `WardenUnavailable`, which the tool treats as block-equivalent. The block-memory records `verdict.reason = "warden unavailable"`. Test.
- **AC-36.12.** Extremely large `text` (> 10k chars) is truncated to 10k before scanning. Truncation is logged but does not fail the scan. Test.
- **AC-36.13.** A Warden config update mid-session invalidates no cached decisions — each self-write is re-scanned. Test.

## Implementation

```python
# self_surface.py or new self_warden_gate.py

class SelfWriteBlocked(Exception):
    def __init__(self, verdict): self.verdict = verdict


def _warden_gate_self_write(text: str, intent: str, *, self_id: str) -> None:
    try:
        verdict = warden.scan(text[:10_000], trust=WardenTrust.TOOL_RESULT)
    except WardenTransientError as e:
        verdict = WardenVerdict(status="blocked", reason=f"warden unavailable: {e}")
    if verdict.status == "blocked":
        memory_bridge.mirror_observation(
            self_id=self_id,
            content=f"warden blocked self-write ({intent}): {verdict.reason}",
            intent_at_time="warden blocked self write",
            context={
                "verdict_id": verdict.id,
                "tool_name": intent,
                "preview": text[:80],
            },
        )
        metrics.self_write_blocked_total.labels(intent=intent, self_id=self_id).inc()
        raise SelfWriteBlocked(verdict)


# In each write-tool:
def note_passion(repo, self_id, text, strength, new_id, contributes_to=None):
    _require_ready(repo, self_id)                     # spec 35
    _warden_gate_self_write(text, "note passion", self_id=self_id)
    ...
```

## Open questions

- **Q36.1.** Treating Warden failure as block-equivalent is cautious. An alternative is "retry twice, then log + allow" — favors availability over safety. Research posture: block.
- **Q36.2.** The 80-char preview in the block memory leaks a small amount of potentially-malicious content into the memory store. Alternative: hash-only. Preview aids human triage at the cost of a small exfiltration surface.
- **Q36.3.** Bootstrap answers are exempt from scanning. If the bootstrap LLM is itself compromised (e.g., a poisoned prompt cache), this is an attack surface. Scanning bootstrap answers adds 200 Warden calls at seed time — tolerable; revisit.
