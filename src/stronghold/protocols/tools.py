"""Tool protocols: executor, registry, and plugin."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from stronghold.types.auth import AuthContext
    from stronghold.types.tool import ToolDefinition, ToolResult


@runtime_checkable
class ToolExecutor(Protocol):
    """Executes a single tool call against a backend."""

    @property
    def name(self) -> str:
        """Tool name this executor handles."""
        ...

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        """Execute the tool with the given arguments."""
        ...


@runtime_checkable
class ToolRegistry(Protocol):
    """Manages tool definitions and executor lookup."""

    def get_definitions(
        self,
        *,
        task_type: str | None = None,
        agent_tools: tuple[str, ...] = (),
    ) -> list[ToolDefinition]:
        """Get tool defs with group-aware full/stub injection."""
        ...

    def get_executor(self, tool_name: str) -> ToolExecutor | None:
        """Look up the executor for a tool by name."""
        ...

    def register(self, executor: ToolExecutor) -> None:
        """Register a new tool executor."""
        ...


@runtime_checkable
class ToolPlugin(Protocol):
    """Plugin interface for operator-provided tool integrations.

    Operators implement this to add custom tools (HA, CoinSwarm,
    search, notifications, etc.) without modifying core Stronghold.
    Plugins self-register at startup via config.
    """

    @property
    def name(self) -> str:
        """Unique tool name."""
        ...

    def get_definition(self) -> ToolDefinition:
        """Return the tool's OpenAI-compatible definition."""
        ...

    async def execute(
        self,
        arguments: dict[str, Any],
        auth: AuthContext,
    ) -> ToolResult:
        """Execute the tool with auth context for tenant-scoped access."""
        ...
