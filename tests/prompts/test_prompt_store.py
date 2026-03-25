"""Tests for InMemoryPromptManager: CRUD, versioning, labels."""

import pytest

from stronghold.prompts.store import InMemoryPromptManager


class TestPromptUpsert:
    """Upsert creates new or updates existing prompts."""

    @pytest.mark.asyncio
    async def test_upsert_creates_new(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("system-prompt", "You are helpful")
        content = await pm.get("system-prompt")
        assert content == "You are helpful"

    @pytest.mark.asyncio
    async def test_upsert_updates_existing(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "version 1")
        await pm.upsert("p1", "version 2")
        content = await pm.get("p1", label="latest")
        assert content == "version 2"

    @pytest.mark.asyncio
    async def test_upsert_with_config(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "content", config={"temperature": 0.7})
        content, config = await pm.get_with_config("p1")
        assert content == "content"
        assert config == {"temperature": 0.7}

    @pytest.mark.asyncio
    async def test_upsert_with_label(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "staging content", label="staging")
        content = await pm.get("p1", label="staging")
        assert content == "staging content"


class TestPromptGet:
    """Get returns content by name and label."""

    @pytest.mark.asyncio
    async def test_get_returns_latest(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "v1")
        await pm.upsert("p1", "v2")
        content = await pm.get("p1", label="latest")
        assert content == "v2"

    @pytest.mark.asyncio
    async def test_get_with_production_label(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "first version")
        # First version automatically gets "production" label
        content = await pm.get("p1", label="production")
        assert content == "first version"

    @pytest.mark.asyncio
    async def test_get_with_specific_label(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "prod version", label="production")
        await pm.upsert("p1", "staging version", label="staging")
        prod = await pm.get("p1", label="production")
        staging = await pm.get("p1", label="staging")
        assert prod == "prod version"
        assert staging == "staging version"

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_empty(self) -> None:
        pm = InMemoryPromptManager()
        content = await pm.get("nonexistent")
        assert content == ""

    @pytest.mark.asyncio
    async def test_get_with_config_nonexistent(self) -> None:
        pm = InMemoryPromptManager()
        content, config = await pm.get_with_config("nonexistent")
        assert content == ""
        assert config == {}


class TestVersionHistory:
    """Version tracking for prompts."""

    @pytest.mark.asyncio
    async def test_versions_increment(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "v1")
        await pm.upsert("p1", "v2")
        await pm.upsert("p1", "v3")
        versions = pm._versions.get("p1", {})
        assert len(versions) == 3
        assert 1 in versions
        assert 2 in versions
        assert 3 in versions

    @pytest.mark.asyncio
    async def test_each_version_has_content(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "content v1", config={"a": 1})
        await pm.upsert("p1", "content v2", config={"b": 2})
        versions = pm._versions["p1"]
        assert versions[1] == ("content v1", {"a": 1})
        assert versions[2] == ("content v2", {"b": 2})

    @pytest.mark.asyncio
    async def test_latest_label_always_updated(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "v1")
        await pm.upsert("p1", "v2")
        await pm.upsert("p1", "v3")
        labels = pm._labels["p1"]
        assert labels["latest"] == 3


class TestPromptList:
    """Listing all prompts."""

    @pytest.mark.asyncio
    async def test_list_returns_all(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("prompt-a", "content a")
        await pm.upsert("prompt-b", "content b")
        await pm.upsert("prompt-c", "content c")
        names = sorted(pm._versions.keys())
        assert names == ["prompt-a", "prompt-b", "prompt-c"]

    @pytest.mark.asyncio
    async def test_list_empty(self) -> None:
        pm = InMemoryPromptManager()
        assert len(pm._versions) == 0


class TestMultiplePrompts:
    """Multiple prompts don't interfere with each other."""

    @pytest.mark.asyncio
    async def test_separate_versions(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("a", "a1")
        await pm.upsert("a", "a2")
        await pm.upsert("b", "b1")
        assert len(pm._versions["a"]) == 2
        assert len(pm._versions["b"]) == 1

    @pytest.mark.asyncio
    async def test_separate_labels(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("a", "a-staging", label="staging")
        await pm.upsert("b", "b-staging", label="staging")
        a = await pm.get("a", label="staging")
        b = await pm.get("b", label="staging")
        assert a == "a-staging"
        assert b == "b-staging"

    @pytest.mark.asyncio
    async def test_production_label_on_first_version(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "first")
        labels = pm._labels["p1"]
        assert "production" in labels
        assert labels["production"] == 1

    @pytest.mark.asyncio
    async def test_second_version_does_not_move_production(self) -> None:
        pm = InMemoryPromptManager()
        await pm.upsert("p1", "first")
        await pm.upsert("p1", "second")
        labels = pm._labels["p1"]
        assert labels["production"] == 1  # still points to v1
        assert labels["latest"] == 2
