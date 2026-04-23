"""Tests for BuildersLogger.

Spec: XP tracking, builder action logging, learning promotion events.
AC: log_builder_action accumulates XP, get_actions filters by name/time/limit,
    get_xp_totals returns per-builder totals, get_stats aggregates,
    clear resets all state.
Edge cases: limit=0 returns all, since filters correctly, multiple builders,
            clear empties everything.
Contracts: log_builder_action is void, get_actions returns list[BuilderAction],
           get_xp_totals returns dict[str,int].
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from stronghold.builders.logger import BuildersLogger


class TestLogBuilderAction:
    def test_accumulates_xp(self) -> None:
        log = BuildersLogger()
        log.log_builder_action("mason", "build", "built a wall", xp_earned=10)
        log.log_builder_action("mason", "build", "built a tower", xp_earned=20)
        assert log.get_xp_totals() == {"mason": 30}

    def test_multiple_builders(self) -> None:
        log = BuildersLogger()
        log.log_builder_action("mason", "build", "wall", xp_earned=10)
        log.log_builder_action("archie", "scaffold", "protocol", xp_earned=5)
        totals = log.get_xp_totals()
        assert totals == {"mason": 10, "archie": 5}

    def test_zero_xp(self) -> None:
        log = BuildersLogger()
        log.log_builder_action("mason", "plan", "read specs", xp_earned=0)
        assert log.get_xp_totals() == {"mason": 0}


class TestGetActions:
    def test_filter_by_builder_name(self) -> None:
        log = BuildersLogger()
        log.log_builder_action("mason", "build", "a")
        log.log_builder_action("archie", "scaffold", "b")
        actions = log.get_actions(builder_name="mason")
        assert len(actions) == 1
        assert actions[0].builder_name == "mason"

    def test_filter_by_since(self) -> None:
        log = BuildersLogger()
        log.log_builder_action("mason", "build", "old")
        cutoff = datetime.now(UTC) + timedelta(seconds=1)
        log.log_builder_action("mason", "build", "new")
        actions = log.get_actions(since=cutoff)
        assert len(actions) == 1
        assert actions[0].description == "new"

    def test_limit(self) -> None:
        log = BuildersLogger()
        for i in range(10):
            log.log_builder_action("mason", "build", f"item-{i}")
        actions = log.get_actions(limit=3)
        assert len(actions) == 3


class TestGetLearningEvents:
    def test_records_and_retrieves(self) -> None:
        log = BuildersLogger()
        log.log_learning_promotion("l1", "frank", "mason", "correct pattern", 0.9)
        events = log.get_learning_events()
        assert len(events) == 1
        assert events[0].learning_id == "l1"
        assert events[0].confidence == 0.9

    def test_filter_by_since(self) -> None:
        log = BuildersLogger()
        log.log_learning_promotion("l1", "a", "b", "r", 0.5)
        cutoff = datetime.now(UTC) + timedelta(seconds=1)
        log.log_learning_promotion("l2", "a", "b", "r", 0.7)
        events = log.get_learning_events(since=cutoff)
        assert len(events) == 1
        assert events[0].learning_id == "l2"


class TestGetStats:
    def test_empty_returns_zeroes(self) -> None:
        log = BuildersLogger()
        stats = log.get_stats()
        assert stats["total_actions"] == 0
        assert stats["total_xp"] == 0

    def test_with_data(self) -> None:
        log = BuildersLogger()
        log.log_builder_action("mason", "build", "wall", xp_earned=10)
        stats = log.get_stats()
        assert stats["total_actions"] == 1
        assert stats["total_xp"] == 10
        assert "mason" in stats["actions_by_builder"]


class TestClear:
    def test_clear_empties_all(self) -> None:
        log = BuildersLogger()
        log.log_builder_action("mason", "build", "wall", xp_earned=10)
        log.log_learning_promotion("l1", "a", "b", "r", 0.5)
        log.clear()
        assert log.get_actions() == []
        assert log.get_xp_totals() == {}
        assert log.get_learning_events() == []
