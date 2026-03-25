"""Tests for complexity estimation."""

from stronghold.classifier.complexity import estimate_complexity, infer_priority


class TestComplexity:
    def test_short_is_simple(self) -> None:
        assert estimate_complexity("fix this bug", "code") == "simple"

    def test_very_long_is_complex(self) -> None:
        text = "word " * 201
        assert estimate_complexity(text, "chat") == "complex"

    def test_two_signals_is_complex(self) -> None:
        text = (
            "I would like you to step by step refactor and optimize "
            "all the components in this module carefully please"
        )
        assert estimate_complexity(text, "chat") == "complex"

    def test_code_task_defaults_moderate(self) -> None:
        text = "write a sorting function for lists"
        result = estimate_complexity(text, "code")
        assert result in ("simple", "moderate")


class TestPriority:
    def test_urgent_is_critical(self) -> None:
        assert infer_priority("this is urgent please fix now") == "critical"

    def test_no_rush_is_low(self) -> None:
        assert infer_priority("when you get a chance no rush") == "low"

    def test_default_is_normal(self) -> None:
        assert infer_priority("can you help me with this") == "normal"


class TestComplexityBoundaries:
    def test_exactly_15_words_is_simple(self) -> None:
        text = " ".join(["word"] * 14)
        assert estimate_complexity(text, "chat") == "simple"

    def test_exactly_200_words(self) -> None:
        text = " ".join(["word"] * 200)
        result = estimate_complexity(text, "chat")
        assert result in ("moderate", "complex")

    def test_one_signal_moderate(self) -> None:
        text = "I want to optimize " + " ".join(["word"] * 85)
        assert estimate_complexity(text, "chat") == "moderate"

    def test_empty_text(self) -> None:
        assert estimate_complexity("", "chat") == "simple"

    def test_code_tasks_tend_moderate(self) -> None:
        text = "write a sorting function for lists"
        result = estimate_complexity(text, "code")
        assert result in ("simple", "moderate")


class TestPriorityEdgeCases:
    def test_multiple_urgent_words(self) -> None:
        assert infer_priority("urgent critical emergency") == "critical"

    def test_empty_text_is_normal(self) -> None:
        assert infer_priority("") == "normal"

    def test_mixed_signals(self) -> None:
        # "urgent" is critical, "no rush" is low — first match wins
        result = infer_priority("urgent but no rush")
        assert result == "critical"
