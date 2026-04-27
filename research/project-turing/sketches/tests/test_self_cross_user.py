"""Tests for specs/cross-user-self-experience.md."""

from __future__ import annotations

import pytest

from turing.self_cross_user import (
    ANONYMOUS_USER,
    DEFAULT_POLICY,
    CrossUserPolicy,
    cross_user_dampening,
    effective_memory_weight,
    should_require_cross_user,
)


def test_cross_user_dampening_shared():
    assert cross_user_dampening(CrossUserPolicy.SHARED) == 1.0


def test_cross_user_dampening_dampened():
    assert cross_user_dampening(CrossUserPolicy.DAMPENED) == 0.6


def test_cross_user_dampening_isolated():
    assert cross_user_dampening(CrossUserPolicy.ISOLATED) == 0.0


def test_cross_user_dampening_unknown_policy():
    assert cross_user_dampening("unknown") == 0.6


def test_effective_weight_same_user():
    w = effective_memory_weight(0.8, "user-a", "user-a", CrossUserPolicy.DAMPENED)
    assert w == 0.8


def test_effective_weight_cross_user_dampened():
    w = effective_memory_weight(0.8, "user-a", "user-b", CrossUserPolicy.DAMPENED)
    assert abs(w - 0.48) < 0.001


def test_effective_weight_cross_user_shared():
    w = effective_memory_weight(0.8, "user-a", "user-b", CrossUserPolicy.SHARED)
    assert w == 0.8


def test_effective_weight_cross_user_isolated():
    w = effective_memory_weight(0.8, "user-a", "user-b", CrossUserPolicy.ISOLATED)
    assert w == 0.0


def test_effective_weight_none_source():
    w = effective_memory_weight(0.8, None, "user-a", CrossUserPolicy.DAMPENED)
    assert w == 0.8


def test_effective_weight_none_requesting():
    w = effective_memory_weight(0.8, "user-a", None, CrossUserPolicy.DAMPENED)
    assert w == 0.8


def test_effective_weight_both_none():
    w = effective_memory_weight(0.5, None, None, CrossUserPolicy.ISOLATED)
    assert w == 0.5


def test_effective_weight_user_scoped_cross_user():
    w = effective_memory_weight(0.8, "user-a", "user-b", CrossUserPolicy.SHARED, user_scoped=True)
    assert w == 0.0


def test_effective_weight_user_scoped_same_user():
    w = effective_memory_weight(0.8, "user-a", "user-a", CrossUserPolicy.ISOLATED, user_scoped=True)
    assert w == 0.8


def test_effective_weight_user_scoped_none_source():
    w = effective_memory_weight(0.8, None, "user-a", CrossUserPolicy.SHARED, user_scoped=True)
    assert w == 0.0


def test_should_require_cross_user_below_threshold():
    assert not should_require_cross_user(1)


def test_should_require_cross_user_at_threshold():
    assert should_require_cross_user(2)


def test_should_require_cross_user_above_threshold():
    assert should_require_cross_user(5)


def test_anonymous_user_is_string():
    assert ANONYMOUS_USER == "anonymous"


def test_default_policy_is_dampened():
    assert DEFAULT_POLICY == CrossUserPolicy.DAMPENED
