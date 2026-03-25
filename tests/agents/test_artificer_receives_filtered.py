"""Test that Artificer receives filtered context when routed from chat."""

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


class TestArtificerFilteredContext:
    @pytest.mark.asyncio
    async def test_greeting_stripped_before_artificer(self) -> None:
        """When chat has greetings then code request, Artificer shouldn't see greetings."""
        app = FastAPI()
        app.include_router(chat_router)

        llm = FakeLLMClient()
        llm.set_simple_response("Here's the code.")
        config = StrongholdConfig(
            providers={
                "t": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1000000}
            },
            models={
                "m": {
                    "provider": "t",
                    "litellm_id": "t/m",
                    "tier": "medium",
                    "quality": 0.7,
                    "speed": 500,
                    "strengths": ["code"],
                }
            },
            task_types={
                "code": TaskTypeConfig(
                    keywords=["function", "bug", "fix"],
                    min_tier="medium",
                    preferred_strengths=["code"],
                )
            },
            permissions={"admin": ["*"]},
            router_api_key="sk-test",
        )
        prompts = InMemoryPromptManager()
        await prompts.upsert("agent.arbiter.soul", "Default.", label="production")
        await prompts.upsert("agent.artificer.soul", "Artificer.", label="production")

        artificer = Agent(
            identity=AgentIdentity(
                name="artificer",
                soul_prompt_name="agent.artificer.soul",
                model="t/m",
                memory_config={},
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )
        default = Agent(
            identity=AgentIdentity(
                name="arbiter", soul_prompt_name="agent.arbiter.soul", model="t/m", memory_config={}
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=Warden(),
        )

        container = Container(
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
            warden=Warden(),
            gate=Gate(warden=Warden()),
            sentinel=Sentinel(
                warden=Warden(),
                permission_table=PermissionTable.from_config({"admin": ["*"]}),
                audit_log=InMemoryAuditLog(),
            ),
            tracer=NoopTracingBackend(),
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry({"code": "artificer"}),
            llm=llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": default, "artificer": artificer},
        )
        app.state.container = container

        # Simulate a session: greeting then code request
        with TestClient(app) as client:
            # First: greeting (goes to session)
            resp1 = client.post(
                "/v1/chat/completions",
                json={
                    "model": "auto",
                    "messages": [
                        {"role": "user", "content": "hey how's it going"},
                        {"role": "assistant", "content": "I'm good!"},
                        {
                            "role": "user",
                            "content": "write a function in validators.py to validate email addresses using regex. Return True for valid emails. Include pytest tests.",
                        },
                    ],
                },
                headers={"Authorization": "Bearer sk-test"},
            )

            assert resp1.status_code == 200

            # Check what the LLM actually received
            last_call = llm.calls[-1]
            user_msgs = [m for m in last_call["messages"] if m.get("role") == "user"]

            # The greeting "hey how's it going" should be filtered out
            all_content = " ".join(m["content"] for m in user_msgs)
            assert "how's it going" not in all_content
            assert "email" in all_content
