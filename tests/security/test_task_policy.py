"""Tests for TaskAcceptancePolicy (ADR-K8S-030)."""

from __future__ import annotations

import math

from stronghold.security.task_policy import (
    InMemoryTaskAcceptancePolicy,
    TaskAcceptancePolicy,
)


def test_default_allows_task_creation() -> None:
    p = InMemoryTaskAcceptancePolicy()
    assert p.check_task_creation("alice", "acme", "artificer") is True


def test_deny_agent_blocks() -> None:
    p = InMemoryTaskAcceptancePolicy()
    p.deny_agent("mallory", "acme", "forge")
    assert p.check_task_creation("mallory", "acme", "forge") is False
    assert p.check_task_creation("alice", "acme", "forge") is True


def test_budget_within_limits() -> None:
    p = InMemoryTaskAcceptancePolicy()
    assert p.check_budget("alice", "acme", "P2", token_budget=10_000) is True
    assert p.check_budget("alice", "acme", "P2", cost_budget=5.0) is True
    assert p.check_budget("alice", "acme", "P2", wall_clock_seconds=1800) is True


def test_budget_exceeds_token_limit() -> None:
    p = InMemoryTaskAcceptancePolicy()
    # P0 max_tokens is scaled: 200_000 / log2(2) = 141,845
    max_p0_tokens = p._calculate_token_budget("P0")
    assert p.check_budget("alice", "acme", "P0", token_budget=max_p0_tokens + 1) is False


def test_budget_exceeds_cost_limit() -> None:
    p = InMemoryTaskAcceptancePolicy()
    # P1 default max_cost is 5.0
    assert p.check_budget("alice", "acme", "P1", cost_budget=50.0) is False


def test_budget_exceeds_wall_clock() -> None:
    p = InMemoryTaskAcceptancePolicy()
    # P0 default max_seconds is 300
    assert p.check_budget("alice", "acme", "P0", wall_clock_seconds=600) is False


def test_budget_none_values_pass() -> None:
    p = InMemoryTaskAcceptancePolicy()
    assert p.check_budget("alice", "acme", "P2") is True


def test_budget_unknown_tier_denied() -> None:
    """Unknown tiers are denied to prevent bypass via invalid tier names."""
    p = InMemoryTaskAcceptancePolicy()
    assert p.check_budget("alice", "acme", "P99", token_budget=999_999) is False
    assert p.check_budget("alice", "acme", "", token_budget=1) is False
    assert p.check_budget("alice", "acme", "'; DROP TABLE --", token_budget=1) is False


def test_custom_budget_limit() -> None:
    p = InMemoryTaskAcceptancePolicy()
    # Set P5 base tokens to 100
    p.set_budget_limit("P5", max_tokens=100)
    # P5 scaled: 100 / log2(7) = 100 / 2.83 = 35.36
    max_p5_tokens = p._calculate_token_budget("P5")
    assert p.check_budget("alice", "acme", "P5", token_budget=max_p5_tokens - 1) is True
    assert p.check_budget("alice", "acme", "P5", token_budget=max_p5_tokens + 1) is False


def test_protocol_compliance() -> None:
    p = InMemoryTaskAcceptancePolicy()
    assert isinstance(p, TaskAcceptancePolicy)


def test_all_tiers_have_defaults() -> None:
    p = InMemoryTaskAcceptancePolicy()
    for tier in ("P0", "P1", "P2", "P3", "P4", "P5"):
        # All tiers should have default limits
        assert p.check_budget("alice", "acme", tier, token_budget=1) is True


def test_cost_at_exact_limit_passes() -> None:
    p = InMemoryTaskAcceptancePolicy()
    p.set_budget_limit("P1", max_cost=5.0)
    assert p.check_budget("alice", "acme", "P1", cost_budget=5.0) is True
    assert p.check_budget("alice", "acme", "P1", cost_budget=5.01) is False


def test_wall_clock_at_exact_limit_passes() -> None:
    p = InMemoryTaskAcceptancePolicy()
    p.set_budget_limit("P0", max_seconds=300)
    assert p.check_budget("alice", "acme", "P0", wall_clock_seconds=300) is True
    assert p.check_budget("alice", "acme", "P0", wall_clock_seconds=301) is False


def test_multi_dimension_budget_fail() -> None:
    p = InMemoryTaskAcceptancePolicy()
    p.set_budget_limit("P2", max_tokens=999999, max_cost=1.0)
    assert p.check_budget("alice", "acme", "P2", token_budget=100, cost_budget=50.0) is False


class TestLogarithmicBudgetScaling:
    """Test logarithmic token budget scaling by priority tier."""

    def test_p0_gets_most_tokens(self) -> None:
        """P0 (highest priority) gets base_tokens / 1.41."""
        policy = InMemoryTaskAcceptancePolicy()
        priority = "P0"
        base_tokens = 200_000

        max_tokens = policy._calculate_token_budget(priority)
        expected = base_tokens / math.log2(2)
        assert abs(max_tokens - expected) < 1, f"Expected {expected}, got {max_tokens}"

    def test_p2_gets_standard_tokens(self) -> None:
        """P2 (default priority) gets base_tokens / 2.0."""
        policy = InMemoryTaskAcceptancePolicy()
        priority = "P2"
        base_tokens = 100_000

        max_tokens = policy._calculate_token_budget(priority)
        expected = base_tokens / math.log2(4)
        assert abs(max_tokens - expected) < 1, f"Expected {expected}, got {max_tokens}"

    def test_p5_gets_fewest_tokens(self) -> None:
        """P5 (lowest priority) gets base_tokens / 2.83."""
        policy = InMemoryTaskAcceptancePolicy()
        priority = "P5"
        base_tokens = 25_000

        max_tokens = policy._calculate_token_budget(priority)
        expected = base_tokens / math.log2(7)
        assert abs(max_tokens - expected) < 1, f"Expected {expected}, got {max_tokens}"

    def test_scaling_decreases_monotonically(self) -> None:
        """Token budget decreases monotonically from P0 to P5."""
        policy = InMemoryTaskAcceptancePolicy()

        budgets = [policy._calculate_token_budget(f"P{i}") for i in range(6)]

        assert all(budgets[i] >= budgets[i + 1] for i in range(5)), (
            "Token budgets should decrease from P0 to P5"
        )

    def test_check_budget_enforces_scaled_limits(self) -> None:
        """Budget check rejects requests exceeding scaled limits."""
        policy = InMemoryTaskAcceptancePolicy()

        max_tokens_p0 = policy._calculate_token_budget("P0")
        assert not policy.check_budget(
            user_id="user1",
            org_id="org1",
            priority_tier="P0",
            token_budget=max_tokens_p0 + 1,
        )

    def test_set_budget_limit_updates_base_tokens(self) -> None:
        """Setting budget limit updates base tokens for tier."""
        policy = InMemoryTaskAcceptancePolicy()

        new_p2_tokens = 150_000

        policy.set_budget_limit(
            tier="P2",
            max_tokens=new_p2_tokens,
        )

        assert policy._base_tokens_per_tier["P2"] == new_p2_tokens, (
            f"Expected {new_p2_tokens}, got {policy._base_tokens_per_tier['P2']}"
        )
