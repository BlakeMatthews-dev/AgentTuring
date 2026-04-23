"""Tests for turing/working_memory.py."""

from __future__ import annotations

import pytest

from turing.repo import Repo
from turing.self_identity import bootstrap_self_id
from turing.working_memory import (
    WORKING_MEMORY_MAX_CONTENT_LEN,
    WORKING_MEMORY_MAX_ENTRIES,
    WorkingMemory,
)


def test_add_and_list(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    eid = wm.add(self_id, "remember this")
    entries = wm.entries(self_id)
    assert len(entries) == 1
    assert entries[0].entry_id == eid
    assert entries[0].content == "remember this"
    assert entries[0].priority == 0.5


def test_entries_sorted_by_priority_desc(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    wm.add(self_id, "low", priority=0.2)
    wm.add(self_id, "high", priority=0.9)
    wm.add(self_id, "mid", priority=0.5)
    entries = wm.entries(self_id)
    assert [e.content for e in entries] == ["high", "mid", "low"]


def test_content_truncated_to_max(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    long_content = "x" * (WORKING_MEMORY_MAX_CONTENT_LEN * 3)
    wm.add(self_id, long_content)
    stored = wm.entries(self_id)[0].content
    assert len(stored) == WORKING_MEMORY_MAX_CONTENT_LEN


def test_empty_content_raises(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    with pytest.raises(ValueError, match="empty"):
        wm.add(self_id, "   ")


def test_priority_out_of_range_raises(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    with pytest.raises(ValueError, match="priority"):
        wm.add(self_id, "x", priority=1.5)


def test_capacity_eviction(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    # Fill past capacity with varied priorities.
    for i in range(WORKING_MEMORY_MAX_ENTRIES + 5):
        priority = 0.9 if i < WORKING_MEMORY_MAX_ENTRIES else 0.1
        wm.add(self_id, f"entry {i}", priority=priority)
    entries = wm.entries(self_id)
    assert len(entries) == WORKING_MEMORY_MAX_ENTRIES


def test_capacity_evicts_lowest_priority_first(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    # Add one low and N-1 high priority, then one more high; low should evict.
    low = wm.add(self_id, "low priority", priority=0.1)
    for i in range(WORKING_MEMORY_MAX_ENTRIES - 1):
        wm.add(self_id, f"keeper {i}", priority=0.9)
    wm.add(self_id, "new high", priority=0.9)
    ids = {e.entry_id for e in wm.entries(self_id)}
    assert low not in ids


def test_remove(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    eid = wm.add(self_id, "to remove")
    removed = wm.remove(self_id, eid)
    assert removed is True
    assert wm.entries(self_id) == []


def test_remove_unknown_returns_false(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    removed = wm.remove(self_id, "nope")
    assert removed is False


def test_update_priority(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    eid = wm.add(self_id, "x", priority=0.3)
    assert wm.update_priority(self_id, eid, priority=0.8) is True
    entry = wm.entries(self_id)[0]
    assert entry.priority == 0.8


def test_clear(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    for i in range(3):
        wm.add(self_id, f"x{i}")
    cleared = wm.clear(self_id)
    assert cleared == 3
    assert wm.entries(self_id) == []


def test_render_empty(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    rendered = wm.render(self_id)
    assert "empty" in rendered.lower()


def test_render_non_empty_marks_high_priority(repo: Repo, self_id: str) -> None:
    wm = WorkingMemory(repo.conn)
    wm.add(self_id, "star me", priority=0.9)
    wm.add(self_id, "regular", priority=0.4)
    rendered = wm.render(self_id)
    assert "★ star me" in rendered
    assert "· regular" in rendered


def test_entries_isolated_by_self_id(repo: Repo) -> None:
    wm = WorkingMemory(repo.conn)
    first = bootstrap_self_id(repo.conn)
    # Force a second identity row.
    repo.conn.execute(
        "UPDATE self_identity SET archived_at = ? WHERE self_id = ?",
        ("archived", first),
    )
    second = bootstrap_self_id(repo.conn)
    wm.add(first, "mine-A")
    wm.add(second, "mine-B")
    assert [e.content for e in wm.entries(first)] == ["mine-A"]
    assert [e.content for e in wm.entries(second)] == ["mine-B"]
