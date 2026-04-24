"""fs_raw: escape-hatch file-system tool for cases no workspace playbook covers.

Thin wrapper around FileOpsExecutor (file_ops.py:40) with the same
sandbox boundaries. Kept as a separate `*_raw` surface per the plan so
the playbook count stays bounded.
"""

from __future__ import annotations

import logging
from typing import Any

from stronghold.tools.file_ops import FILE_OPS_TOOL_DEF, FileOpsExecutor
from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.fs_raw")

FS_RAW_TOOL_DEF = ToolDefinition(
    name="fs_raw",
    description=(
        "Raw filesystem operations in the workspace. Use only when no "
        "workspace playbook covers the need. Actions: read, write, list, "
        "mkdir, exists. T1 trust tier only."
    ),
    parameters=dict(FILE_OPS_TOOL_DEF.parameters),
)


class FsRawExecutor:
    """ToolExecutor wrapping FileOpsExecutor with explicit audit logging."""

    def __init__(self) -> None:
        self._inner = FileOpsExecutor()

    @property
    def name(self) -> str:
        return "fs_raw"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        path = arguments.get("path", "")
        workspace = arguments.get("workspace", "")
        logger.info("fs_raw action=%s workspace=%s path=%s", action, workspace, path)
        return await self._inner.execute(arguments)
