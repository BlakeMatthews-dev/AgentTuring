"""Tool Protocol + ToolRegistry with explicit permission allowlist.

Every outward-facing action goes through a registered Tool. The registry
enforces the operator's allowlist: a Tool not registered cannot be invoked.
This is the structural equivalent of `DaydreamWriter`'s source-lock — the
only way to do something the operator hasn't approved is to edit this code.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol


logger = logging.getLogger("turing.runtime.tools")


class ToolMode(StrEnum):
    READ = "read"
    WRITE = "write"
    SUBSCRIBE = "subscribe"


class Tool(Protocol):
    name: str
    mode: ToolMode

    def invoke(self, *args: Any, **kwargs: Any) -> Any: ...


class ToolNotPermitted(RuntimeError):
    pass


class ToolRegistry:
    """Holds the operator-approved tools.

    Lookup-by-name only. A name not registered is a hard error — there is no
    fallback to "try the LLM" or anything similar. The Conduit can only do
    what the operator has explicitly approved.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name!r} already registered")
        self._tools[tool.name] = tool
        logger.info("registered tool %s (%s)", tool.name, tool.mode)

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotPermitted(f"tool {name!r} is not registered; operator has not approved it")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def names_by_mode(self, mode: ToolMode) -> list[str]:
        return sorted(name for name, t in self._tools.items() if t.mode == mode)

    def invoke(self, name: str, **kwargs: Any) -> Any:
        return self.get(name).invoke(**kwargs)
