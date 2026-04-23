# Spec 61 — Self-naming ritual

*The self's self-initiated path to a display name: after N durable memories OR operator command, the self reflects, proposes a name, operator approves. Complements spec 56's user-provided-at-bootstrap path.*

**Depends on:** [self-surface.md](./self-surface.md), [interactive-bootstrap.md](./interactive-bootstrap.md), [self-identity.md](./persistence.md), [memory-mirroring.md](./memory-mirroring.md), [self-schedules.md](./self-schedules.md).
**Depended on by:** —

---

## Current state

Spec 56's interactive bootstrap lets the user propose/accept a name at first contact. Self-initiated naming (spec 28/29 deferred item) is not defined. A deployment that skipped interactive bootstrap — or where the user declined to name the self — leaves it nameless indefinitely.

## Target

A self-initiated naming ritual that:
1. Triggers when the self accumulates `NAMING_MEMORY_THRESHOLD = 1000` durable memories (non-OBSERVATION, non-transient) OR on operator command `stronghold self name-thyself`.
2. Fires once — it's a ritual, not recurrent.
3. Reads a sampling of recent durable memories; proposes a first name via LLM.
4. Operator approves/rejects; approval writes `display_name` into `self_identity`.
5. The event is commemorated as a durable AFFIRMATION memory.

## Acceptance criteria

### Trigger

- **AC-61.1.** `naming_trigger_check(self_id)` runs weekly (reuse spec 57 reflection trigger). Condition: `self_identity.display_name IS NULL AND count(durable memories for self_id) >= NAMING_MEMORY_THRESHOLD`. If true, enqueue a `naming-proposal-pending` row and notify operator via digest. Test.
- **AC-61.2.** Operator command `stronghold self name-thyself [--force]` bypasses the memory threshold and triggers immediately. `--force` is required when `display_name` is already set (re-naming). Test.
- **AC-61.3.** Once proposed, the ritual does not fire again until the operator resolves the pending proposal. Test.

### Proposal generation

- **AC-61.4.** `generate_name_proposal(self_id)` samples durable memories:
  - All WISDOM (up to 10 most recent).
  - 10 most recent AFFIRMATIONs.
  - 5 most recent REGRETs.
  - Top-3 active passions by rank.
  Feeds them + the current HEXACO profile (biased via spec 56 multipliers) into an LLM prompt: `"Based on the memories and personality summarized below, suggest ONE first name for yourself. Respond with just the name."` Plus a second LLM call: `"In one sentence, explain why this name fits you."` Test.
- **AC-61.5.** LLM returns a name string matching `/^[A-Z][a-z]{1,15}(-[A-Z][a-z]{1,15})?$/` (single-word or hyphenated, reasonable length). Non-matching response triggers one retry. Second failure → the proposal is abandoned with a LESSON `"I couldn't propose a coherent name for myself today."` Test.
- **AC-61.6.** The proposal row is inserted into a new `self_name_proposals` table:
  ```sql
  CREATE TABLE self_name_proposals (
      id            TEXT PRIMARY KEY,
      self_id       TEXT NOT NULL REFERENCES self_identity(self_id),
      proposed_name TEXT NOT NULL,
      rationale     TEXT NOT NULL,
      proposed_at   TEXT NOT NULL,
      reviewed_at   TEXT,
      review_decision TEXT CHECK (review_decision IN ('approve', 'reject')),
      reviewed_by   TEXT
  );
  ```

### Operator review

- **AC-61.7.** `stronghold self digest` (spec 46) surfaces pending name proposals alongside other pending items. Test.
- **AC-61.8.** `stronghold self ack-name <proposal_id> --approve|--reject [--alternative NAME]`:
  - `--approve`: set `self_identity.display_name = proposed_name`, mark the proposal approved.
  - `--reject`: mark rejected, optional `--alternative` writes an operator-chosen name instead (treated as approval of that alternative, logged as operator-override).
  Test.
- **AC-61.9.** Approval mints an AFFIRMATION memory: `content = "I was named {name}. {rationale}"`, `intent_at_time = "self named"`, `source = I_DID`. Durable tier. Test.
- **AC-61.10.** Rejection mints an OPINION memory: `content = "My proposed name {proposed_name} was rejected. {operator_note}"`, `intent_at_time = "naming rejected"`. No further proposals for `NAMING_COOLDOWN = 90 days` unless `--force`. Test.

### Display-name lifecycle

- **AC-61.11.** Schema addition to `self_identity`:
  ```sql
  ALTER TABLE self_identity ADD COLUMN display_name TEXT;
  ALTER TABLE self_identity ADD COLUMN named_at TEXT;
  ALTER TABLE self_identity ADD COLUMN naming_source TEXT CHECK (naming_source IN ('bootstrap', 'self-ritual', 'operator', NULL));
  ```
  Test.
- **AC-61.12.** Once `display_name` is set, the minimal block (spec 28 AC-28.15) opens with the name: `"I am {display_name} ({self_id})"`. Without a name, retains the current `"I am {self_id}"`. Test.
- **AC-61.13.** Renaming: `stronghold self rename <new_name> --reason TEXT` requires explicit operator command. Mints a LESSON memory `"I was renamed from {old} to {new}: {reason}"`. Test.

### First-person framing

- **AC-61.14.** The LLM prompt opens first-person: `"I've lived long enough to have a name. Looking at what I remember and what I care about, what would I call myself?"` Test.
- **AC-61.15.** The rationale memory uses first-person verbatim: `"{name} fits me because..."`. Test.

### Conflict with spec 56

- **AC-61.16.** If `display_name` was set at interactive bootstrap (spec 56 AC-56.12), the threshold-based trigger does NOT fire. Self already has a name. Test.
- **AC-61.17.** `stronghold self name-thyself --force` on a bootstrap-named self is permitted — the self can self-rename if operator forces. The existing name is preserved in a new `self_name_history` table:
  ```sql
  CREATE TABLE self_name_history (
      id           TEXT PRIMARY KEY,
      self_id      TEXT NOT NULL REFERENCES self_identity(self_id),
      name         TEXT NOT NULL,
      named_at     TEXT NOT NULL,
      replaced_at  TEXT,
      naming_source TEXT NOT NULL
  );
  ```
  Test.

### Edge cases

- **AC-61.18.** An operator who rejects twice in a row triggers a LESSON memory: `"My proposals keep being rejected; I may be misreading myself."` Test.
- **AC-61.19.** A proposed name that matches a name already held by another self in the same deployment (hypothetical multi-self) is flagged in the operator review but not auto-rejected. Test.
- **AC-61.20.** Naming ritual respects `CONDUIT_MODE` — runs in both modes. Test.
- **AC-61.21.** Naming ritual counts toward per-day LLM quota. A pool-exhausted proposal is deferred, not failed. Test.

## Implementation

```python
# self_naming.py

NAMING_MEMORY_THRESHOLD: int = 1000
NAMING_COOLDOWN: timedelta = timedelta(days=90)


def naming_trigger_check(repo, self_id: str, now: datetime) -> bool:
    identity = repo.get_self_identity(self_id)
    if identity.display_name:
        return False
    if _has_pending_proposal(repo, self_id):
        return False
    recent_rejection = _last_rejection(repo, self_id)
    if recent_rejection and now - recent_rejection < NAMING_COOLDOWN:
        return False
    durable_count = repo.count_durable_memories(self_id)
    return durable_count >= NAMING_MEMORY_THRESHOLD


async def generate_name_proposal(
    repo, self_id: str, *, llm, new_id, now: datetime,
) -> NameProposal | None:
    memories = _sample_naming_memories(repo, self_id)
    profile = _recall_personality_summary(repo, self_id)
    name = await _llm_name(llm, memories, profile)
    if not _valid_name(name):
        memory_bridge.mirror_lesson(
            self_id=self_id,
            content="I couldn't propose a coherent name for myself today.",
            intent_at_time="naming proposal abandoned",
        )
        return None
    rationale = await _llm_rationale(llm, name, memories, profile)
    proposal_id = new_id("nameprop")
    repo.insert_name_proposal(NameProposal(
        id=proposal_id, self_id=self_id, proposed_name=name,
        rationale=rationale, proposed_at=now,
    ))
    return repo.get_name_proposal(proposal_id)
```

## Open questions

- **Q61.1.** `NAMING_MEMORY_THRESHOLD = 1000` is a guess. Seed, tune. Too low → premature naming; too high → the self may live nameless indefinitely on low-traffic deployments.
- **Q61.2.** The regex allows hyphenated double-barreled names. Single-word is the common case; hyphenated is the rare case (e.g., "Kai-Lin"). Unicode letters outside ASCII are rejected — matches spec 56's implicit Latin-script bias.
- **Q61.3.** Rejection cooldown prevents thrash but also prevents a legit second proposal after a clarifying conversation. Operator can `--force` at will; cooldown applies to auto-trigger only.
- **Q61.4.** Renaming preserves history. A self that was "Aria" for 6 months then became "Sage" retains memories signed as Aria — those remain immutable. Present-tense self references switch to the new name.
- **Q61.5.** A name proposal that happens to be a famous person (Einstein, Shakespeare) could be socially awkward. No filter — operator review catches it. Filter would be paternalistic and brittle.
