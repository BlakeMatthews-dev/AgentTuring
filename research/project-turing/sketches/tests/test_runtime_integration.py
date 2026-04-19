"""End-to-end runtime integration — FakeProvider, RealReactor, brief run."""

from __future__ import annotations

import tempfile
import threading
from datetime import timedelta
from pathlib import Path

from turing.repo import Repo
from turing.runtime.config import RuntimeConfig
from turing.runtime.main import build_and_run
from turing.types import MemoryTier, SourceKind


def test_runtime_short_run_accumulates_session_markers(tmp_path: Path) -> None:
    """A 2-second run with FakeProvider emits daydream session markers."""
    db_path = tmp_path / "turing.db"

    rc = build_and_run(
        [
            "--tick-rate",
            "100",
            "--duration",
            "2",
            "--use-fake-provider",
            "--db",
            str(db_path),
            "--log-level",
            "ERROR",
        ]
    )
    assert rc == 0

    repo = Repo(str(db_path))
    markers = list(
        repo.find(
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
        )
    )
    assert markers, "expected at least one OBSERVATION/I_DID session marker"
    assert any("daydream session" in m.content for m in markers)
    repo.close()


def test_runtime_self_id_persists_across_runs(tmp_path: Path) -> None:
    db_path = tmp_path / "turing.db"

    build_and_run(
        ["--tick-rate", "100", "--duration", "1", "--db", str(db_path),
         "--use-fake-provider", "--log-level", "ERROR"]
    )
    repo = Repo(str(db_path))
    first_id = repo.conn.execute(
        "SELECT self_id FROM self_identity WHERE archived_at IS NULL"
    ).fetchone()[0]
    repo.close()

    build_and_run(
        ["--tick-rate", "100", "--duration", "1", "--db", str(db_path),
         "--use-fake-provider", "--log-level", "ERROR"]
    )
    repo = Repo(str(db_path))
    second_id = repo.conn.execute(
        "SELECT self_id FROM self_identity WHERE archived_at IS NULL"
    ).fetchone()[0]
    repo.close()

    assert first_id == second_id
