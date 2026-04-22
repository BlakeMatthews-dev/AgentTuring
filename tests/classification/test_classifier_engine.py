"""Tests for the ClassifierEngine integration: keyword + complexity + priority."""

import pytest

from stronghold.classifier.engine import ClassifierEngine, is_ambiguous
from stronghold.types.config import TaskTypeConfig


def _task_types() -> dict[str, TaskTypeConfig]:
    return {
        "chat": TaskTypeConfig(
            keywords=["hello", "hi", "hey", "thanks"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "code": TaskTypeConfig(
            keywords=["code", "function", "bug", "error", "implement"],
            min_tier="medium",
            preferred_strengths=["code"],
        ),
        "automation": TaskTypeConfig(
            keywords=["light", "fan", "turn on", "turn off", "chore"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "search": TaskTypeConfig(
            keywords=["search", "look up", "find"],
            min_tier="small",
            preferred_strengths=["chat"],
        ),
        "creative": TaskTypeConfig(
            keywords=["story", "poem", "essay"],
            min_tier="medium",
            preferred_strengths=["creative"],
        ),
        "reasoning": TaskTypeConfig(
            keywords=["prove", "derive", "logic"],
            min_tier="large",
            preferred_strengths=["reasoning"],
        ),
    }


class TestClassifyTaskType:
    """classify() returns correct task_type for known types."""

    @pytest.mark.asyncio
    async def test_chat_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "hello how are you"}],
            _task_types(),
        )
        assert intent.task_type == "chat"

    @pytest.mark.asyncio
    async def test_code_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "write a function to sort a list"}],
            _task_types(),
        )
        assert intent.task_type == "code"

    @pytest.mark.asyncio
    async def test_automation_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "turn on the bedroom fan"}],
            _task_types(),
        )
        assert intent.task_type == "automation"

    @pytest.mark.asyncio
    async def test_search_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "search for the latest news about AI"}],
            _task_types(),
        )
        assert intent.task_type == "search"

    @pytest.mark.asyncio
    async def test_creative_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "write a story about a dragon"}],
            _task_types(),
        )
        # Strong indicator "write a story" triggers creative
        assert intent.task_type == "creative"

    @pytest.mark.asyncio
    async def test_reasoning_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [
                {
                    "role": "user",
                    "content": "prove that the square root of 2 is irrational step by step",
                }
            ],
            _task_types(),
        )
        assert intent.task_type == "reasoning"


class TestClassifyEdgeCases:
    """Edge cases for classify()."""

    @pytest.mark.asyncio
    async def test_empty_messages(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify([], _task_types())
        assert intent.task_type == "chat"  # default
        assert intent.user_text == ""

    @pytest.mark.asyncio
    async def test_empty_user_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": ""}],
            _task_types(),
        )
        assert intent.task_type == "chat"

    @pytest.mark.asyncio
    async def test_very_long_message(self) -> None:
        engine = ClassifierEngine()
        long_text = "write code to " + "do something complex " * 200
        intent = await engine.classify(
            [{"role": "user", "content": long_text}],
            _task_types(),
        )
        assert intent.task_type == "code"  # "write code to" is a strong code signal
        assert intent.complexity == "complex"  # long text = complex

    @pytest.mark.asyncio
    async def test_single_word(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "hello"}],
            _task_types(),
        )
        assert intent.task_type == "chat"
        assert intent.complexity == "simple"

    @pytest.mark.asyncio
    async def test_only_system_message(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "system", "content": "You are a helpful assistant"}],
            _task_types(),
        )
        assert intent.task_type == "chat"  # no user text => default

    @pytest.mark.asyncio
    async def test_last_user_message_used(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
                {"role": "user", "content": "write a function to sort"},
            ],
            _task_types(),
        )
        assert intent.task_type == "code"

    @pytest.mark.asyncio
    async def test_explicit_priority_respected(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "hello"}],
            _task_types(),
            explicit_priority="P0",
        )
        assert intent.tier == "P0"

    @pytest.mark.asyncio
    async def test_classified_by_keywords(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "write a function to sort"}],
            _task_types(),
        )
        assert intent.classified_by == "keywords"


class TestIsAmbiguous:
    """is_ambiguous() with various score distributions."""

    def test_clear_single_high_score(self) -> None:
        scores = {"code": 5.0, "chat": 0.0}
        assert not is_ambiguous(scores)

    def test_single_nonzero_not_ambiguous(self) -> None:
        scores = {"code": 1.0}
        assert not is_ambiguous(scores)

    def test_two_close_scores_below_threshold(self) -> None:
        scores = {"code": 2.0, "chat": 1.5}
        assert is_ambiguous(scores)

    def test_two_scores_one_above_threshold(self) -> None:
        scores = {"code": 4.0, "chat": 1.0}
        assert not is_ambiguous(scores)

    def test_all_zero_not_ambiguous(self) -> None:
        scores = {"code": 0.0, "chat": 0.0, "search": 0.0}
        assert not is_ambiguous(scores)

    def test_empty_scores_not_ambiguous(self) -> None:
        assert not is_ambiguous({})

    def test_many_low_scores_ambiguous(self) -> None:
        scores = {"code": 1.0, "chat": 1.0, "search": 1.0, "creative": 1.0}
        assert is_ambiguous(scores)

    def test_one_at_threshold_not_ambiguous(self) -> None:
        scores = {"code": 3.0, "chat": 1.0}
        assert not is_ambiguous(scores)

    def test_one_just_below_threshold_ambiguous(self) -> None:
        scores = {"code": 2.9, "chat": 1.0}
        assert is_ambiguous(scores)

    def test_single_zero_not_ambiguous(self) -> None:
        scores = {"code": 0.0}
        assert not is_ambiguous(scores)


class TestComplexityEstimation:
    """Complexity estimation via classify()."""

    @pytest.mark.asyncio
    async def test_short_is_simple(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "hi there"}],
            _task_types(),
        )
        assert intent.complexity == "simple"

    @pytest.mark.asyncio
    async def test_very_long_is_complex(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "word " * 201}],
            _task_types(),
        )
        assert intent.complexity == "complex"

    @pytest.mark.asyncio
    async def test_complex_signals_detected(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [
                {
                    "role": "user",
                    "content": (
                        "Please do a step by step detailed analysis of the code, "
                        "refactor and optimize it for better performance and maintainability"
                    ),
                }
            ],
            _task_types(),
        )
        assert intent.complexity in ("moderate", "complex")


class TestPriorityInference:
    """Priority inferred from urgency keywords."""

    @pytest.mark.asyncio
    async def test_urgent_is_critical(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "urgent the server is down help"}],
            _task_types(),
        )
        assert intent.tier == "P0"

    @pytest.mark.asyncio
    async def test_important_is_p1(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "this is important for the client demo"}],
            _task_types(),
        )
        assert intent.tier == "P1"

    @pytest.mark.asyncio
    async def test_no_rush_is_p4(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "just curious about something no rush"}],
            _task_types(),
        )
        assert intent.tier == "P4"

    @pytest.mark.asyncio
    async def test_normal_message_p2_tier(self) -> None:
        engine = ClassifierEngine()
        intent = await engine.classify(
            [{"role": "user", "content": "hello how are you"}],
            _task_types(),
        )
        assert intent.tier == "P2"


class TestMultiIntentDetection:
    """detect_multi_intent identifies compound requests."""

    def test_single_intent_returns_empty_list(self) -> None:
        """A simple single-topic request has no compound intents; the
        contract is to return an empty list (not None, not a single-element
        list) so callers can use truthiness to branch."""
        engine = ClassifierEngine()
        result = engine.detect_multi_intent("turn on the fan", _task_types())
        assert result == []

    def test_compound_request_returns_distinct_intents(self) -> None:
        """A request with two clear task types separated by 'and' produces
        a list containing BOTH task_type strings, in the order they appear,
        without duplicates."""
        engine = ClassifierEngine()
        result = engine.detect_multi_intent(
            "search for recipes and write code to parse them",
            _task_types(),
        )
        # At least two distinct task types must have been detected.
        assert len(result) >= 2
        assert "search" in result
        assert "code" in result
        # No duplicates.
        assert len(result) == len(set(result))
