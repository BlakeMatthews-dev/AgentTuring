"""IntentClassifier protocol definition."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from stronghold.types.intent import Intent


class IntentClassifier(Protocol):
    """Protocol for intent classification functionality."""

    def classify(
        self,
        messages: list[str],
        task_types: list[str],
        explicit_priority: bool = False,
    ) -> Intent:
        """Classify intent from messages.

        Args:
            messages: List of message strings to analyze
            task_types: List of task types to consider
            explicit_priority: Whether to prioritize explicit intents

        Returns:
            The classified intent
        """
        ...

    def detect_multi_intent(
        self,
        user_text: str,
        task_types: list[str],
    ) -> list[str]:
        """Detect multiple intents in user text.

        Args:
            user_text: The user input text to analyze
            task_types: List of task types to consider

        Returns:
            List of detected intent strings
        """
        ...
