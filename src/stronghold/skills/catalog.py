"""Skill Catalog — multi-tenant cascade with filesystem watching.

ADR-K8S-022: skills are markdown documents with YAML frontmatter.
Cascade resolution: user > tenant > builtin (same pattern as Tool Catalog).
Filesystem watcher detects new/modified skill files without restart.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from stronghold.skills.parser import parse_skill_file
from stronghold.types.skill import SkillDefinition

logger = logging.getLogger("stronghold.skills.catalog")

_SCOPE_PRIORITY = {"builtin": 0, "tenant": 1, "user": 2}


@dataclass(frozen=True)
class SkillCatalogEntry:
    """A skill registered in the catalog with scope metadata."""

    definition: SkillDefinition
    version: str = "1.0.0"
    scope: str = "builtin"  # "builtin" | "tenant" | "user"
    tenant_id: str = ""
    user_id: str = ""


class SkillCatalog:
    """Multi-tenant skill catalog with cascade resolution and filesystem watching."""

    def __init__(self) -> None:
        self._entries: list[SkillCatalogEntry] = []
        self._lock = threading.RLock()
        self._watcher_thread: threading.Thread | None = None
        self._watch_stop = threading.Event()
        self._file_mtimes: dict[str, float] = {}

    def register(self, entry: SkillCatalogEntry) -> None:
        with self._lock:
            self._entries.append(entry)

    def resolve(
        self, skill_name: str, tenant_id: str = "", user_id: str = "",
    ) -> SkillCatalogEntry | None:
        """Resolve a skill by name with cascade: user > tenant > builtin."""
        candidates: list[SkillCatalogEntry] = []
        with self._lock:
            for entry in self._entries:
                if entry.definition.name != skill_name:
                    continue
                if entry.scope == "user" and entry.user_id == user_id and user_id:
                    candidates.append(entry)
                elif entry.scope == "tenant" and entry.tenant_id == tenant_id and tenant_id:
                    candidates.append(entry)
                elif entry.scope == "builtin":
                    candidates.append(entry)

        if not candidates:
            return None
        candidates.sort(key=lambda e: _SCOPE_PRIORITY.get(e.scope, 0), reverse=True)
        return candidates[0]

    def list_skills(
        self, tenant_id: str = "", user_id: str = "",
    ) -> list[SkillCatalogEntry]:
        """Return all skills visible to this tenant/user, deduplicated by name."""
        seen: dict[str, SkillCatalogEntry] = {}
        with self._lock:
            for entry in self._entries:
                name = entry.definition.name
                visible = False
                if entry.scope == "builtin":
                    visible = True
                elif entry.scope == "tenant" and entry.tenant_id == tenant_id and tenant_id:
                    visible = True
                elif entry.scope == "user" and entry.user_id == user_id and user_id:
                    visible = True
                if not visible:
                    continue
                existing = seen.get(name)
                if existing is None or _SCOPE_PRIORITY.get(entry.scope, 0) > _SCOPE_PRIORITY.get(
                    existing.scope, 0
                ):
                    seen[name] = entry
        return sorted(seen.values(), key=lambda e: e.definition.name)

    def load_directory(self, directory: str | Path, scope: str = "builtin",
                       tenant_id: str = "", user_id: str = "") -> int:
        """Load all .md skill files from a directory. Returns count loaded."""
        directory = Path(directory)
        if not directory.is_dir():
            return 0
        count = 0
        for path in sorted(directory.glob("*.md")):
            try:
                content = path.read_text(encoding="utf-8")
                skill_def = parse_skill_file(content)
                if skill_def is None:
                    logger.warning("Skill parse returned None: %s", path)
                    continue
                entry = SkillCatalogEntry(
                    definition=skill_def,
                    scope=scope,
                    tenant_id=tenant_id,
                    user_id=user_id,
                )
                self.register(entry)
                self._file_mtimes[str(path)] = path.stat().st_mtime
                count += 1
            except Exception:
                logger.warning("Failed to parse skill: %s", path, exc_info=True)
        return count

    def start_watching(self, directory: str | Path, poll_interval: float = 2.0) -> None:
        """Start a background thread that watches for skill file changes."""
        if self._watcher_thread and self._watcher_thread.is_alive():
            return
        self._watch_stop.clear()
        self._watcher_thread = threading.Thread(
            target=self._watch_loop,
            args=(Path(directory), poll_interval),
            daemon=True,
            name="skill-catalog-watcher",
        )
        self._watcher_thread.start()

    def stop_watching(self) -> None:
        self._watch_stop.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=5.0)

    def _watch_loop(self, directory: Path, interval: float) -> None:
        while not self._watch_stop.is_set():
            try:
                self._check_for_changes(directory)
            except Exception:
                logger.warning("Skill watcher error", exc_info=True)
            self._watch_stop.wait(interval)

    def _check_for_changes(self, directory: Path) -> None:
        if not directory.is_dir():
            return
        for path in directory.glob("*.md"):
            key = str(path)
            mtime = path.stat().st_mtime
            old_mtime = self._file_mtimes.get(key)
            if old_mtime is None or mtime > old_mtime:
                try:
                    content = path.read_text(encoding="utf-8")
                    skill_def = parse_skill_file(content)
                    entry = SkillCatalogEntry(definition=skill_def, scope="builtin")
                    # Remove old entry with same name + scope
                    with self._lock:
                        self._entries = [
                            e for e in self._entries
                            if not (e.definition.name == skill_def.name and e.scope == "builtin")
                        ]
                    self.register(entry)
                    self._file_mtimes[key] = mtime
                    logger.info("Reloaded skill: %s from %s", skill_def.name, path.name)
                except Exception:
                    logger.warning("Failed to reload skill: %s", path, exc_info=True)
