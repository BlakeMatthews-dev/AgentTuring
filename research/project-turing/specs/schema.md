# Spec 1 — Schema additions to `EpisodicMemory`

*Field additions required to index memories to a persistent self and to type their provenance.*

**Depends on:** —
**Depended on by:** all later specs.

---

## Current state

From `src/stronghold/types/memory.py`:

- `EpisodicMemory` carries `agent_id`, `user_id`, `org_id`, `team_id`, `scope`, `source: str` (free-form), `context`, `reinforcement_count`, `contradiction_count`, `deleted: bool`.
- No stable self-identity that outlives the `agent_id`.
- No first-person markers (affect, confidence at encoding, surprise).
- No provenance typing — `source` is prose and not constrained.
- No lineage — a memory cannot point to the one it replaced.

## Target

Extend `EpisodicMemory` so it can carry the structural information an autonoetic self needs: who the self is, what the source of the memory is, what the stance was at encoding, and what memory (if any) this one supersedes.

## Acceptance criteria

- **AC-1.1.** Constructing an `EpisodicMemory` without `self_id` raises `ValueError`. Negative test exists.
- **AC-1.2.** `source` is typed as `SourceKind`, not `str`. The old free-form string is rejected. Type-check test.
- **AC-1.3.** `affect` is constrained to `[-1.0, 1.0]`. Values outside raise on construction. Property test over random floats.
- **AC-1.4.** `confidence_at_creation` and `surprise_delta` are constrained to `[0.0, 1.0]`. Values outside raise. Property test.
- **AC-1.5.** `supersedes` and `superseded_by` each refer to a valid `memory_id` or are `None`. A memory cannot supersede itself. Negative test for self-reference.
- **AC-1.6.** `immutable` defaults to `False`. Setting it to `True` at construction is allowed; mutating it after construction raises. Test asserts the field is write-once.

## Implementation

```python
from enum import StrEnum
from dataclasses import dataclass, field
from datetime import UTC, datetime


class SourceKind(StrEnum):
    I_DID = "i_did"
    I_WAS_TOLD = "i_was_told"
    I_IMAGINED = "i_imagined"


@dataclass(frozen=False)
class EpisodicMemory:
    # Identity
    memory_id: str
    self_id: str                          # stable; survives agent_id changes
    tier: "MemoryTier"                    # see spec 2
    content: str
    weight: float

    # Provenance
    source: SourceKind

    # First-person markers
    affect: float = 0.0                   # [-1.0, 1.0]
    confidence_at_creation: float = 0.0   # [0.0, 1.0]
    surprise_delta: float = 0.0           # [0.0, 1.0]
    intent_at_time: str = ""

    # Lineage
    supersedes: str | None = None
    superseded_by: str | None = None
    origin_episode_id: str | None = None

    # Durability flag
    immutable: bool = False

    # Counters
    reinforcement_count: int = 0
    contradiction_count: int = 0

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Freeform context (e.g., list of contributing memory_ids)
    context: dict[str, object] = field(default_factory=dict)
```

Validation lives in `__post_init__`:

```python
def __post_init__(self) -> None:
    if not self.self_id:
        raise ValueError("self_id is required")
    if not -1.0 <= self.affect <= 1.0:
        raise ValueError(f"affect out of range: {self.affect}")
    if not 0.0 <= self.confidence_at_creation <= 1.0:
        raise ValueError("confidence_at_creation out of range")
    if not 0.0 <= self.surprise_delta <= 1.0:
        raise ValueError("surprise_delta out of range")
    if self.supersedes is not None and self.supersedes == self.memory_id:
        raise ValueError("memory cannot supersede itself")
```

`immutable` write-once is enforced by a `__setattr__` override that raises if the attribute already exists and is `True`.

## Open questions

- **Q1.1.** Free-form `context: dict[str, object]` invites drift. Should it be a typed variant with a known set of keys, or is the flexibility worth the looseness?
- **Q1.2.** `confidence_at_creation` in `[0.0, 1.0]` is tidy but loses the distinction between "I had no belief" and "I had a 0.5 belief." Should there be a `has_prior: bool`?
