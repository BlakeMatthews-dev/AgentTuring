"""Tests for IntentClassifier protocol methods and signatures."""

from __future__ import annotations

import inspect
from typing import Protocol

from stronghold.protocols.classifier import IntentClassifier


class TestIntentClassifierProtocol:
    def test_protocol_methods_and_signatures(self) -> None:
        """Verify IntentClassifier protocol has correct methods and signatures."""
        # Verify it's a Protocol
        assert isinstance(IntentClassifier, type) and issubclass(IntentClassifier, Protocol)

        # Get all members of the protocol
        members = inspect.getmembers(IntentClassifier)

        # Extract methods (functions) from members
        methods = [
            name
            for name, member in members
            if inspect.isfunction(member) or inspect.ismethod(member)
        ]

        # Verify required methods exist
        assert "classify" in methods, "classify method is missing from IntentClassifier protocol"
        assert "detect_multi_intent" in methods, (
            "detect_multi_intent method is missing from IntentClassifier protocol"
        )

        # Verify classify method signature
        classify_method = IntentClassifier.classify
        sig = inspect.signature(classify_method)
        params = list(sig.parameters.keys())
        assert params == ["self", "messages", "task_types", "explicit_priority"], (
            f"classify method has incorrect parameters: {params}"
        )
        assert sig.return_annotation == "Intent", (
            f"classify method has incorrect return type: {sig.return_annotation}"
        )

        # Verify detect_multi_intent method signature
        detect_method = IntentClassifier.detect_multi_intent
        sig = inspect.signature(detect_method)
        params = list(sig.parameters.keys())
        assert params == ["self", "user_text", "task_types"], (
            f"detect_multi_intent method has incorrect parameters: {params}"
        )
        assert sig.return_annotation == "list[str]", (
            f"detect_multi_intent method has incorrect return type: {sig.return_annotation}"
        )

    def test_protocol_method_documentation(self) -> None:
        """Verify IntentClassifier protocol methods are properly documented."""
        # Verify classify method has docstring
        classify_method = IntentClassifier.classify
        assert classify_method.__doc__ is not None, (
            "classify method is missing docstring documentation"
        )
        assert len(classify_method.__doc__.strip()) > 0, "classify method has empty docstring"

        # Verify detect_multi_intent method has docstring
        detect_method = IntentClassifier.detect_multi_intent
        assert detect_method.__doc__ is not None, (
            "detect_multi_intent method is missing docstring documentation"
        )
        assert len(detect_method.__doc__.strip()) > 0, (
            "detect_multi_intent method has empty docstring"
        )

        # Verify docstrings contain key documentation elements
        classify_doc = classify_method.__doc__.lower()
        assert "intent" in classify_doc, "classify method docstring should mention 'intent'"
        assert "messages" in classify_doc, "classify method docstring should mention 'messages'"
        assert "task" in classify_doc, "classify method docstring should mention 'task'"

        detect_doc = detect_method.__doc__.lower()
        assert "intent" in detect_doc, (
            "detect_multi_intent method docstring should mention 'intent'"
        )
        assert "multi" in detect_doc or "multiple" in detect_doc, (
            "detect_multi_intent method docstring should mention multi-intent detection"
        )
