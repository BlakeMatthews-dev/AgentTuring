"""PostgreSQL prompt manager."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncpg


class PgPromptManager:
    """PostgreSQL-backed versioned prompt store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get(self, name: str, *, label: str = "production") -> str:
        """Fetch prompt content by name and label."""
        content, _ = await self.get_with_config(name, label=label)
        return content

    async def get_with_config(
        self,
        name: str,
        *,
        label: str = "production",
    ) -> tuple[str, dict[str, Any]]:
        """Fetch prompt text + config metadata."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT content, config FROM prompts WHERE name = $1 AND label = $2",
                name,
                label,
            )
            if row:
                config = _parse_config(row["config"])
                return str(row["content"]), config

            # Fallback to latest version
            row = await conn.fetchrow(
                "SELECT content, config FROM prompts WHERE name = $1 ORDER BY version DESC LIMIT 1",
                name,
            )
            if row:
                config = _parse_config(row["config"])
                return str(row["content"]), config
        return "", {}

    async def upsert(
        self,
        name: str,
        content: str,
        *,
        config: dict[str, Any] | None = None,
        label: str = "",
    ) -> None:
        """Create a new version of a prompt."""
        config_json = json.dumps(config or {})
        async with self._pool.acquire() as conn:
            # Get next version
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(version), 0) + 1 AS next_ver FROM prompts WHERE name = $1",
                name,
            )
            next_ver: int = row["next_ver"] if row else 1

            # Remove old label assignment if exists
            if label:
                await conn.execute(
                    "UPDATE prompts SET label = NULL WHERE name = $1 AND label = $2",
                    name,
                    label,
                )

            # Also update 'latest' label
            await conn.execute(
                "UPDATE prompts SET label = NULL WHERE name = $1 AND label = 'latest'",
                name,
            )

            # Insert new version
            effective_label = label or "latest"
            await conn.execute(
                """INSERT INTO prompts (name, version, label, content, config)
                   VALUES ($1, $2, $3, $4, $5::jsonb)""",
                name,
                next_ver,
                effective_label,
                content,
                config_json,
            )

            # If first version, also set production
            if next_ver == 1 and effective_label != "production":
                await conn.execute(
                    """INSERT INTO prompts (name, version, label, content, config)
                       VALUES ($1, $2, 'production', $3, $4::jsonb)
                       ON CONFLICT (name, label)
                       DO UPDATE SET version = $2, content = $3, config = $4::jsonb""",
                    name,
                    next_ver,
                    content,
                    config_json,
                )


def _parse_config(raw: Any) -> dict[str, Any]:
    """Parse config from DB row (may be str, dict, or None)."""
    if raw is None:
        return {}
    if isinstance(raw, str):
        result: dict[str, Any] = json.loads(raw)
        return result
    if isinstance(raw, dict):
        return dict(raw)
    return {}
