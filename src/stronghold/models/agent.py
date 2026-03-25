"""Agent persistence model.

Maps to the existing `agents` table from 001_initial.sql + 004_agent_trust_tiers.sql.
The JSONB `config` column is replaced by typed fields via migration 005.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Column, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.types import DateTime
from sqlmodel import Field, SQLModel


class AgentRecord(SQLModel, table=True):
    """An agent definition stored in PostgreSQL.

    This is the database record — not the runtime Agent object. The factory
    reads these records and instantiates Agent objects with strategies and
    LLM clients. The record is the source of truth for agent configuration.
    """

    __tablename__ = "agents"

    name: str = Field(primary_key=True, max_length=50)
    version: str = Field(default="1.0.0", max_length=20)
    description: str = Field(default="", sa_column=Column(Text, default=""))

    # Soul prompt (full text, including preamble if applicable)
    soul: str = Field(default="", sa_column=Column(Text, default=""))
    rules: str = Field(default="", sa_column=Column(Text, default=""))

    # Agent behavior
    reasoning_strategy: str = Field(default="direct", max_length=30)
    model: str = Field(default="auto", max_length=100)
    model_fallbacks: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"),
    )
    model_constraints: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    tools: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"),
    )
    skills: list[str] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(Text), nullable=False, server_default="{}"),
    )
    max_tool_rounds: int = Field(default=3)
    memory_config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )

    # Security
    trust_tier: str = Field(default="t4", max_length=5)
    provenance: str = Field(default="user", max_length=20)
    ai_reviewed: bool = Field(default=False)
    ai_review_clean: bool = Field(default=False)
    ai_review_flags: str = Field(default="")
    admin_reviewed: bool = Field(default=False)
    admin_reviewed_by: str = Field(default="")
    user_reviewed: bool = Field(default=False)

    # Multi-tenant
    org_id: str = Field(default="")
    preamble: bool = Field(default=True)

    # Lifecycle
    active: bool = Field(default=True)
    config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default="{}"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
