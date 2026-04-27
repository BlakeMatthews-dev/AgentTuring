"""Tests for turing.self_personality_drift — AC-40.1..14.

Covers: drift_clip budget logic, weekly/quarterly_delta with mock repos.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_personality_drift import (
    FACET_QUARTERLY_DRIFT_MAX,
    FACET_WEEKLY_DRIFT_MAX,
    drift_clip,
    quarterly_delta,
    weekly_delta,
)


class _FakeRevision:
    def __init__(self, deltas_by_facet: dict[str, float]):
        self.deltas_by_facet = deltas_by_facet


class _FakeRepo:
    def __init__(self, revisions: list[_FakeRevision] | None = None):
        self._revisions = revisions or []

    def list_revisions_since(self, self_id: str, cutoff: datetime):
        return self._revisions


class TestDriftClip:
    def test_within_both_budgets_unchanged(self):
        result = drift_clip(0.3, 0.1, 0.5)
        assert result == pytest.approx(0.3)

    def test_exceeds_weekly_only_clips_to_weekly_headroom(self):
        result = drift_clip(0.3, 0.4, 0.5)
        assert result == pytest.approx(0.1)

    def test_exceeds_quarterly_only_clips_to_quarterly_headroom(self):
        result = drift_clip(0.3, 0.1, 1.4)
        assert result == pytest.approx(0.1)

    def test_both_exceeded_returns_zero(self):
        result = drift_clip(0.5, 0.6, 1.6)
        assert result == 0.0

    def test_negative_delta_clips_correctly(self):
        result = drift_clip(-0.3, 0.1, 0.5)
        assert result == pytest.approx(-0.3)

    def test_negative_delta_exceeds_budget_clips(self):
        result = drift_clip(-0.5, 0.4, 0.5)
        assert result == pytest.approx(-0.1)

    def test_near_zero_headroom_returns_tiny_value(self):
        result = drift_clip(0.01, 0.499, 0.5)
        assert 0.0 < result <= 0.01
        assert result == pytest.approx(0.001)


class TestWeeklyDelta:
    def test_no_revisions_returns_zero(self):
        repo = _FakeRepo(revisions=[])
        now = datetime.now(UTC)
        assert weekly_delta(repo, "s1", "creativity", now) == 0.0

    def test_sums_abs_deltas_for_matching_facet(self):
        repo = _FakeRepo(
            revisions=[
                _FakeRevision({"creativity": 0.1}),
                _FakeRevision({"creativity": -0.2}),
                _FakeRevision({"openness": 0.3}),
            ]
        )
        now = datetime.now(UTC)
        result = weekly_delta(repo, "s1", "creativity", now)
        assert result == pytest.approx(0.3)


class TestQuarterlyDelta:
    def test_no_revisions_returns_zero(self):
        repo = _FakeRepo(revisions=[])
        now = datetime.now(UTC)
        assert quarterly_delta(repo, "s1", "creativity", now) == 0.0

    def test_sums_abs_deltas_for_matching_facet(self):
        repo = _FakeRepo(
            revisions=[
                _FakeRevision({"creativity": 0.4}),
                _FakeRevision({"creativity": 0.1}),
            ]
        )
        now = datetime.now(UTC)
        result = quarterly_delta(repo, "s1", "creativity", now)
        assert result == pytest.approx(0.5)
