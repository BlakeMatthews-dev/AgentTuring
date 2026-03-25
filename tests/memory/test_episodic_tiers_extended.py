"""Extended episodic tier tests: bounds, reinforcement, decay edge cases."""

import pytest

from stronghold.memory.episodic.tiers import clamp_weight, decay, reinforce
from stronghold.types.memory import WEIGHT_BOUNDS, EpisodicMemory, MemoryTier


class TestWeightBoundsEnforced:
    """All 7 tiers must enforce their documented (floor, ceiling) bounds."""

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_floor_enforced(self, tier: MemoryTier) -> None:
        floor, _ = WEIGHT_BOUNDS[tier]
        assert clamp_weight(tier, -1.0) == floor

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_ceiling_enforced(self, tier: MemoryTier) -> None:
        _, ceiling = WEIGHT_BOUNDS[tier]
        assert clamp_weight(tier, 99.0) == ceiling

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_mid_value_untouched(self, tier: MemoryTier) -> None:
        floor, ceiling = WEIGHT_BOUNDS[tier]
        mid = (floor + ceiling) / 2
        assert clamp_weight(tier, mid) == mid

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_floor_value_exact(self, tier: MemoryTier) -> None:
        floor, _ = WEIGHT_BOUNDS[tier]
        assert clamp_weight(tier, floor) == floor

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_ceiling_value_exact(self, tier: MemoryTier) -> None:
        _, ceiling = WEIGHT_BOUNDS[tier]
        assert clamp_weight(tier, ceiling) == ceiling


class TestReinforcementAtCeiling:
    """Reinforce when already at ceiling should stay at ceiling."""

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_reinforce_at_ceiling_stays(self, tier: MemoryTier) -> None:
        _, ceiling = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=ceiling)
        result = reinforce(mem, delta=0.1)
        assert result.weight == ceiling
        assert result.reinforcement_count == 1

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_double_reinforce_at_ceiling(self, tier: MemoryTier) -> None:
        _, ceiling = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=ceiling)
        mem = reinforce(mem, delta=0.1)
        mem = reinforce(mem, delta=0.1)
        assert mem.weight == ceiling
        assert mem.reinforcement_count == 2


class TestDecayAtFloor:
    """Decay when already at floor should stay at floor."""

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_decay_at_floor_stays(self, tier: MemoryTier) -> None:
        floor, _ = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=floor)
        result = decay(mem, delta=0.1)
        assert result.weight == floor
        assert result.contradiction_count == 1

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_double_decay_at_floor(self, tier: MemoryTier) -> None:
        floor, _ = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=floor)
        mem = decay(mem, delta=0.1)
        mem = decay(mem, delta=0.1)
        assert mem.weight == floor
        assert mem.contradiction_count == 2


class TestMultipleReinforcements:
    """Reinforcement accumulates correctly, capped at ceiling."""

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_10_reinforcements_capped(self, tier: MemoryTier) -> None:
        floor, ceiling = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=floor)
        for _ in range(10):
            mem = reinforce(mem, delta=0.05)
        assert mem.weight <= ceiling
        assert mem.reinforcement_count == 10

    def test_lesson_from_floor_to_ceiling(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.LESSON, content="t", weight=0.5)
        for _ in range(100):
            mem = reinforce(mem, delta=0.05)
        assert mem.weight == 0.9  # LESSON ceiling
        assert mem.reinforcement_count == 100

    def test_observation_from_floor_to_ceiling(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.OBSERVATION, content="t", weight=0.1)
        for _ in range(100):
            mem = reinforce(mem, delta=0.05)
        assert mem.weight == 0.5  # OBSERVATION ceiling
        assert mem.reinforcement_count == 100


class TestMultipleDecays:
    """Decay accumulates correctly, capped at floor."""

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_10_decays_capped(self, tier: MemoryTier) -> None:
        floor, ceiling = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=ceiling)
        for _ in range(10):
            mem = decay(mem, delta=0.05)
        assert mem.weight >= floor
        assert mem.contradiction_count == 10

    def test_regret_from_ceiling_to_floor(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.REGRET, content="t", weight=1.0)
        for _ in range(100):
            mem = decay(mem, delta=0.05)
        assert mem.weight == 0.6  # REGRET floor
        assert mem.contradiction_count == 100

    def test_wisdom_narrow_range(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.WISDOM, content="t", weight=1.0)
        for _ in range(100):
            mem = decay(mem, delta=0.05)
        assert mem.weight == 0.9  # WISDOM floor


class TestReinforceDecayAlternating:
    """Alternating reinforce and decay should stay in bounds."""

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_alternating_stays_in_bounds(self, tier: MemoryTier) -> None:
        floor, ceiling = WEIGHT_BOUNDS[tier]
        mid = (floor + ceiling) / 2
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=mid)
        for _ in range(20):
            mem = reinforce(mem, delta=0.03)
            mem = decay(mem, delta=0.03)
        assert floor <= mem.weight <= ceiling

    def test_reinforce_then_decay_preserves_counts(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.OPINION, content="t", weight=0.5)
        for _ in range(3):
            mem = reinforce(mem)
        for _ in range(2):
            mem = decay(mem)
        assert mem.reinforcement_count == 3
        assert mem.contradiction_count == 2


class TestZeroDelta:
    """Delta of zero should not change weight but still count."""

    def test_reinforce_zero_delta(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.LESSON, content="t", weight=0.7)
        result = reinforce(mem, delta=0.0)
        assert result.weight == 0.7
        assert result.reinforcement_count == 1

    def test_decay_zero_delta(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.LESSON, content="t", weight=0.7)
        result = decay(mem, delta=0.0)
        assert result.weight == 0.7
        assert result.contradiction_count == 1


class TestLargeDelta:
    """Very large delta should still be clamped."""

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_huge_reinforce_clamped(self, tier: MemoryTier) -> None:
        floor, ceiling = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=floor)
        result = reinforce(mem, delta=100.0)
        assert result.weight == ceiling

    @pytest.mark.parametrize("tier", list(MemoryTier))
    def test_huge_decay_clamped(self, tier: MemoryTier) -> None:
        floor, ceiling = WEIGHT_BOUNDS[tier]
        mem = EpisodicMemory(memory_id="t", tier=tier, content="t", weight=ceiling)
        result = decay(mem, delta=100.0)
        assert result.weight == floor
