"""Tests for task-type-aware speed bonuses."""

from stronghold.router.speed import SPEED_WEIGHTS, compute_speed_bonus


class TestSpeedWeights:
    def test_automation_has_speed_bonus(self) -> None:
        assert SPEED_WEIGHTS.get("automation", 0.0) > 0.0

    def test_code_has_no_speed_bonus(self) -> None:
        assert SPEED_WEIGHTS.get("code", 0.0) == 0.0

    def test_reasoning_has_no_speed_bonus(self) -> None:
        assert SPEED_WEIGHTS.get("reasoning", 0.0) == 0.0


class TestSpeedBonus:
    def test_fast_model_gets_bonus_for_automation(self) -> None:
        bonus = compute_speed_bonus("automation", 2000)
        assert bonus > 0.0

    def test_slow_model_gets_small_bonus(self) -> None:
        fast = compute_speed_bonus("automation", 2000)
        slow = compute_speed_bonus("automation", 50)
        assert fast > slow

    def test_code_task_no_bonus_regardless_of_speed(self) -> None:
        bonus = compute_speed_bonus("code", 2000)
        assert bonus == 0.0
