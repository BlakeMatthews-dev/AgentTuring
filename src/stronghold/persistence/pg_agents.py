"""PostgreSQL agent registry using SQLModel.

Reads and writes agent definitions to the `agents` table. Used by the factory
to load agents from the database instead of re-reading the filesystem.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from stronghold.models.agent import AgentRecord

logger = logging.getLogger("stronghold.persistence.pg_agents")


class PgAgentRegistry:
    """CRUD for agent definitions in PostgreSQL via SQLModel."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    async def list_active(self, org_id: str = "") -> list[AgentRecord]:
        """List all active agents, optionally filtered by org."""
        async with AsyncSession(self._engine) as session:
            if org_id:
                result = await session.execute(
                    text(
                        "SELECT * FROM agents WHERE active = TRUE"
                        " AND (org_id = :org OR org_id = '') ORDER BY name"
                    ),
                    {"org": org_id},
                )
            else:
                result = await session.execute(
                    text("SELECT * FROM agents WHERE active = TRUE ORDER BY name"),
                )
            rows = result.mappings().all()
            return [AgentRecord.model_validate(_coerce_row(r)) for r in rows]

    async def get(self, name: str) -> AgentRecord | None:
        """Get a single agent by name."""
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text("SELECT * FROM agents WHERE name = :name"),
                {"name": name},
            )
            row = result.mappings().first()
            return AgentRecord.model_validate(_coerce_row(row)) if row else None

    async def upsert(self, record: AgentRecord) -> AgentRecord:
        """Atomically insert or update an agent definition.

        Uses INSERT ... ON CONFLICT DO UPDATE for race-free upsert.
        All columns are written — no silent drops.
        """
        record.updated_at = datetime.now(UTC)
        async with AsyncSession(self._engine) as session:
            await session.execute(
                text("""
                    INSERT INTO agents (
                        name, version, description, soul, rules,
                        reasoning_strategy, model, model_fallbacks,
                        model_constraints, tools, skills, max_tool_rounds,
                        memory_config, trust_tier, provenance, org_id,
                        preamble, active, config,
                        ai_reviewed, ai_review_clean, ai_review_flags,
                        admin_reviewed, admin_reviewed_by, user_reviewed,
                        created_at, updated_at
                    ) VALUES (
                        :name, :version, :description, :soul, :rules,
                        :reasoning_strategy, :model, :model_fallbacks,
                        :model_constraints::jsonb, :tools, :skills, :max_tool_rounds,
                        :memory_config::jsonb, :trust_tier, :provenance, :org_id,
                        :preamble, :active, :config::jsonb,
                        :ai_reviewed, :ai_review_clean, :ai_review_flags,
                        :admin_reviewed, :admin_reviewed_by, :user_reviewed,
                        :created_at, :updated_at
                    )
                    ON CONFLICT (name) DO UPDATE SET
                        version = EXCLUDED.version,
                        description = EXCLUDED.description,
                        soul = EXCLUDED.soul,
                        rules = EXCLUDED.rules,
                        reasoning_strategy = EXCLUDED.reasoning_strategy,
                        model = EXCLUDED.model,
                        model_fallbacks = EXCLUDED.model_fallbacks,
                        model_constraints = EXCLUDED.model_constraints,
                        tools = EXCLUDED.tools,
                        skills = EXCLUDED.skills,
                        max_tool_rounds = EXCLUDED.max_tool_rounds,
                        memory_config = EXCLUDED.memory_config,
                        trust_tier = EXCLUDED.trust_tier,
                        provenance = EXCLUDED.provenance,
                        org_id = EXCLUDED.org_id,
                        preamble = EXCLUDED.preamble,
                        active = EXCLUDED.active,
                        config = EXCLUDED.config,
                        ai_reviewed = EXCLUDED.ai_reviewed,
                        ai_review_clean = EXCLUDED.ai_review_clean,
                        ai_review_flags = EXCLUDED.ai_review_flags,
                        admin_reviewed = EXCLUDED.admin_reviewed,
                        admin_reviewed_by = EXCLUDED.admin_reviewed_by,
                        user_reviewed = EXCLUDED.user_reviewed,
                        updated_at = EXCLUDED.updated_at
                """),
                {
                    "name": record.name,
                    "version": record.version,
                    "description": record.description,
                    "soul": record.soul,
                    "rules": record.rules,
                    "reasoning_strategy": record.reasoning_strategy,
                    "model": record.model,
                    "model_fallbacks": record.model_fallbacks,
                    "model_constraints": json.dumps(record.model_constraints, default=str),
                    "tools": record.tools,
                    "skills": record.skills,
                    "max_tool_rounds": record.max_tool_rounds,
                    "memory_config": json.dumps(record.memory_config, default=str),
                    "trust_tier": record.trust_tier,
                    "provenance": record.provenance,
                    "org_id": record.org_id,
                    "preamble": record.preamble,
                    "active": record.active,
                    "config": json.dumps(record.config, default=str),
                    "ai_reviewed": record.ai_reviewed,
                    "ai_review_clean": record.ai_review_clean,
                    "ai_review_flags": record.ai_review_flags,
                    "admin_reviewed": record.admin_reviewed,
                    "admin_reviewed_by": record.admin_reviewed_by,
                    "user_reviewed": record.user_reviewed,
                    "created_at": record.created_at,
                    "updated_at": record.updated_at,
                },
            )
            await session.commit()
        return record

    async def count(self) -> int:
        """Count active agents in the database."""
        async with AsyncSession(self._engine) as session:
            result = await session.execute(text("SELECT COUNT(*) FROM agents WHERE active = TRUE"))
            row = result.first()
            return row[0] if row else 0

    async def delete(self, name: str) -> bool:
        """Soft-delete an agent."""
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                text(
                    "UPDATE agents SET active = FALSE, updated_at = NOW()"
                    " WHERE name = :name AND active = TRUE"
                ),
                {"name": name},
            )
            await session.commit()
            return bool(getattr(result, "rowcount", 0) > 0)


# ARRAY columns may come back as None from raw text() queries on some
# asyncpg/SQLAlchemy configurations. Coerce to empty list for Pydantic.
_ARRAY_FIELDS = {"model_fallbacks", "tools", "skills"}
_JSONB_FIELDS = {"model_constraints", "memory_config", "config"}


def _coerce_row(row: Any) -> dict[str, Any]:
    """Coerce raw SQL row to dict safe for AgentRecord.model_validate."""
    data = dict(row)
    for field in _ARRAY_FIELDS:
        if data.get(field) is None:
            data[field] = []
    for field in _JSONB_FIELDS:
        if data.get(field) is None:
            data[field] = {}
    return data
