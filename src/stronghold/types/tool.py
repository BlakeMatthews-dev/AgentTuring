"""Tool types: calls, results, definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolDefinition:
    """An OpenAI-compatible tool definition."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    groups: tuple[str, ...] = ()
    endpoint: str = ""
    auth_key_env: str = ""


@dataclass(frozen=True)
class ToolCall:
    """An LLM-generated tool call."""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ToolResult:
    """Result of executing a tool call."""

    content: str = ""
    success: bool = True
    error: str | None = None
    warden_flags: tuple[str, ...] = ()
    sentinel_repaired: bool = False
