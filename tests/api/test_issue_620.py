"""Behavioural tests for tests.fakes.FakeIntentClassifier.

The original file (issue #620) contained ~10 tests that mostly checked
``isinstance(result["intent"], str)`` and ``hasattr(cls, "classify")`` —
things the type annotations already guarantee. The rewrites below test
actual classifier behaviour that downstream code relies on.
"""

from __future__ import annotations

import pytest

from tests.fakes import FakeIntentClassifier


class TestFakeIntentClassifierBehaviour:
    """FakeIntentClassifier is wired into the test Container; it must
    produce the exact shape the real IntentClassifier promises so that
    downstream consumers don't branch on ``isinstance`` at runtime."""

    @pytest.mark.parametrize(
        "text",
        [
            "turn on the kitchen light",
            "",
            "   \t\n   ",
            "a" * 10_000,
            "日本語の入力",
            "<script>alert(1)</script>",
        ],
    )
    async def test_classify_returns_stable_unknown_for_any_input(
        self, text: str
    ) -> None:
        """FakeIntentClassifier is deliberately dumb — every input produces
        the same ``unknown`` verdict. Callers that see a shifting intent
        from the fake are getting nondeterminism in their test environment.
        """
        result = await FakeIntentClassifier().classify(text)
        assert result == {"intent": "unknown", "confidence": 0.5}

    async def test_classify_is_independent_across_calls(self) -> None:
        """The fake must not accumulate state — two calls on the same
        instance produce identical results, and a fresh instance matches."""
        c = FakeIntentClassifier()
        r1 = await c.classify("one")
        r2 = await c.classify("two")
        r3 = await FakeIntentClassifier().classify("three")
        assert r1 == r2 == r3

    async def test_classify_signature_is_single_text_param(self) -> None:
        """Downstream consumers call ``classifier.classify(text)`` — a
        signature regression (e.g. accidentally requiring a second arg)
        would break the ``IntentClassifier`` protocol silently because
        the fake is only duck-typed.
        """
        import inspect

        sig = inspect.signature(FakeIntentClassifier.classify)
        params = list(sig.parameters.keys())
        # @staticmethod — no implicit self — must be exactly ``text``.
        assert params == ["text"]
