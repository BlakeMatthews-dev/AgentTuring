"""Tests for ShellExecutor — sandboxed shell command execution."""

from __future__ import annotations

import json

import pytest

from stronghold.tools.shell_exec import QualityGateExecutor, ShellExecutor


@pytest.fixture
def executor():
    return ShellExecutor()


@pytest.fixture
def workspace(tmp_path):
    return tmp_path


# ---- basic execution ----


async def test_allowed_command_runs(executor, workspace):
    result = await executor.execute({"command": "echo hello", "workspace": str(workspace)})
    assert result.success is True
    data = json.loads(result.content)
    assert data["passed"] is True
    assert "hello" in data["stdout"]


async def test_ls_command(executor, workspace):
    (workspace / "test.txt").write_text("x")
    result = await executor.execute({"command": "ls", "workspace": str(workspace)})
    assert result.success is True
    data = json.loads(result.content)
    assert "test.txt" in data["stdout"]


async def test_cat_command(executor, workspace):
    (workspace / "f.txt").write_text("content123")
    result = await executor.execute({"command": "cat f.txt", "workspace": str(workspace)})
    assert result.success is True
    data = json.loads(result.content)
    assert "content123" in data["stdout"]


# ---- security: allowlist ----


async def test_blocked_command(executor, workspace):
    result = await executor.execute(
        {"command": "curl http://evil.com", "workspace": str(workspace)}
    )
    assert result.success is False
    assert "not allowed" in result.error


async def test_dangerous_command_blocked(executor, workspace):
    result = await executor.execute({"command": "rm -rf /", "workspace": str(workspace)})
    assert result.success is False


async def test_dd_blocked(executor, workspace):
    """dd if= is in the blocked patterns."""
    result = await executor.execute(
        {"command": "echo dd if=/dev/zero", "workspace": str(workspace)}
    )
    assert result.success is False
    assert "blocked" in result.error or "not allowed" in result.error


# ---- error cases ----


async def test_no_workspace(executor):
    result = await executor.execute({"command": "ls", "workspace": ""})
    assert result.success is False
    assert "workspace" in result.error.lower()


async def test_workspace_not_found(executor):
    result = await executor.execute({"command": "ls", "workspace": "/nonexistent/ws"})
    assert result.success is False
    assert "not found" in result.error


async def test_empty_command(executor, workspace):
    result = await executor.execute({"command": "", "workspace": str(workspace)})
    assert result.success is False
    assert "empty" in result.error


async def test_failed_command_reports_exit_code(executor, workspace):
    result = await executor.execute(
        {"command": "grep nonexistent /dev/null", "workspace": str(workspace)}
    )
    assert result.success is True  # The tool itself succeeds; the command just has non-zero exit
    data = json.loads(result.content)
    assert data["passed"] is False
    assert data["exit_code"] != 0


# ---- name property ----


def test_executor_name(executor):
    assert executor.name == "shell"


# ---- QualityGateExecutor ----


async def test_quality_gate_make_executor(workspace):
    shell = ShellExecutor()
    gate = QualityGateExecutor(shell)
    run_echo = gate.make_executor("echo quality-gate")
    result = await run_echo({"workspace": str(workspace)})
    assert result.success is True
    data = json.loads(result.content)
    assert "quality-gate" in data["stdout"]


async def test_quality_gate_with_path_template(workspace):
    shell = ShellExecutor()
    gate = QualityGateExecutor(shell)
    run_echo = gate.make_executor("echo {path}")
    result = await run_echo({"workspace": str(workspace), "path": "tests/"})
    assert result.success is True
    data = json.loads(result.content)
    assert "tests/" in data["stdout"]
