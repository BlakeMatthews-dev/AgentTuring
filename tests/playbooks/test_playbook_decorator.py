"""@playbook decorator: definition attachment, dry-run injection, defaults."""

from __future__ import annotations

from typing import Any

from stronghold.playbooks.base import PlaybookDefinition, get_definition, playbook
from stronghold.playbooks.brief import Brief


@playbook("noop", description="A minimal read-only playbook for tests.")
async def _noop(_inputs: dict[str, Any], _ctx: Any) -> Brief:
    return Brief(title="noop")


@playbook(
    "writes_noop",
    writes=True,
    input_schema={
        "type": "object",
        "properties": {"repo": {"type": "string"}},
        "required": ["repo"],
    },
)
async def _writes_noop(_inputs: dict[str, Any], _ctx: Any) -> Brief:
    return Brief(title="writes")


@playbook(
    "writes_with_explicit_dry_run",
    writes=True,
    input_schema={
        "type": "object",
        "properties": {
            "dry_run": {"type": "boolean", "description": "custom"},
        },
    },
)
async def _writes_explicit(_inputs: dict[str, Any], _ctx: Any) -> Brief:
    return Brief(title="explicit")


def test_decorator_attaches_definition() -> None:
    d = get_definition(_noop)
    assert isinstance(d, PlaybookDefinition)
    assert d.name == "noop"
    assert d.description == "A minimal read-only playbook for tests."
    assert d.writes is False
    assert d.scope == "builtin"


def test_decorator_uses_docstring_when_description_missing() -> None:
    @playbook("from_docstring")
    async def fn(_inputs: dict[str, Any], _ctx: Any) -> Brief:
        """Docstring description wins when no explicit description."""
        return Brief(title="t")

    d = get_definition(fn)
    assert d is not None
    assert d.description == "Docstring description wins when no explicit description."


def test_writes_playbook_auto_injects_dry_run() -> None:
    d = get_definition(_writes_noop)
    assert d is not None
    assert d.writes is True
    props = d.input_schema["properties"]
    assert "dry_run" in props
    assert props["dry_run"]["type"] == "boolean"
    assert props["dry_run"]["default"] is False
    # Existing properties preserved
    assert "repo" in props
    assert "repo" in d.input_schema["required"]


def test_existing_dry_run_property_is_not_overwritten() -> None:
    d = get_definition(_writes_explicit)
    assert d is not None
    assert d.input_schema["properties"]["dry_run"]["description"] == "custom"


def test_read_only_playbook_does_not_inject_dry_run() -> None:
    d = get_definition(_noop)
    assert d is not None
    assert "dry_run" not in d.input_schema["properties"]


def test_dry_run_default_respects_parameter() -> None:
    @playbook("writes_default_true", writes=True, dry_run_default=True)
    async def fn(_inputs: dict[str, Any], _ctx: Any) -> Brief:
        return Brief(title="t")

    d = get_definition(fn)
    assert d is not None
    assert d.input_schema["properties"]["dry_run"]["default"] is True
    assert d.dry_run_default is True


def test_get_definition_returns_none_for_undecorated() -> None:
    async def plain(_inputs: dict[str, Any], _ctx: Any) -> Brief:
        return Brief(title="t")

    assert get_definition(plain) is None


def test_scope_and_trust_tier_defaults() -> None:
    d = get_definition(_noop)
    assert d is not None
    assert d.scope == "builtin"
    assert d.requires_trust_tier == "T2"
    assert d.requires_scope == ()
