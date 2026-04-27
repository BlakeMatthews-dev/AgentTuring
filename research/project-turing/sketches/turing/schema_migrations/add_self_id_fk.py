"""Migration: add self_id -> self_identity(self_id) FK to all qualifying tables.

Qualifying tables:
  - All self_* tables with a self_id column, except self_identity itself
  - working_memory, voice_section, conversation_turn, reward_events, code_snapshots

Uses SQLite "recreate table" pattern (CREATE new -> INSERT -> DROP old -> RENAME).
Idempotent: skips tables where the FK already exists.
Atomic: all changes in a single transaction.
Raises on phantom self_id values (orphan references to non-existent self_identity rows).

Usage::

    import sqlite3
    conn = sqlite3.connect("turing.db")
    add_self_id_fk.apply_migration(conn)
"""

import re
import sqlite3

FK_CLAUSE = "REFERENCES self_identity(self_id) ON DELETE RESTRICT"

EXTRA_TABLES = frozenset(
    {
        "working_memory",
        "voice_section",
        "conversation_turn",
        "reward_events",
        "code_snapshots",
    }
)


def _discover_target_tables(cur: sqlite3.Cursor) -> list[str]:
    targets: list[str] = []
    for (name,) in cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall():
        if name == "self_identity":
            continue
        cols = {r[1] for r in cur.execute(f"PRAGMA table_info([{name}])").fetchall()}
        if "self_id" not in cols:
            continue
        if name.startswith("self_") or name in EXTRA_TABLES:
            targets.append(name)
    return sorted(targets)


def _check_phantoms(cur: sqlite3.Cursor, tables: list[str]) -> None:
    for table in tables:
        phantoms = cur.execute(
            f"SELECT DISTINCT [{table}].self_id "
            f"FROM [{table}] "
            f"LEFT JOIN self_identity ON [{table}].self_id = self_identity.self_id "
            f"WHERE self_identity.self_id IS NULL"
        ).fetchall()
        if phantoms:
            ids = [r[0] for r in phantoms]
            raise ValueError(
                f"Phantom self_ids in '{table}' (not in self_identity): {ids}. "
                f"Resolve these before migration."
            )


def _has_self_id_fk(cur: sqlite3.Cursor, table: str) -> bool:
    fks = cur.execute(f"PRAGMA foreign_key_list([{table}])").fetchall()
    return any(fk[2] == "self_identity" and fk[3] == "self_id" for fk in fks)


def _inject_fk(sql: str, table: str) -> str:
    new_sql = re.sub(
        r"(self_id\s+TEXT\s+(?:NOT\s+NULL|PRIMARY\s+KEY))",
        rf"\1 {FK_CLAUSE}",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if new_sql == sql:
        raise RuntimeError(f"Could not inject FK into DDL for '{table}':\n{sql}")
    return new_sql


def _make_temp_ddl(sql: str, table: str, temp_name: str) -> str:
    return re.sub(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?" + re.escape(table),
        f"CREATE TABLE {temp_name}",
        sql,
        count=1,
        flags=re.IGNORECASE,
    )


def _migrate_table(cur: sqlite3.Cursor, table: str) -> None:
    original_ddl = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()[0]

    indexes = cur.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL",
        (table,),
    ).fetchall()

    triggers = cur.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND tbl_name=?",
        (table,),
    ).fetchall()

    new_ddl = _inject_fk(original_ddl, table)
    temp = f"_mig_tmp_{table}"

    for trig_name, _ in triggers:
        cur.execute(f"DROP TRIGGER IF EXISTS [{trig_name}]")

    cur.execute(f"DROP TABLE IF EXISTS [{temp}]")
    cur.execute(_make_temp_ddl(new_ddl, table, temp))

    cols = [f"[{r[1]}]" for r in cur.execute(f"PRAGMA table_info([{table}])").fetchall()]
    col_list = ", ".join(cols)
    cur.execute(f"INSERT INTO [{temp}] ({col_list}) SELECT {col_list} FROM [{table}]")

    cur.execute(f"DROP TABLE [{table}]")
    cur.execute(f"ALTER TABLE [{temp}] RENAME TO [{table}]")

    for (idx_sql,) in indexes:
        cur.execute(idx_sql)

    for _, trig_sql in triggers:
        cur.execute(trig_sql)

    row_count = cur.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
    print(f"  OK    {table} ({row_count} rows)")


def apply_migration(conn: sqlite3.Connection) -> None:
    """Apply the self_id FK migration.

    All changes are made within a single transaction.  The function manages
    PRAGMA foreign_keys itself (OFF during migration, ON after).
    """
    print("[migration] Starting add_self_id_fk migration...")
    cur = conn.cursor()

    if not cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='self_identity'"
    ).fetchone():
        raise RuntimeError("self_identity table not found — cannot add FK references")

    targets = _discover_target_tables(cur)
    print(f"[migration] {len(targets)} candidate tables: {targets}")

    _check_phantoms(cur, targets)
    print("[migration] No phantom self_id values found.")

    saved_isolation = conn.isolation_level
    conn.isolation_level = None
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("BEGIN")

    migrated: list[str] = []
    skipped: list[str] = []

    try:
        for table in targets:
            if _has_self_id_fk(cur, table):
                print(f"  SKIP  {table}: FK already exists")
                skipped.append(table)
                continue
            _migrate_table(cur, table)
            migrated.append(table)

        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        print("[migration] Rolled back due to error.")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.isolation_level = saved_isolation

    violations = cur.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"FK violations after migration: {violations}")

    print(f"[migration] Done: {len(migrated)} migrated, {len(skipped)} skipped.")
