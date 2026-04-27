"""Tests for specs/revision-compaction.md: AC-53.*."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from turing.self_compaction import (
    _keep_set,
    compact_todo_revisions,
    get_compaction_counts,
)


NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


@dataclass
class FakeRevision:
    node_id: str
    revision_num: int


class FakeRepo:
    def __init__(self, todo_ids_over_floor: dict[str, list[FakeRevision]] | None = None):
        self.todo_ids_over_floor: dict[str, list[FakeRevision]] = todo_ids_over_floor or {}
        self.compacted: list[tuple[str, datetime]] = []

    def list_todo_ids_with_revisions(self, self_id: str, min_revisions: int = 11) -> list[str]:
        return [tid for tid, revs in self.todo_ids_over_floor.items() if len(revs) >= min_revisions]

    def list_todo_revisions(self, todo_id: str) -> list[FakeRevision]:
        return self.todo_ids_over_floor.get(todo_id, [])

    def compact_todo_revision(self, node_id: str, now: datetime) -> None:
        self.compacted.append((node_id, now))


@pytest.fixture(autouse=True)
def _reset_compaction_counts():
    from turing import self_compaction as mod

    mod._COMPACTED_COUNTS["todo"] = 0
    mod._COMPACTED_COUNTS["answer"] = 0
    yield


def test_ac_53_1_keep_set_5() -> None:
    assert _keep_set(5) == {1, 2, 3, 4, 5}


def test_ac_53_2_keep_set_10() -> None:
    assert _keep_set(10) == set(range(1, 11))


def test_ac_53_3_keep_set_11() -> None:
    assert _keep_set(11) == {1, 10, 11}


def test_ac_53_4_keep_set_100() -> None:
    expected = {1, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
    assert _keep_set(100) == expected
    assert len(_keep_set(100)) == 11


def test_ac_53_5_keep_set_1() -> None:
    assert _keep_set(1) == {1}


def test_ac_53_6_compact_no_todos_over_floor() -> None:
    repo = FakeRepo(todo_ids_over_floor={"t1": [FakeRevision("r1", i) for i in range(1, 11)]})
    assert compact_todo_revisions(repo, "self-1", NOW) == 0
    assert repo.compacted == []


def test_ac_53_7_compact_one_todo_over_floor() -> None:
    revs = [FakeRevision(f"r{i}", i) for i in range(1, 16)]
    repo = FakeRepo(todo_ids_over_floor={"t1": revs})
    result = compact_todo_revisions(repo, "self-1", NOW)
    keep = _keep_set(15)
    expected_compacted = [f"r{i}" for i in range(1, 16) if i not in keep]
    assert result == len(expected_compacted)
    assert [c[0] for c in repo.compacted] == expected_compacted
