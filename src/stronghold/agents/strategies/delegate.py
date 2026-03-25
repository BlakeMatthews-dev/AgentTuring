"""Delegate strategy: classify intent → route to sub-agent."""

from __future__ import annotations

from typing import Any

from stronghold.types.agent import ReasoningResult


class DelegateStrategy:
    """Classify and route to the correct sub-agent."""

    def __init__(self, routing_table: dict[str, str], default_agent: str = "") -> None:
        self._routing = routing_table
        self._default = default_agent

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: Any,  # noqa: ARG002
        *,
        classified_task_type: str = "chat",
        **kwargs: Any,
    ) -> ReasoningResult:
        """Route to the correct agent based on task type."""
        target = self._routing.get(classified_task_type, self._default)

        if not target:
            # No routing match — handle directly as chat
            return ReasoningResult(
                response=None,
                done=False,
                delegate_to=None,
            )

        # Extract user text for delegation
        user_text = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_text = str(msg.get("content", ""))
                break

        return ReasoningResult(
            response=None,
            done=False,
            delegate_to=target,
            delegate_message=user_text,
        )
