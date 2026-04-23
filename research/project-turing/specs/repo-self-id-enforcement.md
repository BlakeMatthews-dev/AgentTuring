# Spec 47 — Repo-layer self-id enforcement + FK (G13, G14)

*Every `SelfRepo` write method validates `acting_self_id`; every self-model table has a foreign key to `self_identity`. Closes F24 (full), F25.*

**Depends on:** [self-schema.md](./self-schema.md), [persistence.md](./persistence.md), [self-write-preconditions.md](./self-write-preconditions.md).
**Depended on by:** —

---

## Current state

Low-level repo methods accept rows without validating that the acting self owns the target. `self_id TEXT NOT NULL` is a column on every table but there is no FK to `self_identity(self_id)`. A typo creates a phantom self, invisible to identity queries but with live rows.

## Target

1. Every `SelfRepo.update_*`, `SelfRepo.insert_contributor`, `SelfRepo.insert_todo_revision`, etc. gains an `acting_self_id: str` keyword-only parameter; mismatch raises `CrossSelfAccess`.
2. Schema migration adds `FOREIGN KEY (self_id) REFERENCES self_identity(self_id) ON DELETE RESTRICT` on every self-model table.
3. `PRAGMA foreign_keys = ON` is set on every connection.

## Acceptance criteria

### Parameter enforcement

- **AC-47.1.** Every `SelfRepo.insert_*` and `SelfRepo.update_*` method signature gains `*, acting_self_id: str`. Method body validates `row.self_id == acting_self_id`; mismatch raises `CrossSelfAccess(row.self_id, acting_self_id)`. Test per method.
- **AC-47.2.** Applies to: `insert_facet`, `update_facet_score`, `insert_item`, `insert_answer`, `insert_revision`, `insert_passion`, `update_passion`, `insert_hobby`, `update_hobby`, `insert_interest`, `insert_preference`, `insert_skill`, `update_skill`, `insert_todo`, `update_todo`, `insert_todo_revision`, `insert_mood`, `update_mood`, `insert_contributor`, `mark_contributor_retracted`, `insert_pending_contributor`. Test each.
- **AC-47.3.** Tool-surface callers pass `self_id` through. Existing tests updated to pass `acting_self_id`. Test.

### Foreign key migration

- **AC-47.4.** Every self-model table gains `FOREIGN KEY (self_id) REFERENCES self_identity(self_id) ON DELETE RESTRICT`. Migration script in `schema_migrations/` applies on startup. Test.
- **AC-47.5.** Insert with a `self_id` not in `self_identity` raises `IntegrityError`. Test.
- **AC-47.6.** `PRAGMA foreign_keys = ON` is set at every connection open (it's per-connection in SQLite). Test with a fresh connection.
- **AC-47.7.** Deleting a `self_identity` row with dependent self-model rows raises. Operators who want to delete a self must first call a future `stronghold self retire --cascade` (out of scope here). Test.

### Migration safety

- **AC-47.8.** Migration is idempotent: running on a DB that already has FKs is a no-op. Test.
- **AC-47.9.** If pre-migration rows have `self_id` values not in `self_identity` (phantom selves), migration fails loudly and refuses to proceed. The operator must triage. Test with a fixture containing a phantom row.

### Observability

- **AC-47.10.** Counter `turing_cross_self_access_blocked_total{method, acting_self_id}` increments on each `CrossSelfAccess`. Test.

### Edge cases

- **AC-47.11.** `mark_contributor_retracted(contributor_node_id, retracted_by)` validates that the contributor's own `self_id` matches the caller's `acting_self_id`. Test.
- **AC-47.12.** Bootstrap inserts (facets, items, answers, mood) pass `acting_self_id` matching the bootstrapping self. Test the full bootstrap succeeds.
- **AC-47.13.** Tests written before this spec landed used `srepo.insert_X(row)` without `acting_self_id`. Migration tactic: add a deprecation-warning shim for the old signature for one tranche, then remove. Test the shim fires a DeprecationWarning.

## Implementation

```python
# self_repo.py pattern applied to every write method

class CrossSelfAccess(Exception):
    def __init__(self, row_self_id: str, acting_self_id: str):
        self.row_self_id = row_self_id
        self.acting_self_id = acting_self_id


def insert_passion(self, p: Passion, *, acting_self_id: str) -> Passion:
    if p.self_id != acting_self_id:
        raise CrossSelfAccess(p.self_id, acting_self_id)
    self._conn.execute(...)
    self._conn.commit()
    return p
```

Schema migration (SQLite's limited ALTER TABLE means recreate + copy):

```sql
-- schema_migrations/2026_04_22_self_id_fk.sql
PRAGMA foreign_keys = OFF;
BEGIN TRANSACTION;

CREATE TABLE self_personality_facets_new (
    node_id          TEXT PRIMARY KEY,
    self_id          TEXT NOT NULL REFERENCES self_identity(self_id) ON DELETE RESTRICT,
    trait            TEXT NOT NULL,
    facet_id         TEXT NOT NULL,
    score            REAL NOT NULL CHECK (score >= 1.0 AND score <= 5.0),
    last_revised_at  TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    UNIQUE (self_id, trait, facet_id)
);

INSERT INTO self_personality_facets_new SELECT * FROM self_personality_facets;
DROP TABLE self_personality_facets;
ALTER TABLE self_personality_facets_new RENAME TO self_personality_facets;

-- (repeat for each of the 13 self-* tables)

COMMIT;
PRAGMA foreign_keys = ON;
```

Connection open:

```python
# repo.py

class Repo:
    def __init__(self, ...):
        self._conn = sqlite3.connect(...)
        self._conn.execute("PRAGMA foreign_keys = ON")
        ...
```

## Open questions

- **Q47.1.** `ON DELETE RESTRICT` prevents self deletion when dependent rows exist. Alternative: `ON DELETE CASCADE` — deleting a self cascades to every self-model row. Research-branch posture is audit-friendly: RESTRICT, force explicit decision.
- **Q47.2.** SQLite's "recreate table" migration is heavy for production data. For this research sketch: fine. For any production port: convert to Postgres and use proper `ALTER TABLE ADD CONSTRAINT`.
- **Q47.3.** Existing-tests-update tactic is either "pass `acting_self_id` in every call" (~40 test edits) or "wrap via a test helper that defaults `acting_self_id=row.self_id`." The helper is less noisy but hides the intent that tests verify the behavior under correct matching.
