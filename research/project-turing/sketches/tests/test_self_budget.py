"""Tests for turing.self_budget — AC-37.1..13.

Covers: fresh() defaults, consume/refund lifecycle, context binding,
category independence, exceeded counters, nested-context overwrite.
"""

from __future__ import annotations

import pytest

import turing.self_budget as _sb_mod
from turing.self_budget import (
    RequestWriteBudget,
    SelfWriteBudgetExceeded,
    consume,
    get_budget,
    get_exceeded_counts,
    refund,
    use_budget,
)


@pytest.fixture(autouse=True)
def _isolate_exceeded_counts():
    _sb_mod._BUDGET_EXCEEDED_COUNTS.clear()
    yield
    _sb_mod._BUDGET_EXCEEDED_COUNTS.clear()


class TestFreshDefaults:
    def test_fresh_returns_default_values(self):
        b = RequestWriteBudget.fresh()
        assert b.new_nodes == 3
        assert b.contributors == 5
        assert b.todo_writes == 2
        assert b.personality_claims == 3


class TestConsume:
    def test_decrements_new_nodes_to_zero(self):
        b = RequestWriteBudget.fresh()
        with use_budget(b):
            consume("new_nodes")
            assert b.new_nodes == 2
            consume("new_nodes")
            assert b.new_nodes == 1
            consume("new_nodes")
            assert b.new_nodes == 0

    def test_at_zero_raises_exceeded_with_category_and_remaining(self):
        b = RequestWriteBudget.fresh()
        with use_budget(b):
            for _ in range(3):
                consume("new_nodes")
            with pytest.raises(SelfWriteBudgetExceeded) as exc_info:
                consume("new_nodes")
            assert exc_info.value.category == "new_nodes"
            assert exc_info.value.remaining == 0

    def test_outside_context_is_noop(self):
        assert get_budget() is None
        consume("new_nodes")
        consume("contributors")
        assert get_budget() is None


class TestRefund:
    def test_restores_consumed_counter(self):
        b = RequestWriteBudget.fresh()
        with use_budget(b):
            consume("new_nodes")
            assert b.new_nodes == 2
            refund("new_nodes")
            assert b.new_nodes == 3

    def test_refund_outside_context_is_noop(self):
        refund("new_nodes")


class TestContextBinding:
    def test_binds_inside_unbinds_outside(self):
        assert get_budget() is None
        b = RequestWriteBudget.fresh()
        with use_budget(b) as bound:
            assert bound is b
            assert get_budget() is b
        assert get_budget() is None


class TestCategoryIndependence:
    def test_different_categories_dont_interfere(self):
        b = RequestWriteBudget.fresh()
        with use_budget(b):
            consume("new_nodes")
            consume("new_nodes")
            assert b.new_nodes == 1
            assert b.contributors == 5
            consume("contributors")
            assert b.contributors == 4
            assert b.new_nodes == 1
            assert b.todo_writes == 2
            assert b.personality_claims == 3


class TestExceededCounter:
    def test_increments_on_each_blocked_consume(self):
        b = RequestWriteBudget(new_nodes=1)
        with use_budget(b):
            consume("new_nodes")
            for i in range(3):
                with pytest.raises(SelfWriteBudgetExceeded):
                    consume("new_nodes")
                assert get_exceeded_counts()["new_nodes"] == i + 1

    def test_separate_categories_tracked_separately(self):
        b = RequestWriteBudget(new_nodes=0, personality_claims=0)
        with use_budget(b):
            with pytest.raises(SelfWriteBudgetExceeded):
                consume("new_nodes")
            with pytest.raises(SelfWriteBudgetExceeded):
                consume("personality_claims")
            counts = get_exceeded_counts()
            assert counts["new_nodes"] == 1
            assert counts["personality_claims"] == 1


class TestNestedContexts:
    def test_second_use_budget_overwrites_inside(self):
        outer = RequestWriteBudget.fresh()
        inner = RequestWriteBudget(new_nodes=0, contributors=0, todo_writes=0, personality_claims=0)
        with use_budget(outer):
            assert get_budget() is outer
            with use_budget(inner):
                assert get_budget() is inner
            assert get_budget() is outer
        assert get_budget() is None
