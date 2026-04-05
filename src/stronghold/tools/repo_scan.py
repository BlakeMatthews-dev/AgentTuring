"""Read-only repository scanning tools for codebase exploration.

Provides glob, grep, and read_file tools sandboxed to a workspace directory.
These are intentionally read-only -- no writes, no deletes, no shell escapes.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import re
from pathlib import Path
from typing import Any

from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.repo_scan")

# Directories to always skip when scanning
_SKIP_DIRS = frozenset({
    ".git", "__pycache__", ".mypy_cache", ".ruff_cache",
    "node_modules", ".tox", ".pytest_cache", ".venv", "venv",
    ".eggs", "*.egg-info",
})

GLOB_FILES_DEF = ToolDefinition(
    name="glob_files",
    description=(
        "Find files matching a glob pattern in the workspace. "
        "Returns a list of relative paths. "
        "Example patterns: '**/*.py', 'src/**/*.yaml', 'tests/test_*.py'."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern to match (e.g. '**/*.py', 'src/**/models/*.py').",
            },
            "workspace": {"type": "string", "description": "Workspace root path."},
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results to return (default 200).",
            },
        },
        "required": ["pattern", "workspace"],
    },
    groups=("exploration",),
)

GREP_CONTENT_DEF = ToolDefinition(
    name="grep_content",
    description=(
        "Search file contents for a regex pattern in the workspace. "
        "Returns matching lines with file path and line number. "
        "Supports standard Python regex syntax."
    ),
    parameters={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": (
                    "Regex pattern to search for "
                    "(e.g. 'class.*Protocol', 'def execute')."
                ),
            },
            "workspace": {"type": "string", "description": "Workspace root path."},
            "glob": {
                "type": "string",
                "description": (
                    "Optional file glob to restrict search "
                    "(e.g. '**/*.py'). Default: all text files."
                ),
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching lines to return (default 100).",
            },
            "context_lines": {
                "type": "integer",
                "description": "Number of context lines before and after each match (default 0).",
            },
            "case_insensitive": {
                "type": "boolean",
                "description": "Case-insensitive matching (default false).",
            },
        },
        "required": ["pattern", "workspace"],
    },
    groups=("exploration",),
)

READ_FILE_DEF = ToolDefinition(
    name="read_file",
    description=(
        "Read the contents of a file in the workspace. "
        "Supports offset and limit for reading portions of large files. "
        "Returns numbered lines."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path within workspace."},
            "workspace": {"type": "string", "description": "Workspace root path."},
            "offset": {
                "type": "integer",
                "description": "Line number to start reading from (0-based, default 0).",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of lines to return (default 500).",
            },
        },
        "required": ["path", "workspace"],
    },
    groups=("exploration",),
)


def _sandbox(workspace: str, rel_path: str) -> tuple[Path, Path] | None:
    """Resolve and sandbox a path. Returns (ws, target) or None if escape."""
    ws = Path(workspace).resolve()
    target = (ws / rel_path).resolve()
    if not str(target).startswith(str(ws)):
        return None
    return ws, target


def _should_skip(path: Path) -> bool:
    """Check if any path component matches skip patterns."""
    for part in path.parts:
        if part in _SKIP_DIRS:
            return True
        for pattern in _SKIP_DIRS:
            if "*" in pattern and fnmatch.fnmatch(part, pattern):
                return True
    return False


def _is_text_file(path: Path) -> bool:
    """Best-effort check if a file is text (not binary)."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(8192)
        return b"\x00" not in chunk
    except OSError:
        return False


class GlobFilesExecutor:
    """Find files matching a glob pattern."""

    @property
    def name(self) -> str:
        return "glob_files"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pattern = arguments.get("pattern", "")
        workspace = arguments.get("workspace", "")
        max_results = arguments.get("max_results", 200)

        if not workspace:
            return ToolResult(success=False, error="workspace path required")
        if not pattern:
            return ToolResult(success=False, error="pattern required")

        ws = Path(workspace).resolve()
        if not ws.is_dir():
            return ToolResult(success=False, error=f"workspace not found: {workspace}")

        try:
            matches = []
            for path in ws.glob(pattern):
                if not path.is_file():
                    continue
                if _should_skip(path.relative_to(ws)):
                    continue
                matches.append(str(path.relative_to(ws)))
                if len(matches) >= max_results:
                    break

            matches.sort()
            return ToolResult(
                content=json.dumps({"count": len(matches), "files": matches}),
                success=True,
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GrepContentExecutor:
    """Search file contents for a regex pattern."""

    @property
    def name(self) -> str:
        return "grep_content"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pattern = arguments.get("pattern", "")
        workspace = arguments.get("workspace", "")
        file_glob = arguments.get("glob", "**/*")
        max_results = arguments.get("max_results", 100)
        context_lines = arguments.get("context_lines", 0)
        case_insensitive = arguments.get("case_insensitive", False)

        if not workspace:
            return ToolResult(success=False, error="workspace path required")
        if not pattern:
            return ToolResult(success=False, error="pattern required")

        ws = Path(workspace).resolve()
        if not ws.is_dir():
            return ToolResult(success=False, error=f"workspace not found: {workspace}")

        flags = re.IGNORECASE if case_insensitive else 0
        try:
            regex = re.compile(pattern, flags)
        except re.error as e:
            return ToolResult(success=False, error=f"invalid regex: {e}")

        results: list[dict[str, Any]] = []
        try:
            for path in ws.glob(file_glob):
                if not path.is_file() or _should_skip(path.relative_to(ws)):
                    continue
                if not _is_text_file(path):
                    continue

                try:
                    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue

                for i, line in enumerate(lines):
                    if regex.search(line):
                        match_entry: dict[str, Any] = {
                            "file": str(path.relative_to(ws)),
                            "line": i + 1,
                            "content": line.rstrip(),
                        }
                        if context_lines > 0:
                            start = max(0, i - context_lines)
                            end = min(len(lines), i + context_lines + 1)
                            match_entry["context"] = [
                                f"{j + 1}: {lines[j].rstrip()}"
                                for j in range(start, end)
                            ]
                        results.append(match_entry)
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break

            return ToolResult(
                content=json.dumps({"count": len(results), "matches": results}),
                success=True,
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class ReadFileExecutor:
    """Read file contents (read-only, no write capability)."""

    @property
    def name(self) -> str:
        return "read_file"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        rel_path = arguments.get("path", "")
        workspace = arguments.get("workspace", "")
        offset = arguments.get("offset", 0)
        limit = arguments.get("limit", 500)

        if not workspace:
            return ToolResult(success=False, error="workspace path required")
        if not rel_path:
            return ToolResult(success=False, error="path required")

        result = _sandbox(workspace, rel_path)
        if result is None:
            return ToolResult(success=False, error="path escapes workspace")
        _ws, target = result

        if not target.exists():
            return ToolResult(success=False, error=f"file not found: {rel_path}")
        if not target.is_file():
            return ToolResult(success=False, error=f"not a file: {rel_path}")

        try:
            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total = len(lines)
            selected = lines[offset : offset + limit]
            numbered = [
                f"{offset + i + 1}\t{line}" for i, line in enumerate(selected)
            ]
            return ToolResult(
                content=json.dumps({
                    "path": rel_path,
                    "total_lines": total,
                    "showing": f"{offset + 1}-{offset + len(selected)}",
                    "content": "\n".join(numbered),
                }),
                success=True,
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
