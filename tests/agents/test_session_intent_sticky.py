"""Test that once a conversation enters a specialist flow, follow-ups stay there."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.chat import router as chat_router
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
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
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.types.agent import AgentIdentity
from stronghold.types.auth import PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeLLMClient


@pytest.fixture
def sticky_app() -> FastAPI:
    import asyncio

    app = FastAPI()
    app.include_router(chat_router)

    llm = FakeLLMClient()
    llm.set_simple_response("I'm the Artificer, working on your code.")

    config = StrongholdConfig(
        providers={"t": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1000000}},
        models={
            "m": {
                "provider": "t",
                "litellm_id": "t/m",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code", "chat"],
            }
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello", "hi"], preferred_strengths=["chat"]),
            "code": TaskTypeConfig(
                keywords=["code", "function", "bug", "fix", "test"],
                min_tier="medium",
                preferred_strengths=["code"],
            ),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )

    prompts = InMemoryPromptManager()
    warden = Warden()
    cb = ContextBuilder()
    session_store = InMemorySessionStore()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "Default chat.", label="production")
        await prompts.upsert("agent.artificer.soul", "I am the Artificer.", label="production")

        default = Agent(
            identity=AgentIdentity(
                name="arbiter", soul_prompt_name="agent.arbiter.soul", model="t/m", memory_config={}
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=cb,
            prompt_manager=prompts,
            warden=warden,
            session_store=session_store,
        )
        artificer = Agent(
            identity=AgentIdentity(
                name="artificer",
                soul_prompt_name="agent.artificer.soul",
                model="t/m",
                memory_config={},
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=cb,
            prompt_manager=prompts,
            warden=warden,
            session_store=session_store,
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
            context_builder=cb,
            intent_registry=IntentRegistry({"code": "artificer"}),
            llm=llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default, "artificer": artificer},
        )

    container = asyncio.run(setup())
    app.state.container = container
    return app


class TestSessionIntentSticky:
    def test_followup_stays_with_same_agent(self, sticky_app: FastAPI) -> None:
        """Once routed to Artificer, follow-ups should stay with Artificer."""
        with TestClient(sticky_app) as client:
            # First: code request with session_id
            resp1 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [
                        {
                            "role": "user",
                            "content": "write a function to sort a list in utils.py with type hints and pytest tests",
                        }
                    ],
                    "session_id": "sticky-test",
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp1.status_code == 200
            assert resp1.json()["_routing"]["agent"] == "artificer"

            # Second: vague follow-up (would normally classify as chat)
            resp2 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [
                        {
                            "role": "user",
                            "content": "write a function to sort a list in utils.py with type hints and pytest tests",
                        },
                        {
                            "role": "assistant",
                            "content": "I'm the Artificer, working on your code.",
                        },
                        {
                            "role": "user",
                            "content": "yeah that looks good but make it handle empty lists too",
                        },
                    ],
                    "session_id": "sticky-test",
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp2.status_code == 200
            # Should STILL be artificer, not default
            assert resp2.json()["_routing"]["agent"] == "artificer"

    def test_explicit_chat_breaks_sticky(self, sticky_app: FastAPI) -> None:
        """Explicit chat intent should break the sticky session."""
        with TestClient(sticky_app) as client:
            # Code request
            client.post(
                "/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [
                        {
                            "role": "user",
                            "content": "write a function to parse JSON in parser.py with tests",
                        }
                    ],
                    "session_id": "break-test",
                },
                headers={"Authorization": "Bearer sk-test"},
            )

            # Explicit greeting — should go to default
            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [{"role": "user", "content": "hello how are you"}],
                    "session_id": "break-test-new",  # new session
                },
                headers={"Authorization": "Bearer sk-test"},
            )
            assert resp.json()["_routing"]["agent"] == "arbiter"
