"""WorkspaceOps: file read/write/git wrappers around tool_dispatcher.

Extracted from RuntimePipeline to enable isolated testing of file operations.
"""

from __future__ import annotations

from typing import Any


class WorkspaceOps:
    """Workspace file and git operations via tool_dispatcher."""

    def __init__(self, tool_dispatcher: Any) -> None:
        self._td = tool_dispatcher

    async def read_file(self, path: str, workspace: str) -> str:
        """Read a file from workspace. Returns content or empty string."""
        result = await self._td.execute(
            "file_ops", {"action": "read", "path": path, "workspace": workspace},
        )
        if result.startswith("Error:"):
            return ""
        return result

    async def write_file(self, path: str, content: str, workspace: str) -> str:
        """Write a file to workspace. Returns result string."""
        return await self._td.execute(
            "file_ops",
            {"action": "write", "path": path, "content": content, "workspace": workspace},
        )

    async def git_command(self, command: str, workspace: str) -> str:
        """Run a git command in workspace."""
        return await self._td.execute(
            "git", {"command": command, "workspace": workspace},
        )

    async def list_files(self, path: str, workspace: str) -> str:
        """List files in a directory."""
        return await self._td.execute(
            "shell",
            {"command": f"find {path} -type f -name '*.py' 2>/dev/null | head -50", "workspace": workspace},
        )
