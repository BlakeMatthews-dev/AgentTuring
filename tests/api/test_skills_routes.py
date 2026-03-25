"""Tests for API skills routes: list, get, forge, delete, update, validate, test."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.skills import router as skills_router
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.security.gate import Gate
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from stronghold.types.tool import ToolDefinition
from tests.fakes import FakeLLMClient


@pytest.fixture
def skills_app() -> FastAPI:
    """Create a FastAPI app with skills routes and a pre-registered tool."""
    app = FastAPI()
    app.include_router(skills_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("ok")

    config = StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1000000},
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )

    prompts = InMemoryPromptManager()
    learning_store = InMemoryLearningStore()
    warden = Warden()
    context_builder = ContextBuilder()

    tool_registry = InMemoryToolRegistry()
    # Register a test tool so list/get have data
    test_tool = ToolDefinition(
        name="web_search",
        description="Search the web for information",
        parameters={"type": "object", "properties": {"query": {"type": "string"}}},
        groups=("search",),
        endpoint="https://example.com/search",
    )
    tool_registry.register(test_tool)

    tool_dispatcher = ToolDispatcher(tool_registry)

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

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

        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=learning_store,
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            audit_log=InMemoryAuditLog(),
            warden=warden,
            gate=Gate(warden=warden),
            sentinel=Sentinel(
                warden=warden,
                permission_table=PermissionTable.from_config(config.permissions),
                audit_log=InMemoryAuditLog(),
            ),
            tracer=NoopTracingBackend(),
            context_builder=context_builder,
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=tool_registry,
            tool_dispatcher=tool_dispatcher,
            agents={"arbiter": default_agent},
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


class TestListSkills:
    def test_authenticated_returns_tool_list(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.get(
                "/v1/stronghold/skills",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["name"] == "web_search"
            assert data[0]["description"] == "Search the web for information"
            assert "search" in data[0]["groups"]

    def test_unauthenticated_returns_401(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.get("/v1/stronghold/skills")
            assert resp.status_code == 401


class TestGetSkill:
    def test_existing_skill_returns_200(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.get(
                "/v1/stronghold/skills/web_search",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "web_search"
            assert data["description"] == "Search the web for information"
            assert "query" in data["parameters"]["properties"]
            assert data["endpoint"] == "https://example.com/search"

    def test_nonexistent_returns_404(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.get(
                "/v1/stronghold/skills/nonexistent_skill",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 404


class TestForgeSkill:
    def test_forge_creates_skill(self, skills_app: FastAPI) -> None:
        # Set FakeLLM to return a valid SKILL.md
        valid_skill_md = (
            "---\n"
            "name: do_stuff\n"
            'description: "A skill that does stuff"\n'
            "groups: [general]\n"
            "parameters:\n"
            "  type: object\n"
            "  properties:\n"
            "    input:\n"
            "      type: string\n"
            "      description: \"The input\"\n"
            "  required: [input]\n"
            'trust_tier: "t3"\n'
            "---\n\n"
            "You are a tool that does stuff.\n"
        )
        skills_app.state.container.llm.set_simple_response(valid_skill_md)
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/forge",
                json={"description": "A new skill that does stuff"},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "do_stuff"
            assert data["trust_tier"] == "t3"
            assert data["status"] == "forged"

    def test_forge_rejects_bad_llm_output(self, skills_app: FastAPI) -> None:
        skills_app.state.container.llm.set_simple_response("not a valid skill")
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/forge",
                json={"description": "A new skill"},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 422

    def test_non_admin_returns_403(self, skills_app: FastAPI) -> None:
        """Non-admin users cannot forge skills.

        StaticKeyAuthProvider returns SYSTEM_AUTH which has admin role,
        so we test with a custom auth provider that returns a non-admin user.
        """
        from stronghold.types.auth import AuthContext

        from tests.fakes import FakeAuthProvider

        skills_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/forge",
                json={"description": "A skill"},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 403

    def test_missing_description_returns_400(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/forge",
                json={},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 400


class TestDeleteSkill:
    def test_admin_returns_200(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.delete(
                "/v1/stronghold/skills/web_search",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "deleted"
            assert data["name"] == "web_search"

    def test_non_admin_returns_403(self, skills_app: FastAPI) -> None:
        from stronghold.types.auth import AuthContext

        from tests.fakes import FakeAuthProvider

        skills_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(skills_app) as client:
            resp = client.delete(
                "/v1/stronghold/skills/web_search",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 403


class TestUpdateSkill:
    def test_admin_existing_returns_200(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.put(
                "/v1/stronghold/skills/web_search",
                json={"description": "Updated description"},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "web_search"
            assert data["status"] == "updated"

    def test_nonexistent_returns_404(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.put(
                "/v1/stronghold/skills/nonexistent",
                json={"description": "new"},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 404

    def test_non_admin_returns_403(self, skills_app: FastAPI) -> None:
        from stronghold.types.auth import AuthContext

        from tests.fakes import FakeAuthProvider

        skills_app.state.container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="viewer",
                username="viewer",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
            )
        )
        with TestClient(skills_app) as client:
            resp = client.put(
                "/v1/stronghold/skills/web_search",
                json={"description": "new"},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 403


class TestValidateSkill:
    def test_valid_skill_md_returns_valid(self, skills_app: FastAPI) -> None:
        skill_content = (
            "---\n"
            "name: my_skill\n"
            "description: A test skill\n"
            "groups: [general]\n"
            "parameters:\n"
            "  type: object\n"
            "  properties:\n"
            "    query:\n"
            "      type: string\n"
            "  required: [query]\n"
            "---\n"
            "\n"
            "You are a helpful skill.\n"
        )
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/validate",
                json={"content": skill_content},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is True
            assert data["parsed"]["name"] == "my_skill"

    def test_empty_content_returns_400(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/validate",
                json={"content": ""},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 400

    def test_invalid_skill_md_returns_not_valid(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/validate",
                json={"content": "this is not valid yaml frontmatter"},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["valid"] is False


class TestTestSkill:
    def test_valid_skill_name_executes(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/test",
                json={"skill_name": "web_search", "test_input": {"query": "test"}},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["skill_name"] == "web_search"
            # The tool has no executor registered, so it falls back to HTTP
            # which will fail with SSRF block or similar, but still returns a result
            assert "output" in data

    def test_missing_skill_name_returns_400(self, skills_app: FastAPI) -> None:
        with TestClient(skills_app) as client:
            resp = client.post(
                "/v1/stronghold/skills/test",
                json={"test_input": {"query": "test"}},
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 400
