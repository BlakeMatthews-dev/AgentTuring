"""Tests for TaskAcceptancePolicy (ADR-K8S-030)."""

from __future__ import annotations

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
    # P0 default max_tokens is 100_000
    assert p.check_budget("alice", "acme", "P0", token_budget=200_000) is False


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
    """SECURITY: unknown tier names must not bypass budget enforcement."""
    p = InMemoryTaskAcceptancePolicy()
    assert p.check_budget("alice", "acme", "P99", token_budget=1) is False
    assert p.check_budget("alice", "acme", "", token_budget=1) is False
    assert p.check_budget("alice", "acme", "P0'; DROP TABLE users;--", token_budget=1) is False


def test_custom_budget_limit() -> None:
    p = InMemoryTaskAcceptancePolicy()
    p.set_budget_limit("P5", max_tokens=100)
    assert p.check_budget("alice", "acme", "P5", token_budget=50) is True
    assert p.check_budget("alice", "acme", "P5", token_budget=200) is False


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
