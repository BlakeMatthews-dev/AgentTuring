"""Newsletter content reader: scans vault directory for HuggingFace summaries.

Read-only tool. The agent has no email access. Summaries are written by an
external HuggingFace pipeline that parses, summarizes, Warden-scans, and
deposits markdown files into a known vault directory.

See specs/newsletter-reader.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.newsletter")


@dataclass(frozen=True)
class ParsedNewsletter:
    file_path: str
    title: str
    source: str
    received_at: datetime | None
    summary: str
    sentence_count: int
    tags: list[str]


class NewsletterContentReader:
    name = "newsletter_reader"
    mode = ToolMode.READ

    def __init__(self, *, vault_dir: str | Path) -> None:
        if not vault_dir:
            raise ValueError("vault_dir required")
        self._dir = Path(vault_dir)
        self._seen: dict[str, float] = {}

    def invoke(
        self,
        *,
        scan_mode: str = "incremental",
    ) -> list[ParsedNewsletter]:
        if not self._dir.is_dir():
            return []
        results: list[ParsedNewsletter] = []
        for path in sorted(self._dir.rglob("*.md")):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if scan_mode == "incremental":
                if self._seen.get(str(path)) == mtime:
                    continue
            parsed = self._parse_file(path)
            if parsed is not None:
                results.append(parsed)
                self._seen[str(path)] = mtime
        return results

    def _parse_file(self, path: Path) -> ParsedNewsletter | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            logger.warning("cannot read %s", path)
            return None
        if not text.strip():
            logger.warning("empty file %s", path)
            return None
        meta, body = self._split_frontmatter(text)
        return ParsedNewsletter(
            file_path=str(path),
            title=str(meta.get("title", path.stem)),
            source=str(meta.get("source", "unknown")),
            received_at=self._parse_date(meta.get("created") or meta.get("received_at")),
            summary=body.strip(),
            sentence_count=body.count(".") + body.count("!") + body.count("?"),
            tags=list(meta.get("tags", [])),
        )

    def _split_frontmatter(self, text: str) -> tuple[dict[str, Any], str]:
        if not text.startswith("---"):
            return {}, text
        parts = text.split("---", 2)
        if len(parts) < 3:
            return {}, text
        try:
            meta = yaml.safe_load(parts[1]) or {}
        except yaml.YAMLError:
            return {}, text
        if not isinstance(meta, dict):
            return {}, text
        return meta, parts[2]

    @staticmethod
    def _parse_date(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        import datetime as _dt

        if isinstance(value, _dt.date) and not isinstance(value, datetime):
            return datetime(value.year, value.month, value.day)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        return None
