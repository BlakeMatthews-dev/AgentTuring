"""Tests for InMemoryAgentStore: CRUD + GitAgent import/export."""

from __future__ import annotations

import io
import zipfile

import pytest
import yaml

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.security.warden.detector import Warden
from stronghold.types.agent import AgentIdentity
from tests.fakes import FakeLLMClient


@pytest.fixture
def agent_store() -> InMemoryAgentStore:
    """Create an InMemoryAgentStore with one pre-existing agent."""
    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")
    prompts = InMemoryPromptManager()
    warden = Warden()
    context_builder = ContextBuilder()
    learning_store = InMemoryLearningStore()

    default_agent = Agent(
        identity=AgentIdentity(
            name="arbiter",
            soul_prompt_name="agent.arbiter.soul",
            model="test/model",
            memory_config={"learnings": True},
        ),
        strategy=DirectStrategy(),
        llm=fake_llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    agents: dict[str, Agent] = {"arbiter": default_agent}
    store = InMemoryAgentStore(agents, prompts)
    store._souls["arbiter"] = "You are a helpful assistant."
    store._rules["arbiter"] = "Be concise."
    return store


class TestCreate:
    async def test_valid_identity_stores_agent(self, agent_store: InMemoryAgentStore) -> None:
        identity = AgentIdentity(
            name="ranger",
            soul_prompt_name="agent.ranger.soul",
            model="test/model",
        )
        name = await agent_store.create(identity, "You are the Ranger.")
        assert name == "ranger"
        assert "ranger" in agent_store._agents

    async def test_invalid_name_uppercase_raises(self, agent_store: InMemoryAgentStore) -> None:
        identity = AgentIdentity(
            name="BadName",
            soul_prompt_name="agent.bad.soul",
            model="test/model",
        )
        with pytest.raises(ValueError, match="Invalid agent name"):
            await agent_store.create(identity, "soul")

    async def test_invalid_name_too_long_raises(self, agent_store: InMemoryAgentStore) -> None:
        identity = AgentIdentity(
            name="a" * 51,
            soul_prompt_name="agent.long.soul",
            model="test/model",
        )
        with pytest.raises(ValueError, match="Invalid agent name"):
            await agent_store.create(identity, "soul")

    async def test_duplicate_name_raises(self, agent_store: InMemoryAgentStore) -> None:
        identity = AgentIdentity(
            name="arbiter",
            soul_prompt_name="agent.arbiter.soul",
            model="test/model",
        )
        with pytest.raises(ValueError, match="already exists"):
            await agent_store.create(identity, "soul")


class TestGet:
    async def test_existing_returns_detail_dict(self, agent_store: InMemoryAgentStore) -> None:
        result = await agent_store.get("arbiter")
        assert result is not None
        assert result["name"] == "arbiter"
        assert result["model"] == "test/model"
        assert result["soul_prompt_preview"] == "You are a helpful assistant."
        assert result["rules_preview"] == "Be concise."

    async def test_nonexistent_returns_none(self, agent_store: InMemoryAgentStore) -> None:
        result = await agent_store.get("nonexistent")
        assert result is None


class TestListAll:
    async def test_returns_all_agents(self, agent_store: InMemoryAgentStore) -> None:
        results = await agent_store.list_all()
        assert len(results) == 1
        assert results[0]["name"] == "arbiter"

    async def test_returns_multiple_after_create(self, agent_store: InMemoryAgentStore) -> None:
        identity = AgentIdentity(
            name="artificer",
            soul_prompt_name="agent.artificer.soul",
            model="test/model",
        )
        await agent_store.create(identity, "You are the Artificer.")
        results = await agent_store.list_all()
        assert len(results) == 2
        names = [r["name"] for r in results]
        assert "arbiter" in names
        assert "artificer" in names


class TestUpdate:
    async def test_soul_prompt_updates(self, agent_store: InMemoryAgentStore) -> None:
        result = await agent_store.update("arbiter", {"soul_prompt": "New soul."})
        assert result["soul_prompt_preview"] == "New soul."

    async def test_rules_update(self, agent_store: InMemoryAgentStore) -> None:
        result = await agent_store.update("arbiter", {"rules": "New rules."})
        assert result["rules_preview"] == "New rules."

    async def test_nonexistent_raises(self, agent_store: InMemoryAgentStore) -> None:
        with pytest.raises(ValueError, match="not found"):
            await agent_store.update("nonexistent", {"soul_prompt": "new"})


class TestDelete:
    async def test_existing_returns_true(self, agent_store: InMemoryAgentStore) -> None:
        result = await agent_store.delete("arbiter")
        assert result is True
        assert "arbiter" not in agent_store._agents

    async def test_nonexistent_returns_false(self, agent_store: InMemoryAgentStore) -> None:
        result = await agent_store.delete("nonexistent")
        assert result is False


class TestExportGitagent:
    async def test_valid_returns_zip_bytes(self, agent_store: InMemoryAgentStore) -> None:
        data = await agent_store.export_gitagent("arbiter")
        # Non-empty bytes payload — exported zips should never be empty.
        assert data
        assert len(data) > 0
        # ZIP files begin with the "PK" magic number (0x50 0x4B).
        assert data[:2] == b"PK", f"Expected ZIP magic bytes, got: {data[:4]!r}"

        # Verify zip contents
        buf = io.BytesIO(data)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
            assert "arbiter/agent.yaml" in names
            assert "arbiter/SOUL.md" in names

            # Verify agent.yaml content
            manifest = yaml.safe_load(zf.read("arbiter/agent.yaml"))
            assert manifest["name"] == "arbiter"
            assert manifest["spec_version"] == "0.1.0"

            # Verify SOUL.md content
            soul = zf.read("arbiter/SOUL.md").decode("utf-8")
            assert soul == "You are a helpful assistant."

            # RULES.md should be present since we set it
            assert "arbiter/RULES.md" in names
            rules = zf.read("arbiter/RULES.md").decode("utf-8")
            assert rules == "Be concise."

    async def test_nonexistent_raises(self, agent_store: InMemoryAgentStore) -> None:
        with pytest.raises(ValueError, match="not found"):
            await agent_store.export_gitagent("nonexistent")


class TestImportGitagent:
    async def test_valid_zip_creates_agent(self, agent_store: InMemoryAgentStore) -> None:
        # Build a valid GitAgent zip
        buf = io.BytesIO()
        manifest = {
            "spec_version": "0.1.0",
            "name": "imported-agent",
            "version": "1.0.0",
            "description": "An imported agent",
            "reasoning": {"strategy": "direct", "max_rounds": 3},
            "model": "test/model",
            "tools": [],
            "trust_tier": "t2",
            "memory": {},
        }
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(
                "imported-agent/agent.yaml",
                yaml.dump(manifest, default_flow_style=False),
            )
            zf.writestr("imported-agent/SOUL.md", "You are the imported agent.")
            zf.writestr("imported-agent/RULES.md", "Follow the rules.")

        name = await agent_store.import_gitagent(buf.getvalue())
        assert name == "imported-agent"
        assert "imported-agent" in agent_store._agents

        detail = await agent_store.get("imported-agent")
        assert detail is not None
        assert detail["description"] == "An imported agent"

    async def test_invalid_zip_no_manifest_raises(
        self, agent_store: InMemoryAgentStore
    ) -> None:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("random/file.txt", "nothing")
        with pytest.raises(ValueError, match="No agent.yaml"):
            await agent_store.import_gitagent(buf.getvalue())
