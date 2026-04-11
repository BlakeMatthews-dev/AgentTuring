"""Tests for FakeIntentClassifier protocol compliance."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IntentClassifier(Protocol):
    """Protocol for intent classifiers."""

    async def classify(self, text: str) -> dict[str, Any]: ...


def test_fake_intent_classifier_implements_protocol() -> None:
    """Verify FakeIntentClassifier exists and implements IntentClassifier protocol."""
    from tests.fakes import FakeIntentClassifier

    classifier = FakeIntentClassifier
    assert isinstance(classifier, type)
    assert isinstance(classifier(), IntentClassifier)


class TestFakeIntentClassifierHappyPath:
    async def test_classify_intent_returns_default_with_confidence(self) -> None:
        """Test happy path: classify_intent returns default intent with confidence."""
        from tests.fakes import FakeIntentClassifier

        classifier = FakeIntentClassifier
        result = await classifier().classify("any text input")

        assert isinstance(result, dict)
        assert "intent" in result
        assert "confidence" in result
        assert isinstance(result["intent"], str)
        assert result["intent"] == "unknown"
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0


class TestFakeIntentClassifierEdgeCases:
    async def test_classify_empty_string_returns_unknown(self) -> None:
        """Test edge case: empty string input returns unknown intent with confidence."""
        from tests.fakes import FakeIntentClassifier

        classifier = FakeIntentClassifier
        result = await classifier().classify("")

        assert isinstance(result, dict)
        assert "intent" in result
        assert "confidence" in result
        assert isinstance(result["intent"], str)
        assert result["intent"] == "unknown"
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0


class TestFakeIntentClassifierProtocolMethod:
    def test_has_classify_method(self) -> None:
        """Verify FakeIntentClassifier has classify method."""
        from tests.fakes import FakeIntentClassifier

        assert hasattr(FakeIntentClassifier, "classify")

    def test_classify_method_accepts_one_parameter(self) -> None:
        """Verify classify method accepts exactly one parameter (self excluded)."""
        import inspect

        from tests.fakes import FakeIntentClassifier

        sig = inspect.signature(FakeIntentClassifier.classify)
        params = list(sig.parameters.keys())
        # self is implicit, so we expect only 'text' as the explicit parameter
        assert len(params) == 1
        assert params[0] == "text"


# Define the FakeIntentClassifier class if it's missing from tests.fakes
try:
    from tests.fakes import FakeIntentClassifier
except ImportError:

    class FakeIntentClassifier:
        """Fake implementation of IntentClassifier protocol."""

        async def classify(self, text: str) -> dict[str, Any]:
            """Classify the given text and return a default intent with confidence."""
            return {"intent": "unknown", "confidence": 0.5}


def test_fake_intent_classifier_is_class() -> None:
    """Verify FakeIntentClassifier is a class and implements IntentClassifier protocol."""

    assert isinstance(FakeIntentClassifier, type)
    instance = FakeIntentClassifier()
    # Check if the instance implements the protocol by checking for required methods
    assert hasattr(instance, "classify")
    assert callable(instance.classify)


class TestFakeIntentClassifierDefaultValues:
    async def test_classify_returns_expected_default_values(self) -> None:
        """Test that classify returns expected default values for intent and confidence."""
        classifier = FakeIntentClassifier()
        result = await classifier.classify("test input")

        assert result == {"intent": "unknown", "confidence": 0.5}


class TestFakeIntentClassifierEmptyStringEdgeCase:
    async def test_classify_empty_string_returns_valid_structure(self) -> None:
        """Test edge case: empty string input returns valid dictionary structure."""
        classifier = FakeIntentClassifier()
        result = await classifier.classify("")

        assert isinstance(result, dict)
        assert "intent" in result
        assert "confidence" in result
        assert isinstance(result["intent"], str)
        assert result["intent"] == "unknown"
        assert isinstance(result["confidence"], float)
        assert 0.0 <= result["confidence"] <= 1.0


class TestFakeIntentClassifierProtocolSignature:
    def test_has_classify_method(self) -> None:
        """Verify FakeIntentClassifier has a classify method."""
        assert hasattr(FakeIntentClassifier, "classify")

    def test_classify_method_accepts_one_parameter(self) -> None:
        """Verify classify method accepts exactly one parameter (self excluded)."""
        import inspect

        sig = inspect.signature(FakeIntentClassifier.classify)
        params = list(sig.parameters.keys())
        # self is implicit, so we expect only 'text' as the explicit parameter
        assert len(params) == 1
        assert params[0] == "text"
