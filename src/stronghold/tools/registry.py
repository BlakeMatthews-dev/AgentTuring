"""Tool registry: manages tool definitions, executors, and OpenAI schema generation.

Replaces the hardcoded _TOOL_SCHEMAS in agents/base.py with a pluggable registry.
Tools register via ToolPlugin protocol or direct definition + callback.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.registry")


class InMemoryToolRegistry:
    """In-memory tool registry. Implements ToolRegistry protocol."""

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._executors: dict[str, Callable[..., Coroutine[Any, Any, ToolResult]]] = {}

    def register(
        self,
        definition: ToolDefinition,
        executor: Callable[..., Coroutine[Any, Any, ToolResult]] | None = None,
    ) -> None:
        """Register a tool definition and optional executor."""
        self._definitions[definition.name] = definition
        if executor is not None:
            self._executors[definition.name] = executor
        logger.debug("Registered tool: %s", definition.name)

    def get(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._definitions.get(name)

    def get_executor(
        self,
        name: str,
    ) -> Callable[..., Coroutine[Any, Any, ToolResult]] | None:
        """Get the executor for a tool by name."""
        return self._executors.get(name)

    def list_all(self) -> list[ToolDefinition]:
        """List all registered tool definitions."""
        return list(self._definitions.values())

    def list_for_task(self, task_type: str) -> list[ToolDefinition]:
        """List tools matching a task type group."""
        return [d for d in self._definitions.values() if not d.groups or task_type in d.groups]

    def get_definitions(
        self,
        *,
        task_type: str | None = None,
        agent_tools: tuple[str, ...] = (),
    ) -> list[ToolDefinition]:
        """Get tool definitions with group-aware filtering.

        If agent_tools specified, only return those tools.
        If task_type specified, full schema for matching groups, stubs for others.
        """
        if agent_tools:
            return [self._definitions[name] for name in agent_tools if name in self._definitions]
        if task_type:
            return self.list_for_task(task_type)
        return self.list_all()

    def to_openai_schemas(
        self,
        *,
        task_type: str | None = None,
        agent_tools: tuple[str, ...] = (),
    ) -> list[dict[str, Any]]:
        """Convert tool definitions to OpenAI function calling format."""
        definitions = self.get_definitions(
            task_type=task_type,
            agent_tools=agent_tools,
        )
        schemas: list[dict[str, Any]] = []
        for defn in definitions:
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": defn.name,
                        "description": defn.description,
                        "parameters": defn.parameters,
                    },
                }
            )
        return schemas

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, name: str) -> bool:
        return name in self._definitions
