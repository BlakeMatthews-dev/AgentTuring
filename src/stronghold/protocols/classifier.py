"""Intent classifier protocol."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.config import TaskTypeConfig
    from stronghold.types.intent import Intent


@runtime_checkable
class IntentClassifier(Protocol):
    """Classifies user messages into task types with complexity and priority."""

    async def classify(
        self,
        messages: list[dict[str, str]],
        task_types: dict[str, TaskTypeConfig],
        explicit_priority: str | None = None,
    ) -> Intent:
        """Classify the user's intent."""
        ...

    def detect_multi_intent(
        self,
        user_text: str,
        task_types: dict[str, TaskTypeConfig],
    ) -> list[str]:
        """Returns list of task_type strings if compound request, else empty."""
        ...
