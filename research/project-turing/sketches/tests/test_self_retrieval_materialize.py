"""Tests for specs/retrieval-contributor-cap.md: AC-38.1..15."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_retrieval_materialize import (
    K_RETRIEVAL_CONTRIBUTORS,
    RETRIEVAL_SUM_CAP,
    RETRIEVAL_WEIGHT_COEFFICIENT,
    _DROP_COUNTS,
    get_drop_counts,
    materialize_retrieval_contributors,
)


@pytest.fixture(autouse=True)
def _reset_drop_counts():
    _DROP_COUNTS["count_cap"] = 0
    _DROP_COUNTS["sum_cap"] = 0
    yield
    _DROP_COUNTS["count_cap"] = 0
    _DROP_COUNTS["sum_cap"] = 0


def _call(srepo, self_id, per_target, new_id):
    return materialize_retrieval_contributors(srepo, self_id, datetime.now(UTC), per_target, new_id)


class TestConstants:
    def test_k_retrieval_contributors(self):
        assert K_RETRIEVAL_CONTRIBUTORS == 8

    def test_retrieval_sum_cap(self):
        assert RETRIEVAL_SUM_CAP == 1.0

    def test_retrieval_weight_coefficient(self):
        assert RETRIEVAL_WEIGHT_COEFFICIENT == 0.4


class TestMaterializeRetrievalContributors:
    def test_ac38_1_empty_per_target_returns_empty(self, srepo, bootstrapped_id, new_id):
        result = _call(srepo, bootstrapped_id, {}, new_id)
        assert result == {}

    def test_ac38_2_single_target_3_hits(self, srepo, bootstrapped_id, new_id):
        per_target = {"t1": {"s1": 0.5, "s2": 0.3, "s3": 0.1}}
        result = _call(srepo, bootstrapped_id, per_target, new_id)
        assert result == {"t1": 3}
        rows = srepo.active_contributors_for("t1", datetime.now(UTC))
        assert len(rows) == 3

    def test_ac38_3_count_cap_at_k(self, srepo, bootstrapped_id, new_id):
        hits = {f"s{i}": 0.01 * (20 - i) for i in range(20)}
        per_target = {"t1": hits}
        result = _call(srepo, bootstrapped_id, per_target, new_id)
        assert result["t1"] == K_RETRIEVAL_CONTRIBUTORS
        rows = srepo.active_contributors_for("t1", datetime.now(UTC))
        assert len(rows) == K_RETRIEVAL_CONTRIBUTORS

    def test_ac38_4_sum_cap_truncates_high_similarity(self, srepo, bootstrapped_id, new_id):
        per_target = {"t1": {"s1": 0.99, "s2": 0.99, "s3": 0.99}}
        result = _call(srepo, bootstrapped_id, per_target, new_id)
        assert result["t1"] == 2
        rows = srepo.active_contributors_for("t1", datetime.now(UTC))
        assert len(rows) == 2
        expected_weight = 0.99 * RETRIEVAL_WEIGHT_COEFFICIENT
        for row in rows:
            assert abs(row.weight - expected_weight) < 1e-9

    def test_ac38_5_low_sim_hits_count_cap_not_sum(self, srepo, bootstrapped_id, new_id):
        hits = {f"s{i}": 0.05 for i in range(50)}
        per_target = {"t1": hits}
        result = _call(srepo, bootstrapped_id, per_target, new_id)
        assert result["t1"] == K_RETRIEVAL_CONTRIBUTORS
        rows = srepo.active_contributors_for("t1", datetime.now(UTC))
        assert len(rows) == K_RETRIEVAL_CONTRIBUTORS

    def test_ac38_6_clamped_oversized_similarity(self, srepo, bootstrapped_id, new_id):
        per_target = {"t1": {"s1": 10.0}}
        result = _call(srepo, bootstrapped_id, per_target, new_id)
        assert result["t1"] == 1
        rows = srepo.active_contributors_for("t1", datetime.now(UTC))
        assert len(rows) == 1
        assert abs(rows[0].weight - RETRIEVAL_WEIGHT_COEFFICIENT) < 1e-9

    def test_ac38_7_zero_hits_target(self, srepo, bootstrapped_id, new_id):
        per_target = {"t1": {}}
        result = _call(srepo, bootstrapped_id, per_target, new_id)
        assert result["t1"] == 0
        rows = srepo.active_contributors_for("t1", datetime.now(UTC))
        assert len(rows) == 0

    def test_ac38_8_drop_counts_tracked(self, srepo, bootstrapped_id, new_id):
        hits = {f"s{i}": 0.01 * (20 - i) for i in range(20)}
        _call(srepo, bootstrapped_id, {"t1": hits}, new_id)
        assert get_drop_counts()["count_cap"] == 1
        assert get_drop_counts()["sum_cap"] == 0

        _DROP_COUNTS["count_cap"] = 0
        _DROP_COUNTS["sum_cap"] = 0

        _call(srepo, bootstrapped_id, {"t1": {"s1": 0.99, "s2": 0.99, "s3": 0.99}}, new_id)
        assert get_drop_counts()["count_cap"] == 0
        assert get_drop_counts()["sum_cap"] == 1

    def test_ac38_9_independent_target_caps(self, srepo, bootstrapped_id, new_id):
        per_target = {
            "t1": {"s1": 0.99, "s2": 0.99, "s3": 0.99},
            "t2": {"s4": 0.5, "s5": 0.3},
        }
        result = _call(srepo, bootstrapped_id, per_target, new_id)
        assert result["t1"] == 2
        assert result["t2"] == 2
        rows_t1 = srepo.active_contributors_for("t1", datetime.now(UTC))
        rows_t2 = srepo.active_contributors_for("t2", datetime.now(UTC))
        assert len(rows_t1) == 2
        assert len(rows_t2) == 2
