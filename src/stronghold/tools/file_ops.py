"""File operations tool — read, write, list files in a workspace.

Sandboxed to a specific directory (the active worktree).
Cannot escape the workspace root.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.file_ops")

FILE_OPS_TOOL_DEF = ToolDefinition(
    name="file_ops",
    description=(
        "Read, write, and list files in the workspace. Actions: read, write, list, mkdir, exists."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["read", "write", "list", "mkdir", "exists"],
            },
            "path": {"type": "string", "description": "Relative path within workspace."},
            "content": {"type": "string", "description": "File content (for write)."},
            "workspace": {"type": "string", "description": "Workspace root path."},
        },
        "required": ["action", "path"],
    },
    groups=("code_gen",),
)


class FileOpsExecutor:
    """Sandboxed file operations within a workspace directory."""

    @property
    def name(self) -> str:
        return "file_ops"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action", "")
        rel_path = arguments.get("path", "")
        workspace = arguments.get("workspace", "")

        if not workspace:
            return ToolResult(success=False, error="workspace path required")

        ws = Path(workspace)
        if not ws.is_dir():
            return ToolResult(success=False, error=f"workspace not found: {workspace}")

        # Resolve and sandbox. Use is_relative_to (Path semantics) instead of
        # string startswith to prevent:
        #   - prefix collision attacks (/tmp/work vs /tmp/work-evil)
        #   - symlink escapes (symlink in workspace pointing outside)
        # Catch null bytes and other OS errors from resolve().
        try:
            ws_resolved = ws.resolve(strict=True)
            target = (ws / rel_path).resolve(strict=False)
        except (OSError, ValueError) as e:
            return ToolResult(success=False, error=f"invalid path: {e}")

        try:
            target.relative_to(ws_resolved)
        except ValueError:
            return ToolResult(success=False, error="path escapes workspace")

        try:
            if action == "read":
                if not target.exists():
                    return ToolResult(success=False, error=f"file not found: {rel_path}")
                content = target.read_text(encoding="utf-8")
                return ToolResult(content=content, success=True)

            if action == "write":
                file_content = arguments.get("content", "")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(file_content, encoding="utf-8")
                return ToolResult(
                    content=json.dumps(
                        {
                            "status": "ok",
                            "path": rel_path,
                            "bytes": len(file_content),
                        }
                    ),
                    success=True,
                )

            if action == "list":
                if not target.is_dir():
                    return ToolResult(success=False, error=f"not a directory: {rel_path}")
                entries = sorted(
                    str(p.relative_to(ws))
                    for p in target.rglob("*")
                    if p.is_file() and ".git" not in p.parts
                )
                return ToolResult(content=json.dumps(entries[:200]), success=True)

            if action == "mkdir":
                target.mkdir(parents=True, exist_ok=True)
                return ToolResult(content=json.dumps({"status": "ok"}), success=True)

            if action == "exists":
                return ToolResult(
                    content=json.dumps({"exists": target.exists(), "is_file": target.is_file()}),
                    success=True,
                )

            return ToolResult(success=False, error=f"unknown action: {action}")

        except Exception as e:
            return ToolResult(success=False, error=str(e))
