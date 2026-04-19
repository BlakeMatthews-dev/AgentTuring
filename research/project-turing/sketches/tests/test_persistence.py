"""Tests for specs/persistence.md: AC-8.1, AC-8.2, AC-8.3, AC-8.6, AC-8.7."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest

from turing.repo import Repo
from turing.self_identity import archive_and_mint_new, bootstrap_self_id
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def test_ac_8_1_durable_memory_has_no_deleted_column(repo: Repo) -> None:
    cur = repo.conn.execute("PRAGMA table_info(durable_memory)")
    column_names = {row[1] for row in cur.fetchall()}
    assert "deleted" not in column_names


def test_ac_8_2_durable_memory_delete_blocked(repo: Repo, self_id: str) -> None:
    regret = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="c",
        weight=0.7,
        intent_at_time="i",
        immutable=True,
    )
    repo.insert(regret)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repo.conn.execute(
            "DELETE FROM durable_memory WHERE memory_id = ?", (regret.memory_id,)
        )


def test_ac_8_3_restart_preserves_durable_memories() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "turing.db"

        repo1 = Repo(db_path)
        sid = bootstrap_self_id(repo1.conn)
        regret = EpisodicMemory(
            memory_id=str(uuid4()),
            self_id=sid,
            tier=MemoryTier.REGRET,
            source=SourceKind.I_DID,
            content="durable",
            weight=0.7,
            intent_at_time="i",
            immutable=True,
        )
        repo1.insert(regret)
        repo1.close()

        repo2 = Repo(db_path)
        reloaded = repo2.get(regret.memory_id)
        assert reloaded is not None
        assert reloaded.content == "durable"
        assert reloaded.tier == MemoryTier.REGRET
        repo2.close()


def test_ac_8_6_self_id_mint_once_then_read() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "turing.db"

        repo1 = Repo(db_path)
        sid_1 = bootstrap_self_id(repo1.conn)
        repo1.close()

        repo2 = Repo(db_path)
        sid_2 = bootstrap_self_id(repo2.conn)
        repo2.close()

        assert sid_1 == sid_2


def test_ac_8_7_archive_and_mint_preserves_old() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "turing.db"
        repo1 = Repo(db_path)

        original = bootstrap_self_id(repo1.conn)
        new = archive_and_mint_new(repo1.conn, reason="clean-slate")
        assert new != original

        cur = repo1.conn.execute(
            "SELECT COUNT(*) FROM self_identity WHERE self_id = ?", (original,)
        )
        assert cur.fetchone()[0] == 1

        cur = repo1.conn.execute(
            "SELECT archived_at FROM self_identity WHERE self_id = ?", (original,)
        )
        row = cur.fetchone()
        assert row[0] is not None
        repo1.close()


def test_wisdom_writes_deferred(repo: Repo, self_id: str) -> None:
    wisdom = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.WISDOM,
        source=SourceKind.I_DID,
        content="I am the kind of pipeline that routes carefully",
        weight=0.95,
        intent_at_time="self-description",
        immutable=True,
    )
    from turing.repo import WisdomDeferred

    with pytest.raises(WisdomDeferred):
        repo.insert(wisdom)
