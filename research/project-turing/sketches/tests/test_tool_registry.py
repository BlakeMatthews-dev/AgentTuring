"""Tests for runtime/tools/base.py — registry + allowlist."""

from __future__ import annotations

from typing import Any

import pytest

from turing.runtime.tools.base import Tool, ToolMode, ToolNotPermitted, ToolRegistry


class _Echo:
    name = "echo"
    mode = ToolMode.READ

    def invoke(self, **kwargs: Any) -> Any:
        return kwargs


def test_registered_tool_invokes() -> None:
    reg = ToolRegistry()
    reg.register(_Echo())
    assert reg.invoke("echo", x=1, y=2) == {"x": 1, "y": 2}


def test_unregistered_tool_raises_not_permitted() -> None:
    reg = ToolRegistry()
    with pytest.raises(ToolNotPermitted, match="not registered"):
        reg.invoke("anything", x=1)


def test_double_registration_rejected() -> None:
    reg = ToolRegistry()
    reg.register(_Echo())
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_Echo())


def test_names_by_mode() -> None:
    class _W:
        name = "writer"
        mode = ToolMode.WRITE

        def invoke(self, **kwargs: Any) -> Any:
            return None

    reg = ToolRegistry()
    reg.register(_Echo())
    reg.register(_W())
    assert reg.names_by_mode(ToolMode.WRITE) == ["writer"]
    assert reg.names_by_mode(ToolMode.READ) == ["echo"]
