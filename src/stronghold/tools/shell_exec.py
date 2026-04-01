"""Shell execution tool — run commands in a workspace.

Sandboxed to a workspace directory. Supports the quality gate
commands Mason needs: pytest, ruff, mypy, bandit, git.

Blocks dangerous commands (rm -rf /, etc.) via allowlist.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.shell")

SHELL_TOOL_DEF = ToolDefinition(
    name="shell",
    description=(
        "Run shell commands in the workspace. "
        "Supports: pytest, ruff, mypy, bandit, git, pip, ls, cat, grep, find."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute."},
            "workspace": {"type": "string", "description": "Working directory."},
        },
        "required": ["command", "workspace"],
    },
    groups=("code_gen",),
)

# Quality gate convenience tools — map to shell commands
RUN_PYTEST_DEF = ToolDefinition(
    name="run_pytest",
    description="Run pytest in the workspace.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Test path (default: tests/)"},
            "workspace": {"type": "string"},
        },
        "required": ["workspace"],
    },
    groups=("code_gen",),
)

RUN_RUFF_CHECK_DEF = ToolDefinition(
    name="run_ruff_check",
    description="Run ruff check on src/.",
    parameters={
        "type": "object",
        "properties": {"workspace": {"type": "string"}},
        "required": ["workspace"],
    },
    groups=("code_gen",),
)

RUN_RUFF_FORMAT_DEF = ToolDefinition(
    name="run_ruff_format",
    description="Run ruff format --check on src/.",
    parameters={
        "type": "object",
        "properties": {"workspace": {"type": "string"}},
        "required": ["workspace"],
    },
    groups=("code_gen",),
)

RUN_MYPY_DEF = ToolDefinition(
    name="run_mypy",
    description="Run mypy --strict on src/stronghold/.",
    parameters={
        "type": "object",
        "properties": {"workspace": {"type": "string"}},
        "required": ["workspace"],
    },
    groups=("code_gen",),
)

RUN_BANDIT_DEF = ToolDefinition(
    name="run_bandit",
    description="Run bandit -r src/stronghold/ -ll.",
    parameters={
        "type": "object",
        "properties": {"workspace": {"type": "string"}},
        "required": ["workspace"],
    },
    groups=("code_gen",),
)

# Commands that are allowed to run
_ALLOWED_PREFIXES = (
    "pytest",
    "python",
    "ruff",
    "mypy",
    "bandit",
    "git ",
    "git\t",
    "pip ",
    "ls",
    "cat ",
    "head ",
    "tail ",
    "grep ",
    "find ",
    "wc ",
    "diff ",
    "echo ",
    "mkdir ",
    "touch ",
    "cp ",
    "mv ",
)

_BLOCKED_PATTERNS = (
    "rm -rf /",
    "rm -rf /*",
    "dd if=",
    "mkfs",
    "> /dev/",
    "chmod 777 /",
    "curl | sh",
    "wget | sh",
)


class ShellExecutor:
    """Sandboxed shell command execution."""

    @property
    def name(self) -> str:
        return "shell"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = arguments.get("command", "")
        workspace = arguments.get("workspace", "")

        if not workspace:
            return ToolResult(success=False, error="workspace path required")

        ws = Path(workspace)
        if not ws.is_dir():
            return ToolResult(success=False, error=f"workspace not found: {workspace}")

        if not command.strip():
            return ToolResult(success=False, error="empty command")

        # Security: check allowlist
        cmd_lower = command.strip().lower()
        if not any(cmd_lower.startswith(p) for p in _ALLOWED_PREFIXES):
            return ToolResult(
                success=False,
                error="command not allowed. Use: pytest, ruff, mypy, bandit, git, pip, ls, grep",
            )

        for blocked in _BLOCKED_PATTERNS:
            if blocked in command:
                return ToolResult(success=False, error="blocked: dangerous command")

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                cwd=ws,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)

            output = stdout.decode("utf-8", errors="replace")
            errors = stderr.decode("utf-8", errors="replace")
            passed = proc.returncode == 0

            result = {
                "passed": passed,
                "exit_code": proc.returncode,
                "stdout": output[-3000:] if len(output) > 3000 else output,
                "stderr": errors[-1000:] if len(errors) > 1000 else errors,
            }
            return ToolResult(content=json.dumps(result), success=True)

        except TimeoutError:
            return ToolResult(success=False, error="command timed out (120s)")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class QualityGateExecutor:
    """Convenience executors for quality gate commands."""

    def __init__(self, shell: ShellExecutor) -> None:
        self._shell = shell

    def make_executor(self, command_template: str) -> Any:
        """Return an execute function for a quality gate command."""
        shell = self._shell

        async def _execute(arguments: dict[str, Any]) -> ToolResult:
            ws = arguments.get("workspace", "")
            path = arguments.get("path", "")
            if "{path}" in command_template:
                cmd = command_template.format(path=path)
            else:
                cmd = command_template
            return await shell.execute({"command": cmd, "workspace": ws})

        return _execute
