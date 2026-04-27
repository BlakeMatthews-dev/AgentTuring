"""CodeReader: read-only access to Turing's own source code.

The self can inspect its own codebase — the same files that define how it
thinks, dreams, and responds. This is the foundation for self-reflection,
metacognition, and requesting changes through Stronghold.

Safety constraints:
  - READ-ONLY: no write, no delete, no execute.
  - Path is sandboxed to /app/sketches/turing/ — cannot escape to host.
  - Max file size: 100 KB (larger files return truncated).
  - List mode: returns directory contents without reading files.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.code_reader")

_SANDBOX_ROOT = Path("/app/sketches/turing")
_MAX_BYTES = 100_000


class CodeReader:
    name = "code_reader"
    mode = ToolMode.READ

    def invoke(
        self,
        *,
        path: str = "",
        action: str = "read",
    ) -> dict[str, Any]:
        target = self._resolve(path)
        if target is None:
            return {"error": f"path escapes sandbox: {path!r}"}

        if action == "list":
            return self._list(target, path)
        return self._read(target, path)

    def _resolve(self, path: str) -> Path | None:
        target = (_SANDBOX_ROOT / path).resolve()
        try:
            target.relative_to(_SANDBOX_ROOT.resolve())
        except ValueError:
            return None
        return target

    def _list(self, target: Path, logical: str) -> dict[str, Any]:
        if not target.exists():
            return {"error": f"path not found: {logical!r}"}
        if target.is_file():
            return {"type": "file", "path": logical}
        entries = []
        for child in sorted(target.iterdir()):
            rel = str(child.relative_to(_SANDBOX_ROOT))
            entries.append(
                {
                    "name": child.name,
                    "path": rel,
                    "type": "dir" if child.is_dir() else "file",
                }
            )
        return {"type": "dir", "path": logical or ".", "entries": entries}

    def _read(self, target: Path, logical: str) -> dict[str, Any]:
        if not target.exists():
            return {"error": f"path not found: {logical!r}"}
        if target.is_dir():
            return self._list(target, logical)
        try:
            raw = target.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return {"error": str(exc)}
        truncated = len(raw) > _MAX_BYTES
        content = raw[:_MAX_BYTES]
        return {
            "type": "file",
            "path": logical,
            "lines": content.count("\n") + 1,
            "truncated": truncated,
            "content": content,
        }
