"""Intent registry: static routing table mapping task_type → agent_name."""

from __future__ import annotations


class IntentRegistry:
    """Maps task types to agent names."""

    def __init__(self, routing_table: dict[str, str] | None = None) -> None:
        self._table = routing_table or {
            "code": "artificer",
            "automation": "warden-at-arms",
            "search": "ranger",
            "creative": "scribe",
            "reasoning": "artificer",
        }

    def get_agent_for_intent(self, task_type: str) -> str | None:
        """Return the agent name for a task type, or None for default handling."""
        return self._table.get(task_type)
