"""fs_raw and exec_raw escape hatches: thin pass-throughs with audit logs."""

from __future__ import annotations

import tempfile
from pathlib import Path

from stronghold.tools.exec_raw import EXEC_RAW_TOOL_DEF, ExecRawExecutor
from stronghold.tools.fs_raw import FS_RAW_TOOL_DEF, FsRawExecutor


async def test_fs_raw_definition_mirrors_file_ops() -> None:
    assert FS_RAW_TOOL_DEF.name == "fs_raw"
    assert "action" in FS_RAW_TOOL_DEF.parameters["properties"]


async def test_fs_raw_write_then_read_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        executor = FsRawExecutor()
        write_result = await executor.execute(
            {
                "action": "write",
                "workspace": workspace,
                "path": "hello.txt",
                "content": "greetings",
            }
        )
        assert write_result.success is True

        read_result = await executor.execute(
            {"action": "read", "workspace": workspace, "path": "hello.txt"},
        )
        assert read_result.success is True
        assert read_result.content == "greetings"
        assert (Path(workspace) / "hello.txt").read_text() == "greetings"


async def test_fs_raw_rejects_path_outside_workspace() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        executor = FsRawExecutor()
        result = await executor.execute(
            {"action": "read", "workspace": workspace, "path": "../../../etc/passwd"},
        )
        assert result.success is False


def test_exec_raw_definition_mirrors_shell() -> None:
    assert EXEC_RAW_TOOL_DEF.name == "exec_raw"
    # ShellExecutor schema uses "command" (not "cmd").
    props = EXEC_RAW_TOOL_DEF.parameters["properties"]
    assert "command" in props or "cmd" in props


async def test_exec_raw_runs_allowlisted_command() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        executor = ExecRawExecutor()
        # ShellExecutor only allows pytest/ruff/mypy/bandit/git/pip/ls/grep.
        # `ls` is one of the safe allowlisted commands.
        result = await executor.execute({"command": "ls", "workspace": workspace})
        assert result.success is True


async def test_exec_raw_rejects_metacharacter_injection() -> None:
    with tempfile.TemporaryDirectory() as workspace:
        executor = ExecRawExecutor()
        result = await executor.execute({"command": "ls; rm -rf /", "workspace": workspace})
        assert result.success is False
        assert result.error is not None
        assert "metacharacter" in result.error
