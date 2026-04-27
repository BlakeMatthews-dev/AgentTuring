"""Tests for specs/repo-self-id-enforcement.md: AC-47.4..9 (FK migration)."""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

from turing.repo import Repo
from turing.self_identity import bootstrap_self_id


_MIG_DIR = str(Path(__file__).resolve().parent.parent / "turing" / "schema_migrations")


@pytest.fixture
def apply_migration():
    if _MIG_DIR not in sys.path:
        sys.path.insert(0, _MIG_DIR)
    mod = importlib.import_module("add_self_id_fk")
    return mod.apply_migration


def _table_has_fk(conn: sqlite3.Connection, table: str) -> bool:
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    return any(row[3] == "self_id" and row[2] == "self_identity" for row in rows)


class TestFKMigration:
    def test_migration_adds_fk_to_facets(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            assert _table_has_fk(r.conn, "self_personality_facets")
        finally:
            r.close()

    def test_migration_adds_fk_to_passions(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            assert _table_has_fk(r.conn, "self_passions")
        finally:
            r.close()

    def test_migration_adds_fk_to_todos(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            assert _table_has_fk(r.conn, "self_todos")
        finally:
            r.close()

    def test_migration_adds_fk_to_working_memory(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            assert _table_has_fk(r.conn, "working_memory")
        finally:
            r.close()

    def test_migration_idempotent(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            apply_migration(r.conn)
            assert _table_has_fk(r.conn, "self_personality_facets")
        finally:
            r.close()

    def test_insert_with_phantom_self_id_raises(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            with pytest.raises(sqlite3.IntegrityError):
                r.conn.execute(
                    "INSERT INTO self_passions (node_id, self_id, text, strength, rank, first_noticed_at) "
                    "VALUES ('p:1', 'phantom-id', 'x', 0.5, 0, '2026-01-01T00:00:00')"
                )
                r.conn.commit()
        finally:
            r.close()

    def test_pragma_foreign_keys_on(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            result = r.conn.execute("PRAGMA foreign_keys").fetchone()
            assert result[0] == 1
        finally:
            r.close()

    def test_delete_self_with_dependents_raises(self, apply_migration) -> None:
        r = Repo(None)
        try:
            apply_migration(r.conn)
            sid = bootstrap_self_id(r.conn)
            now = "2026-01-01T00:00:00"
            r.conn.execute(
                "INSERT INTO self_passions "
                "(node_id, self_id, text, strength, rank, first_noticed_at, created_at, updated_at) "
                "VALUES ('p:1', ?, 'x', 0.5, 0, ?, ?, ?)",
                (sid, now, now, now),
            )
            r.conn.commit()
            with pytest.raises(sqlite3.IntegrityError):
                r.conn.execute("DELETE FROM self_identity WHERE self_id = ?", (sid,))
                r.conn.commit()
        finally:
            r.close()
