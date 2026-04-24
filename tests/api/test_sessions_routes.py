"""Tests for API sessions routes: list, get, delete, validation."""

from __future__ import annotations

import asyncio
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.sessions import router as sessions_router
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
from tests.fakes import FakeLLMClient


@pytest.fixture
def sessions_app() -> FastAPI:
    """Create a FastAPI app with sessions routes and a pre-populated session."""
    app = FastAPI()
    app.include_router(sessions_router)

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
    session_store = InMemorySessionStore()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        # Pre-populate a session scoped to the system org
        # SYSTEM_AUTH has org_id="__system__", so session ID must start with "__system__/"
        session_id = "__system__/_/system:test-session"
        await session_store.append_messages(
            session_id,
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi there"},
            ],
        )

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
            session_store=session_store,
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
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default_agent},
        )

    container = asyncio.run(setup())
    app.state.container = container
    return app


class TestListSessions:
    def test_authenticated_returns_sessions(self, sessions_app: FastAPI) -> None:
        with TestClient(sessions_app) as client:
            resp = client.get(
                "/v1/stronghold/sessions",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["session_id"] == "__system__/_/system:test-session"
            assert data[0]["message_count"] == 2

    def test_unauthenticated_returns_401(self, sessions_app: FastAPI) -> None:
        with TestClient(sessions_app) as client:
            resp = client.get("/v1/stronghold/sessions")
            assert resp.status_code == 401


class TestGetSession:
    def test_existing_returns_200_with_messages(self, sessions_app: FastAPI) -> None:
        with TestClient(sessions_app) as client:
            resp = client.get(
                "/v1/stronghold/sessions/__system__/_/system:test-session",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["session_id"] == "__system__/_/system:test-session"
            assert len(data["messages"]) == 2
            assert data["messages"][0]["role"] == "user"
            assert data["messages"][1]["role"] == "assistant"

    def test_nonexistent_returns_200_empty(self, sessions_app: FastAPI) -> None:
        """A nonexistent session that still matches org ownership returns empty history."""
        with TestClient(sessions_app) as client:
            resp = client.get(
                "/v1/stronghold/sessions/__system__/_/system:no-such-session",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["messages"] == []


class TestDeleteSession:
    def test_existing_returns_200(self, sessions_app: FastAPI) -> None:
        with TestClient(sessions_app) as client:
            resp = client.delete(
                "/v1/stronghold/sessions/__system__/_/system:test-session",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "deleted"

            # Verify it is actually deleted
            resp2 = client.get(
                "/v1/stronghold/sessions/__system__/_/system:test-session",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp2.json()["messages"] == []


class TestSessionIdValidation:
    def test_invalid_chars_returns_400(self, sessions_app: FastAPI) -> None:
        with TestClient(sessions_app) as client:
            # Session IDs with spaces or special chars should be rejected
            resp = client.get(
                "/v1/stronghold/sessions/__system__/ bad session!",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 400

    def test_auth_required_on_delete(self, sessions_app: FastAPI) -> None:
        with TestClient(sessions_app) as client:
            resp = client.delete(
                "/v1/stronghold/sessions/__system__/_/system:test-session",
            )
            assert resp.status_code == 401
