"""Tests for specs/retrieval-contributor-gc.md: AC-50.*."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_activation_gc import (
    GC_READ_THRESHOLD,
    gc_expired_retrieval_contributors,
    gc_opportunistic,
    get_gc_counts,
)


class FakeRepo:
    def __init__(
        self,
        expired_deleted: int = 0,
        target_expired_deleted: int = 0,
        active_count: int = 0,
    ):
        self.expired_deleted = expired_deleted
        self.target_expired_deleted = target_expired_deleted
        self.active_count = active_count
        self.calls: list[tuple[str, tuple, dict]] = []

    def delete_expired_retrieval_contributors(self, now: datetime) -> int:
        self.calls.append(("delete_expired", (now,), {}))
        return self.expired_deleted

    def delete_expired_retrieval_contributors_for_target(
        self, target_node_id: str, now: datetime
    ) -> int:
        self.calls.append(("delete_expired_for_target", (target_node_id, now), {}))
        return self.target_expired_deleted

    def count_active_retrieval_contributors(self, target_node_id: str, now: datetime) -> int:
        self.calls.append(("count_active", (target_node_id, now), {}))
        return self.active_count


@pytest.fixture(autouse=True)
def _reset_gc_counts():
    from turing import self_activation_gc as mod

    mod._GC_DELETED["sweep"] = 0
    mod._GC_DELETED["opportunistic"] = 0
    yield


NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def test_ac_50_1_gc_expired_returns_deleted_count() -> None:
    repo = FakeRepo(expired_deleted=7)
    assert gc_expired_retrieval_contributors(repo, NOW) == 7


def test_ac_50_2_gc_expired_increments_sweep_counter() -> None:
    repo = FakeRepo(expired_deleted=3)
    gc_expired_retrieval_contributors(repo, NOW)
    gc_expired_retrieval_contributors(repo, NOW)
    assert get_gc_counts()["sweep"] == 6


def test_ac_50_3_gc_opportunistic_below_threshold_no_delete() -> None:
    repo = FakeRepo(active_count=50, target_expired_deleted=99)
    result = gc_opportunistic(repo, "node-1", NOW)
    assert result == 0
    assert all(c[0] != "delete_expired_for_target" for c in repo.calls)


def test_ac_50_4_gc_opportunistic_above_threshold_deletes() -> None:
    repo = FakeRepo(active_count=200, target_expired_deleted=15)
    result = gc_opportunistic(repo, "node-1", NOW)
    assert result == 15
    assert get_gc_counts()["opportunistic"] == 15


def test_ac_50_5_get_gc_counts_returns_copy() -> None:
    counts = get_gc_counts()
    counts["sweep"] = 9999
    assert get_gc_counts()["sweep"] == 0


def test_ac_50_6_none_now_defaults_to_utc_now() -> None:
    repo = FakeRepo(expired_deleted=1)
    before = datetime.now(UTC)
    gc_expired_retrieval_contributors(repo, now=None)
    after = datetime.now(UTC)
    passed_now = repo.calls[0][1][0]
    assert before <= passed_now <= after
