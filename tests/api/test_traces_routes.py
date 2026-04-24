"""Tests for traces endpoint (traces.py)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.traces import router as traces_router
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
def traces_app() -> FastAPI:
    """Create a FastAPI app with the traces endpoint."""
    app = FastAPI()
    app.include_router(traces_router)

    fake_llm = FakeLLMClient()

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
                "strengths": ["chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
        phoenix_endpoint="http://phoenix-test:6006",
    )

    prompts = InMemoryPromptManager()
    warden = Warden()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")

        default_agent = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
            ),
            strategy=DirectStrategy(),
            llm=fake_llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=warden,
        )

        return Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=InMemoryLearningStore(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default_agent},
        )

    container = asyncio.run(setup())
    app.state.container = container
    return app


class TestTracesEndpoint:
    def test_authenticated_returns_phoenix_pointer(self, traces_app: FastAPI) -> None:
        """Authenticated GET /v1/stronghold/traces returns phoenix URL."""
        with TestClient(traces_app) as client:
            resp = client.get(
                "/v1/stronghold/traces",
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["traces"] == "stored_in_phoenix"
            assert data["phoenix_url"] == "http://phoenix-test:6006"
            assert "note" in data

    def test_unauthenticated_returns_401(self, traces_app: FastAPI) -> None:
        """GET /v1/stronghold/traces without auth returns 401."""
        with TestClient(traces_app) as client:
            resp = client.get("/v1/stronghold/traces")
            assert resp.status_code == 401
