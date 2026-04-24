"""PlaybookDefinition and the @playbook decorator.

A Playbook is a function that accepts `(inputs: dict, ctx: PlaybookContext)`
and returns a Brief. The @playbook decorator attaches a PlaybookDefinition
to the function so a registry can discover it; the decorator also injects
`dry_run` into the input schema when `writes=True`, per the plan's dry-run
contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from stronghold.playbooks.brief import Brief

_DRY_RUN_PROPERTY: dict[str, Any] = {
    "type": "boolean",
    "description": "When true, render the planned action without executing the write.",
    "default": False,
}


@dataclass(frozen=True)
class PlaybookDefinition:
    """Static metadata for an agent-oriented playbook."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {"type": "object", "properties": {}, "required": []},
    )
    writes: bool = False
    dry_run_default: bool = False
    requires_trust_tier: str = "T2"
    requires_scope: tuple[str, ...] = ()
    next_actions_hint: tuple[str, ...] = ()
    version: str = "1.0.0"
    scope: str = "builtin"  # builtin | tenant | user


def playbook(
    name: str,
    *,
    description: str = "",
    writes: bool = False,
    input_schema: dict[str, Any] | None = None,
    dry_run_default: bool = False,
    requires_trust_tier: str = "T2",
    requires_scope: tuple[str, ...] = (),
    next_actions_hint: tuple[str, ...] = (),
    version: str = "1.0.0",
    scope: str = "builtin",
) -> Callable[
    [Callable[..., Coroutine[Any, Any, Brief]]],
    Callable[..., Coroutine[Any, Any, Brief]],
]:
    """Attach a PlaybookDefinition to an async playbook function.

    Usage::

        @playbook("review_pull_request", writes=False, description="…")
        async def review_pull_request(inputs, ctx) -> Brief:
            ...

    For `writes=True`, a `dry_run: bool` property is added to the input
    schema (with `dry_run_default` as default) unless the caller already
    declared one.
    """

    def wrapper(
        fn: Callable[..., Coroutine[Any, Any, Brief]],
    ) -> Callable[..., Coroutine[Any, Any, Brief]]:
        schema = _normalize_schema(input_schema)
        if writes:
            _inject_dry_run(schema, default=dry_run_default)
        definition = PlaybookDefinition(
            name=name,
            description=description or (fn.__doc__ or "").strip(),
            input_schema=schema,
            writes=writes,
            dry_run_default=dry_run_default,
            requires_trust_tier=requires_trust_tier,
            requires_scope=requires_scope,
            next_actions_hint=next_actions_hint,
            version=version,
            scope=scope,
        )
        fn._playbook_definition = definition  # type: ignore[attr-defined]
        return fn

    return wrapper


def get_definition(fn: Callable[..., Any]) -> PlaybookDefinition | None:
    """Return the PlaybookDefinition attached to a decorated function."""
    return getattr(fn, "_playbook_definition", None)


def _normalize_schema(schema: dict[str, Any] | None) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "type": "object",
        "properties": {},
        "required": [],
    }
    if schema is None:
        return normalized
    normalized["type"] = schema.get("type", "object")
    normalized["properties"] = dict(schema.get("properties", {}))
    normalized["required"] = list(schema.get("required", []))
    return normalized


def _inject_dry_run(schema: dict[str, Any], *, default: bool) -> None:
    properties: dict[str, Any] = schema.setdefault("properties", {})
    if "dry_run" in properties:
        return
    prop = dict(_DRY_RUN_PROPERTY)
    prop["default"] = default
    properties["dry_run"] = prop
