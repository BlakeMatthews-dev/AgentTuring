"""ObsidianWriter: writes markdown notes to an Obsidian vault directory.

Vault is just a directory of markdown files. Notes carry YAML front-matter
the vault's plugins can consume (Dataview, etc.). File name shape:

    <YYYY-MM-DD>/<HHMMSS>-<slug>.md

so a vault rendered as a daily note tree shows the self's activity by day.

Real, no auth, no network — the simplest write target. If your vault is
Obsidian Sync'd or git'd, the writes propagate without anything else from us.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.obsidian")


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str, *, max_len: int = 40) -> str:
    s = _SLUG_RE.sub("-", text.lower()).strip("-")
    return s[:max_len] or "note"


class ObsidianWriter:
    name = "obsidian_writer"
    mode = ToolMode.WRITE

    def __init__(
        self,
        *,
        vault_dir: str | Path,
        subdir: str | None = "Project Turing",
    ) -> None:
        self._vault = Path(vault_dir)
        self._subdir = subdir
        self._vault.mkdir(parents=True, exist_ok=True)

    def invoke(
        self,
        *,
        title: str,
        content: str,
        tags: list[str] | None = None,
        kind: str = "note",
        front_matter: dict[str, Any] | None = None,
    ) -> str:
        now = datetime.now(UTC)
        date_dir = now.strftime("%Y-%m-%d")
        time_part = now.strftime("%H%M%S")
        slug = _slugify(title)
        target_dir = self._vault
        if self._subdir:
            target_dir = target_dir / self._subdir
        target_dir = target_dir / date_dir
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{time_part}-{slug}.md"
        path = target_dir / filename
        if path.exists():
            logger.debug("obsidian note already exists, skipping: %s", path)
            return str(path)

        fm = {
            "title": title,
            "kind": kind,
            "created": now.isoformat(),
            "tags": list(tags or []),
        }
        if front_matter:
            fm.update(front_matter)

        body_lines: list[str] = ["---"]
        for key, value in fm.items():
            if isinstance(value, list):
                body_lines.append(f"{key}: [{', '.join(map(str, value))}]")
            else:
                body_lines.append(f"{key}: {value}")
        body_lines.append("---")
        body_lines.append("")
        body_lines.append(f"# {title}")
        body_lines.append("")
        body_lines.append(content.rstrip())
        body_lines.append("")

        path.write_text("\n".join(body_lines), encoding="utf-8")
        logger.info("wrote obsidian note %s", path)
        return str(path)
