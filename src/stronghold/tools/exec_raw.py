"""exec_raw: escape-hatch shell executor for cases exec_shell playbook misses.

Thin wrapper around ShellExecutor (shell_exec.py:134) with the same
shell-metacharacter denylist. Kept as a separate `*_raw` surface so the
playbook count stays bounded per the plan.
"""

from __future__ import annotations

import logging
from typing import Any

from stronghold.tools.shell_exec import SHELL_TOOL_DEF, ShellExecutor
from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.exec_raw")

EXEC_RAW_TOOL_DEF = ToolDefinition(
    name="exec_raw",
    description=(
        "Raw shell command execution (use only when exec_shell playbook "
        "doesn't cover the need). Same sandbox and metacharacter rules as "
        "the shell tool apply. T1 trust tier only."
    ),
    parameters=dict(SHELL_TOOL_DEF.parameters),
)


class ExecRawExecutor:
    """ToolExecutor wrapping ShellExecutor with explicit audit logging."""

    def __init__(self) -> None:
        self._inner = ShellExecutor()

    @property
    def name(self) -> str:
        return "exec_raw"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        cmd = arguments.get("cmd", "")
        logger.info("exec_raw cmd=%s", cmd)
        return await self._inner.execute(arguments)
