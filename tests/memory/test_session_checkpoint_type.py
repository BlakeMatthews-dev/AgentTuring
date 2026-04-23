"""Tests for SessionCheckpoint dataclass (S1.3)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime

import pytest

from stronghold.types.memory import MemoryScope, SessionCheckpoint


def _make_checkpoint(**overrides: object) -> SessionCheckpoint:
    base: dict[str, object] = {
        "checkpoint_id": "cp-1",
        "session_id": "sess-1",
        "agent_id": "artificer",
        "user_id": "u-1",
        "org_id": "org-1",
        "team_id": "team-1",
        "scope": MemoryScope.SESSION,
        "branch": "feature/foo",
        "summary": "Wired the widget; tests pass.",
        "decisions": ("Use pathlib.", "Skip config reload."),
        "remaining": ("Document the flag.",),
        "notes": ("Reviewer pointed out edge case X.",),
        "failed_approaches": ("Tried regex matching — too fragile.",),
        "created_at": datetime(2026, 4, 23, 14, 30, 15, tzinfo=UTC),
        "source": "agent",
    }
    base.update(overrides)
    return SessionCheckpoint(**base)  # type: ignore[arg-type]


def test_frozen_dataclass_rejects_mutation() -> None:
    """AC 1: SessionCheckpoint is frozen."""
    cp = _make_checkpoint()
    with pytest.raises(FrozenInstanceError):
        cp.summary = "modified"  # type: ignore[misc]


def test_field_set_matches_shared_schema() -> None:
    """AC 1: field names and types match the shared schema in the plan."""
    names = {f.name for f in fields(SessionCheckpoint)}
    expected = {
        "checkpoint_id",
        "session_id",
        "agent_id",
        "user_id",
        "org_id",
        "team_id",
        "scope",
        "branch",
        "summary",
        "decisions",
        "remaining",
        "notes",
        "failed_approaches",
        "created_at",
        "source",
    }
    assert names == expected


def test_ordered_list_fields_are_tuples() -> None:
    """decisions/remaining/notes/failed_approaches are tuples (hashable, ordered)."""
    cp = _make_checkpoint()
    assert isinstance(cp.decisions, tuple)
    assert isinstance(cp.remaining, tuple)
    assert isinstance(cp.notes, tuple)
    assert isinstance(cp.failed_approaches, tuple)


def test_source_literal_values() -> None:
    """source only accepts the three documented values."""
    for src in ("agent", "claude_code", "manual"):
        cp = _make_checkpoint(source=src)
        assert cp.source == src
