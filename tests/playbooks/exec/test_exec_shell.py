"""exec_shell playbook: dry_run preview + live execution path."""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.playbooks.exec.exec_shell import ExecShellPlaybook, exec_shell
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.types.auth import SYSTEM_AUTH
from stronghold.types.tool import ToolResult


class _FakeShell:
    def __init__(self, result: ToolResult) -> None:
        self._result = result
        self.calls: list[dict[str, Any]] = []

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        self.calls.append(arguments)
        return self._result


def _ctx() -> PlaybookContext:
    return PlaybookContext(auth=SYSTEM_AUTH)


async def test_dry_run_renders_plan_without_shell_call(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeShell(ToolResult(content="", success=True))
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.exec.exec_shell"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    brief = await exec_shell(
        {"command": "echo hi", "workspace": "/tmp", "dry_run": True},
        _ctx(),
    )
    assert "Dry-run" in brief.title
    assert "echo hi" in brief.to_markdown()
    assert fake.calls == []


async def test_live_execution_captures_output(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeShell(ToolResult(content="hello world\n", success=True))
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.exec.exec_shell"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    brief = await exec_shell(
        {"command": "echo hello world", "workspace": "/tmp", "dry_run": False},
        _ctx(),
    )
    assert "exec_shell: echo hello" in brief.title
    assert "hello world" in brief.to_markdown()
    assert brief.flags == ()


async def test_failure_surfaces_as_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeShell(ToolResult(success=False, error="exit 1"))
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.exec.exec_shell"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    brief = await exec_shell(
        {"command": "false", "workspace": "/tmp", "dry_run": False},
        _ctx(),
    )
    assert "failed" in brief.summary
    assert brief.flags == ("exit 1",)


async def test_empty_cmd_rejected() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        await exec_shell({"command": "", "workspace": "/tmp"}, _ctx())


async def test_output_truncated_when_huge(monkeypatch: pytest.MonkeyPatch) -> None:
    huge = "x" * 10_000
    fake = _FakeShell(ToolResult(content=huge, success=True))
    import sys  # noqa: PLC0415

    mod = sys.modules["stronghold.playbooks.exec.exec_shell"]
    monkeypatch.setattr(mod, "ShellExecutor", lambda: fake)
    brief = await exec_shell(
        {"command": "cat big", "workspace": "/tmp", "dry_run": False},
        _ctx(),
    )
    assert "(truncated)" in brief.to_markdown()


def test_playbook_class_has_definition() -> None:
    pb = ExecShellPlaybook()
    assert pb.definition.name == "exec_shell"
    assert pb.definition.writes is True
