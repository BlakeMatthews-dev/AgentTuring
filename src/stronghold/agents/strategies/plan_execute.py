"""Plan-execute strategy: plan → subtasks → execute each → review.

Stub implementation for demo. Full version uses sub-agents.
"""

from __future__ import annotations

from typing import Any

from stronghold.types.agent import ReasoningResult


class PlanExecuteStrategy:
    """Plan then execute. Uses sub-agents for each subtask."""

    def __init__(self, max_subtasks: int = 10) -> None:
        self.max_subtasks = max_subtasks

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        """For the demo: delegates planning to LLM, returns plan as response."""
        plan_prompt = (
            "You are a task planner. Decompose the user's request into "
            f"numbered subtasks (max {self.max_subtasks}). "
            "For each subtask, describe what to do and how to test it."
        )
        plan_messages = [
            {"role": "system", "content": plan_prompt},
            *messages,
        ]
        response = await llm.complete(plan_messages, model)
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
        return ReasoningResult(response=content, done=True)
