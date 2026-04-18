# Spec 8 — Persistence, migration, and self_id minting

*The append-only storage layer for durable memory, the contract for version migrations, and how the stable `self_id` is minted and preserved.*

**Depends on:** [schema.md](./schema.md), [tiers.md](./tiers.md), [durability-invariants.md](./durability-invariants.md).
**Depended on by:** —

---

## Current state

- `main` uses the general episodic memory store, which supports soft-delete and row updates. No append-only constraint.
- `agent_id` is per-instance; a redeployment mints a new one. Nothing carries identity across versions.
- Migration scripts are not currently checked for preservation of any particular subset of rows.

## Target

Durable memories live in their own append-only table, separate from the general episodic store. Stable `self_id` is minted once and preserved across all subsequent deployments. Migrations that drop durable rows fail CI.

## Acceptance criteria

- **AC-8.1.** The `durable_memory` table has no `deleted` column. Schema-introspection test asserts absence.
- **AC-8.2.** Any attempted DELETE against `durable_memory` fails at the storage layer. Integration test with a DB trigger (PostgreSQL) or rule (SQLite research sketch).
- **AC-8.3.** Restarting the process preserves every durable memory. Integration test: write N memories, shut down, reload, assert all N retrievable.
- **AC-8.4.** A simulated migration that drops any durable row fails CI. Migration-verifier test: run migration in shadow, compare `SELECT COUNT(*) WHERE tier IN DURABLE_TIERS` before and after.
- **AC-8.5.** A migration that would remap an existing `self_id` fails CI. Test asserts the verifier catches remap attempts.
- **AC-8.6.** `self_id` is minted at bootstrap if and only if `self_identity` table is empty. Subsequent starts read the existing `self_id`. Integration test over two sequential bootstraps.
- **AC-8.7.** Minting a new `self_id` is an explicit operator command and archives the old entry. Test asserts the command path works and the old row is preserved (archived, not deleted).
- **AC-8.8.** Every migration emits a `tier = OBSERVATION`, `source = I_DID` marker memory recording the migration version and timestamp. The Conduit remembers its own upgrades. Integration test.

## Implementation

### 8.1 `durable_memory` table

```sql
CREATE TABLE durable_memory (
    memory_id              TEXT PRIMARY KEY,
    self_id                TEXT NOT NULL,
    tier                   TEXT NOT NULL CHECK (tier IN (
        'regret', 'accomplishment', 'wisdom', 'affirmation'
    )),
    source                 TEXT NOT NULL CHECK (source = 'i_did'),
    content                TEXT NOT NULL,
    weight                 REAL NOT NULL,
    affect                 REAL NOT NULL CHECK (affect BETWEEN -1.0 AND 1.0),
    confidence_at_creation REAL NOT NULL CHECK (confidence_at_creation BETWEEN 0.0 AND 1.0),
    surprise_delta         REAL NOT NULL CHECK (surprise_delta BETWEEN 0.0 AND 1.0),
    intent_at_time         TEXT NOT NULL,
    supersedes             TEXT REFERENCES durable_memory(memory_id),
    superseded_by          TEXT REFERENCES durable_memory(memory_id),
    origin_episode_id      TEXT,
    context                JSONB,
    immutable              BOOLEAN NOT NULL DEFAULT TRUE,
    reinforcement_count    INTEGER NOT NULL DEFAULT 0,
    contradiction_count    INTEGER NOT NULL DEFAULT 0,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- explicitly: no `deleted` column
);

-- Block deletes at the DB level.
CREATE OR REPLACE FUNCTION durable_memory_no_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'durable_memory is append-only; deletes are forbidden';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER durable_memory_block_delete
    BEFORE DELETE ON durable_memory
    FOR EACH ROW EXECUTE FUNCTION durable_memory_no_delete();
```

Indices:

- `(self_id, tier, created_at DESC)` — retrieval by self and tier.
- `(supersedes)` — lineage walks.
- `(superseded_by)` — finding superseded memories.
- `(origin_episode_id)` — session-linked retrievals.

### 8.2 `self_identity` table

```sql
CREATE TABLE self_identity (
    self_id        TEXT PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at    TIMESTAMPTZ,
    archive_reason TEXT
);
```

Exactly one row has `archived_at IS NULL` at any time. Bootstrap reads the non-archived row; if none exists, mints one.

```python
def bootstrap_self_id(conn) -> str:
    row = conn.fetch_one("SELECT self_id FROM self_identity WHERE archived_at IS NULL")
    if row:
        return row["self_id"]
    new_id = str(uuid4())
    conn.execute(
        "INSERT INTO self_identity (self_id) VALUES (%s)",
        [new_id],
    )
    return new_id
```

### 8.3 Migration contract

Every migration that touches `durable_memory` or `self_identity` is checked by a CI-level verifier:

1. **Row preservation.** `SELECT COUNT(*) FROM durable_memory` before and after. Must be monotonic non-decreasing. A migration that decreases the count fails.
2. **self_id preservation.** Active `self_id` must be unchanged or archived-and-replaced-with-operator-approval. Silent remap fails.
3. **Tier and source preservation.** No migration may change a row's `tier` or `source`. Upgrades are new rows with `supersedes`, never in-place.
4. **Migration marker.** Post-migration, an `OBSERVATION` memory is written to the general episodic store (not `durable_memory`, since it's not REGRET/ACCOMPLISHMENT/WISDOM/AFFIRMATION) with `source = I_DID`, `self_id` = current, `content = f"migration {version} applied"`, and timestamps. Verifier asserts this marker is present.

The verifier runs in CI as a shadow migration: apply the migration against a snapshot fixture, run the checks, roll back.

### 8.4 Research-mode storage

For Project Turing's initial research sketches, the `durable_memory` constraints are enforced via SQLite with triggers:

```sql
-- SQLite equivalent — trigger raises on DELETE.
CREATE TRIGGER durable_memory_block_delete
BEFORE DELETE ON durable_memory
BEGIN
    SELECT RAISE(ABORT, 'durable_memory is append-only');
END;
```

Production-grade deployment would use PostgreSQL with the trigger + RLS policies. Not in scope for this spec.

## Open questions

- **Q8.1.** `self_id` as UUID is opaque. An alternative is a human-readable handle minted from configuration. Opaque has a stronger incentive against collision; readable is easier to operate. Going with UUID for now; revisit.
- **Q8.2.** The migration marker lands in the general episodic store, not `durable_memory`. Correct reading of the invariants — OBSERVATION isn't durable — but an operator reading the durable store alone would not see migration history. Should there be a second marker pattern, or is an audit join sufficient?
- **Q8.3.** Archive of a retired `self_id` keeps the row but sets `archived_at`. Does the durable memory attached to that old `self_id` get migrated to the new one, or does it stay orphaned-but-readable under the archived self? Default: stays with the archived self; the new self starts fresh. But this is a real operator call and worth making explicit in ops docs.
