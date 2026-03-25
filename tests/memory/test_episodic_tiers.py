"""Tests for 7-tier weight mechanics."""

from stronghold.memory.episodic.tiers import clamp_weight, decay, reinforce
from stronghold.types.memory import WEIGHT_BOUNDS, EpisodicMemory, MemoryTier


class TestWeightBounds:
    def test_all_tiers_have_bounds(self) -> None:
        for tier in MemoryTier:
            assert tier in WEIGHT_BOUNDS

    def test_regret_cannot_drop_below_06(self) -> None:
        result = clamp_weight(MemoryTier.REGRET, 0.1)
        assert result >= 0.6

    def test_wisdom_cannot_drop_below_09(self) -> None:
        result = clamp_weight(MemoryTier.WISDOM, 0.5)
        assert result >= 0.9

    def test_observation_capped_at_05(self) -> None:
        result = clamp_weight(MemoryTier.OBSERVATION, 1.0)
        assert result <= 0.5

    def test_reinforce_clamped_to_ceiling(self) -> None:
        mem = EpisodicMemory(
            memory_id="test",
            tier=MemoryTier.OBSERVATION,
            content="test",
            weight=0.5,
        )
        result = reinforce(mem, delta=0.1)
        assert result.weight <= 0.5  # observation ceiling

    def test_decay_clamped_to_floor(self) -> None:
        mem = EpisodicMemory(
            memory_id="test",
            tier=MemoryTier.REGRET,
            content="test",
            weight=0.6,
        )
        result = decay(mem, delta=0.1)
        assert result.weight >= 0.6  # regret floor

    def test_reinforce_increments_count(self) -> None:
        mem = EpisodicMemory(
            memory_id="test",
            tier=MemoryTier.LESSON,
            content="test",
            weight=0.6,
        )
        result = reinforce(mem)
        assert result.reinforcement_count == 1


class TestDecayMechanics:
    def test_decay_increments_contradiction(self) -> None:
        mem = EpisodicMemory(
            memory_id="test",
            tier=MemoryTier.OPINION,
            content="test",
            weight=0.5,
        )
        result = decay(mem)
        assert result.contradiction_count == 1


class TestAllTiers:
    def test_observation_bounds(self) -> None:
        assert clamp_weight(MemoryTier.OBSERVATION, 0.0) == 0.1
        assert clamp_weight(MemoryTier.OBSERVATION, 1.0) == 0.5

    def test_hypothesis_bounds(self) -> None:
        assert clamp_weight(MemoryTier.HYPOTHESIS, 0.0) == 0.2
        assert clamp_weight(MemoryTier.HYPOTHESIS, 1.0) == 0.6

    def test_opinion_bounds(self) -> None:
        assert clamp_weight(MemoryTier.OPINION, 0.0) == 0.3
        assert clamp_weight(MemoryTier.OPINION, 1.0) == 0.8

    def test_lesson_bounds(self) -> None:
        assert clamp_weight(MemoryTier.LESSON, 0.0) == 0.5
        assert clamp_weight(MemoryTier.LESSON, 1.0) == 0.9

    def test_affirmation_bounds(self) -> None:
        assert clamp_weight(MemoryTier.AFFIRMATION, 0.0) == 0.6
        assert clamp_weight(MemoryTier.AFFIRMATION, 1.0) == 1.0

    def test_wisdom_bounds(self) -> None:
        assert clamp_weight(MemoryTier.WISDOM, 0.0) == 0.9
        assert clamp_weight(MemoryTier.WISDOM, 1.0) == 1.0


class TestReinforcementChain:
    def test_multiple_reinforcements(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.LESSON, content="t", weight=0.5)
        for _ in range(20):
            mem = reinforce(mem)
        assert mem.weight <= 0.9  # capped at ceiling
        assert mem.reinforcement_count == 20

    def test_multiple_decays(self) -> None:
        mem = EpisodicMemory(memory_id="t", tier=MemoryTier.REGRET, content="t", weight=0.9)
        for _ in range(20):
            mem = decay(mem)
        assert mem.weight >= 0.6  # cannot go below floor
        assert mem.contradiction_count == 20
