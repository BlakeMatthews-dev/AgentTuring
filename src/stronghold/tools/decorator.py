"""@tool decorator for registering functions as Stronghold tools."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from stronghold.tools.catalog import CatalogEntry
from stronghold.types.tool import ToolDefinition

if TYPE_CHECKING:
    from collections.abc import Callable

_REGISTERED_TOOLS: list[CatalogEntry] = []


def tool(
    name: str,
    *,
    version: str = "1.0.0",
    description: str = "",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator to register a function as a Stronghold tool."""

    def wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
        # Build parameters from function signature
        sig = inspect.signature(fn)
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            prop: dict[str, str] = {"type": "string"}
            if param.annotation != inspect.Parameter.empty:
                # Resolve string annotations from __future__ annotations
                ann = param.annotation
                hints = inspect.get_annotations(fn, eval_str=True)
                resolved = hints.get(param_name, ann)
                if resolved is int:
                    prop = {"type": "integer"}
                elif resolved is float:
                    prop = {"type": "number"}
                elif resolved is bool:
                    prop = {"type": "boolean"}
            properties[param_name] = prop
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        definition = ToolDefinition(
            name=name,
            description=description or fn.__doc__ or "",
            parameters={
                "type": "object",
                "properties": properties,
                "required": required,
            },
        )

        entry = CatalogEntry(definition=definition, version=version, scope="builtin")
        fn._catalog_entry = entry  # type: ignore[attr-defined]
        _REGISTERED_TOOLS.append(entry)
        return fn

    return wrapper


def get_decorated_tools() -> list[CatalogEntry]:
    """Return all tools registered via the @tool decorator."""
    return list(_REGISTERED_TOOLS)
