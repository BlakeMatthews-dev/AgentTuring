"""Tests for specs/tiers.md: AC-2.1 through AC-2.5."""

from __future__ import annotations

from turing.tiers import INHERITANCE_PRIORITY, WEIGHT_BOUNDS, clamp_weight
from turing.types import MemoryTier


def test_ac_2_1_accomplishment_in_enum() -> None:
    assert MemoryTier.ACCOMPLISHMENT in MemoryTier
    assert MemoryTier("accomplishment") is MemoryTier.ACCOMPLISHMENT


def test_ac_2_2_accomplishment_bounds() -> None:
    assert WEIGHT_BOUNDS[MemoryTier.ACCOMPLISHMENT] == (0.6, 1.0)


def test_ac_2_2_regret_and_accomplishment_share_bounds() -> None:
    assert WEIGHT_BOUNDS[MemoryTier.REGRET] == WEIGHT_BOUNDS[MemoryTier.ACCOMPLISHMENT]


def test_ac_2_3_clamp_weight_respects_bounds() -> None:
    lo, hi = WEIGHT_BOUNDS[MemoryTier.ACCOMPLISHMENT]
    assert clamp_weight(MemoryTier.ACCOMPLISHMENT, -5.0) == lo
    assert clamp_weight(MemoryTier.ACCOMPLISHMENT, 0.0) == lo
    assert clamp_weight(MemoryTier.ACCOMPLISHMENT, 0.7) == 0.7
    assert clamp_weight(MemoryTier.ACCOMPLISHMENT, 5.0) == hi


def test_ac_2_4_inheritance_priority_accomplishment_eq_5() -> None:
    assert INHERITANCE_PRIORITY[MemoryTier.ACCOMPLISHMENT] == 5
    assert INHERITANCE_PRIORITY[MemoryTier.REGRET] == 5
    assert INHERITANCE_PRIORITY[MemoryTier.AFFIRMATION] == 5


def test_ac_2_5_existing_tier_bounds_unchanged() -> None:
    expected = {
        MemoryTier.OBSERVATION: (0.1, 0.5),
        MemoryTier.HYPOTHESIS: (0.2, 0.6),
        MemoryTier.OPINION: (0.3, 0.8),
        MemoryTier.LESSON: (0.5, 0.9),
        MemoryTier.REGRET: (0.6, 1.0),
        MemoryTier.AFFIRMATION: (0.6, 1.0),
        MemoryTier.WISDOM: (0.9, 1.0),
    }
    for tier, bounds in expected.items():
        assert WEIGHT_BOUNDS[tier] == bounds
