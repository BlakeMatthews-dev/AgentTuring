"""Tests for runtime/actor.py — bridges durable memory to tool calls."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from turing.repo import Repo
from turing.runtime.actor import Actor
from turing.runtime.tools.base import Tool, ToolMode, ToolRegistry
from turing.runtime.tools.obsidian import ObsidianWriter
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _mint_regret(repo: Repo, self_id: str, *, when: datetime) -> str:
    m = EpisodicMemory(
        memory_id=str(uuid4()),
        self_id=self_id,
        tier=MemoryTier.REGRET,
        source=SourceKind.I_DID,
        content="bad routing",
        weight=0.7,
        affect=-0.6,
        intent_at_time="route-x",
        immutable=True,
        created_at=when,
    )
    repo.insert(m)
    return m.memory_id


def test_actor_writes_obsidian_for_new_durable(
    repo: Repo, self_id: str, tmp_path: Path
) -> None:
    registry = ToolRegistry()
    registry.register(ObsidianWriter(vault_dir=tmp_path))
    actor = Actor(repo=repo, self_id=self_id, registry=registry, poll_ticks=1)

    _mint_regret(repo, self_id, when=datetime.now(UTC) + timedelta(seconds=1))

    actor.on_tick(1)

    md_files = list(tmp_path.rglob("*.md"))
    assert md_files, "expected an obsidian note to be written"
    text = md_files[0].read_text(encoding="utf-8")
    assert "regret" in text.lower()
    assert "bad routing" in text


def test_actor_no_op_without_obsidian(
    repo: Repo, self_id: str, tmp_path: Path
) -> None:
    registry = ToolRegistry()             # no tools
    actor = Actor(repo=repo, self_id=self_id, registry=registry, poll_ticks=1)
    _mint_regret(repo, self_id, when=datetime.now(UTC) + timedelta(seconds=1))
    actor.on_tick(1)
    # No exception, no files (no vault wired anyway).
    assert not list(tmp_path.rglob("*.md"))


def test_actor_only_polls_on_cadence(
    repo: Repo, self_id: str, tmp_path: Path
) -> None:
    registry = ToolRegistry()
    registry.register(ObsidianWriter(vault_dir=tmp_path))
    actor = Actor(repo=repo, self_id=self_id, registry=registry, poll_ticks=10)

    _mint_regret(repo, self_id, when=datetime.now(UTC) + timedelta(seconds=1))

    # Tick at 9 — below cadence, no poll.
    actor.on_tick(9)
    assert not list(tmp_path.rglob("*.md"))

    # Tick at 10 — fires.
    actor.on_tick(10)
    assert list(tmp_path.rglob("*.md"))
