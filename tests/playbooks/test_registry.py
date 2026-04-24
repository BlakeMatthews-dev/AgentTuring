"""InMemoryPlaybookRegistry: register, get, list, duplicate detection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from stronghold.playbooks.base import PlaybookDefinition
from stronghold.playbooks.brief import Brief
from stronghold.playbooks.registry import DuplicatePlaybookError, InMemoryPlaybookRegistry

if TYPE_CHECKING:
    from stronghold.protocols.playbooks import PlaybookContext


class _FakePlaybook:
    def __init__(self, name: str) -> None:
        self.definition = PlaybookDefinition(name=name, description=f"pb {name}")

    async def execute(self, _inputs: dict[str, Any], _ctx: PlaybookContext) -> Brief:
        return Brief(title=self.definition.name)


def test_register_and_get_returns_executor() -> None:
    reg = InMemoryPlaybookRegistry()
    pb = _FakePlaybook("review_pr")
    reg.register(pb)
    got = reg.get("review_pr")
    assert got is pb


def test_get_unknown_returns_none() -> None:
    reg = InMemoryPlaybookRegistry()
    assert reg.get("missing") is None


def test_duplicate_registration_raises() -> None:
    reg = InMemoryPlaybookRegistry()
    reg.register(_FakePlaybook("dup"))
    with pytest.raises(DuplicatePlaybookError):
        reg.register(_FakePlaybook("dup"))


def test_list_all_returns_definitions() -> None:
    reg = InMemoryPlaybookRegistry()
    reg.register(_FakePlaybook("a"))
    reg.register(_FakePlaybook("b"))
    names = sorted(d.name for d in reg.list_all())
    assert names == ["a", "b"]


def test_contains_and_len() -> None:
    reg = InMemoryPlaybookRegistry()
    assert len(reg) == 0
    reg.register(_FakePlaybook("x"))
    assert "x" in reg
    assert "y" not in reg
    assert len(reg) == 1


def test_names_returns_registered_names() -> None:
    reg = InMemoryPlaybookRegistry()
    reg.register(_FakePlaybook("one"))
    reg.register(_FakePlaybook("two"))
    assert sorted(reg.names()) == ["one", "two"]
