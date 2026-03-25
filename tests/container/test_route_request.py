"""Tests for Container.route_request().

Exercises the full classification -> routing -> agent pipeline with FakeLLM.
"""

from __future__ import annotations

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.agents.task_queue import InMemoryTaskQueue
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
from stronghold.types.config import (
    RoutingConfig,
    SecurityConfig,
    SessionsConfig,
    StrongholdConfig,
    TaskTypeConfig,
)
from stronghold.types.auth import AuthContext, IdentityKind
from tests.fakes import FakeLLMClient

_TEST_AUTH = AuthContext(
    user_id="test-user",
    username="test-user",
    org_id="test-org",
    roles=frozenset({"user"}),
    kind=IdentityKind.USER,
    auth_method="test",
)


def _build_config() -> StrongholdConfig:
    return StrongholdConfig(
        providers={
            "test_provider": {
                "status": "active",
                "billing_cycle": "monthly",
                "free_tokens": 1_000_000_000,
            },
        },
        models={
            "test-medium": {
                "provider": "test_provider",
                "tier": "medium",
                "quality": 0.6,
                "speed": 500,
                "litellm_id": "test/medium",
                "strengths": ["code", "reasoning"],
            },
            "test-small": {
                "provider": "test_provider",
                "tier": "small",
                "quality": 0.4,
                "speed": 1000,
                "litellm_id": "test/small",
                "strengths": ["chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(
                keywords=["hello", "hi", "hey", "thanks"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
            "code": TaskTypeConfig(
                keywords=["code", "function", "bug", "error", "implement", "class", "module"],
                min_tier="medium",
                preferred_strengths=["code"],
            ),
            "automation": TaskTypeConfig(
                keywords=["light", "fan", "turn on", "turn off"],
                min_tier="small",
                preferred_strengths=["chat"],
            ),
        },
        routing=RoutingConfig(),
        sessions=SessionsConfig(),
        security=SecurityConfig(),
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )


async def _build_container(
    *,
    llm: FakeLLMClient | None = None,
) -> Container:
    llm = llm or FakeLLMClient()
    config = _build_config()
    prompt_manager = InMemoryPromptManager()
    learning_store = InMemoryLearningStore()
    context_builder = ContextBuilder()
    warden = Warden()
    quota_tracker = InMemoryQuotaTracker()
    session_store = InMemorySessionStore()
    tracer = NoopTracingBackend()

    # Seed souls
    await prompt_manager.upsert(
        "agent.arbiter.soul", "You are the Conduit.", label="production"
    )
    await prompt_manager.upsert(
        "agent.artificer.soul", "You are the Artificer, code specialist.", label="production"
    )

    arbiter_agent = Agent(
        identity=AgentIdentity(name="arbiter", soul_prompt_name="agent.arbiter.soul", model="auto"),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompt_manager,
        warden=warden,
        session_store=session_store,
        tracer=tracer,
    )

    artificer_agent = Agent(
        identity=AgentIdentity(
            name="artificer",
            soul_prompt_name="agent.artificer.soul",
            model="auto",
            reasoning_strategy="direct",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompt_manager,
        warden=warden,
        session_store=session_store,
        tracer=tracer,
    )

    agents = {
        "arbiter": arbiter_agent,
        "artificer": artificer_agent,
    }

    audit_log = InMemoryAuditLog()
    perm_table = PermissionTable.from_config(config.permissions)

    return Container(
        config=config,
        auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
        permission_table=perm_table,
        router=RouterEngine(quota_tracker),
        classifier=ClassifierEngine(),
        quota_tracker=quota_tracker,
        prompt_manager=prompt_manager,
        learning_store=learning_store,
        learning_extractor=ToolCorrectionExtractor(),
        outcome_store=InMemoryOutcomeStore(),
        session_store=session_store,
        audit_log=audit_log,
        warden=warden,
        gate=Gate(warden=warden),
        sentinel=Sentinel(
            warden=warden,
            permission_table=perm_table,
            audit_log=audit_log,
        ),
        tracer=tracer,
        context_builder=context_builder,
        intent_registry=IntentRegistry(),
        llm=llm,
        tool_registry=InMemoryToolRegistry(),
        tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
        agents=agents,
    )


class TestChatRouting:
    @pytest.mark.asyncio
    async def test_chat_routes_to_default(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Hello there!")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [{"role": "user", "content": "hello"}],
            auth=_TEST_AUTH,
        )
        assert result["object"] == "chat.completion"
        assert result["choices"][0]["message"]["content"] == "Hello there!"
        # Chat should route to default agent
        assert result["_routing"]["agent"] == "arbiter"

    @pytest.mark.asyncio
    async def test_chat_has_intent_metadata(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Hi!")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [{"role": "user", "content": "hey there how are you"}],
            auth=_TEST_AUTH,
        )
        assert "_routing" in result
        assert "intent" in result["_routing"]
        assert "task_type" in result["_routing"]["intent"]


class TestCodeRouting:
    @pytest.mark.asyncio
    async def test_code_request_routes_to_artificer(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("Here is the code implementation...")
        container = await _build_container(llm=llm)

        # "write a function" is a strong indicator (+3), plus "implement" keyword (+1)
        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to implement binary search "
                        "in search.py that returns True for found items"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )
        assert result["_routing"]["agent"] == "artificer"

    @pytest.mark.asyncio
    async def test_code_request_openai_format(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("done")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function called UserManager in user.py "
                        "with create and delete methods that return typed results"
                    ),
                }
            ],
            auth=_TEST_AUTH,
        )
        assert result["object"] == "chat.completion"
        assert "choices" in result
        assert result["choices"][0]["message"]["role"] == "assistant"


class TestHintBypassesClassification:
    @pytest.mark.asyncio
    async def test_hint_routes_directly(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("code response")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a Python function in utils.py to validate "
                        "email addresses and return True for valid ones"
                    ),
                }
            ],
            auth=_TEST_AUTH,
            intent_hint="code",
        )
        assert result["_routing"]["intent"]["task_type"] == "code"
        assert result["_routing"]["intent"]["classified_by"] == "hint"

    @pytest.mark.asyncio
    async def test_hint_overrides_keyword_classification(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("treated as chat")
        container = await _build_container(llm=llm)

        # This would normally classify as code, but hint says chat
        # Chat task type does not go through sufficiency check
        result = await container.route_request(
            [{"role": "user", "content": "fix the function bug in auth.py"}],
            auth=_TEST_AUTH,
            intent_hint="chat",
        )
        assert result["_routing"]["intent"]["task_type"] == "chat"

    @pytest.mark.asyncio
    async def test_invalid_hint_ignored(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        container = await _build_container(llm=llm)

        # Invalid hint should fall through to normal classification
        result = await container.route_request(
            [{"role": "user", "content": "hello"}],
            auth=_TEST_AUTH,
            intent_hint="nonexistent_type",
        )
        # Should still work, classified by keywords
        assert result["object"] == "chat.completion"


class TestSessionStickiness:
    @pytest.mark.asyncio
    async def test_session_sticks_to_specialist(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("code answer")
        container = await _build_container(llm=llm)

        # First request: use hint to force artificer routing
        result1 = await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to validate JWT tokens "
                        "in auth.py that returns True for valid tokens"
                    ),
                }
            ],
            auth=_TEST_AUTH,
            session_id="sticky-sess",
            intent_hint="code",
        )
        assert result1["_routing"]["agent"] == "artificer"

        # Second request: ambiguous, but same session -> should stick to artificer
        llm.set_simple_response("follow up answer")
        result2 = await container.route_request(
            [{"role": "user", "content": "can you also add a test for that"}],
            auth=_TEST_AUTH,
            session_id="sticky-sess",
        )
        # Should stick to artificer due to session stickiness
        assert result2["_routing"]["agent"] == "artificer"

    @pytest.mark.asyncio
    async def test_different_session_no_stickiness(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("code answer")
        container = await _build_container(llm=llm)

        # First request to session A (use hint to ensure artificer)
        await container.route_request(
            [
                {
                    "role": "user",
                    "content": (
                        "Write a function to implement binary search "
                        "in utils.py that returns the index"
                    ),
                }
            ],
            auth=_TEST_AUTH,
            session_id="session-A",
            intent_hint="code",
        )

        # Request to different session B with chat content
        llm.set_simple_response("hi there")
        result = await container.route_request(
            [{"role": "user", "content": "hello how are you"}],
            auth=_TEST_AUTH,
            session_id="session-B",
        )
        # Should NOT be sticky to artificer
        assert result["_routing"]["agent"] == "arbiter"


class TestResponseFormat:
    @pytest.mark.asyncio
    async def test_result_has_id(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [{"role": "user", "content": "hello"}],
            auth=_TEST_AUTH,
        )
        assert "id" in result
        assert result["id"].startswith("stronghold-")

    @pytest.mark.asyncio
    async def test_result_has_usage(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [{"role": "user", "content": "hello"}],
            auth=_TEST_AUTH,
        )
        assert "usage" in result

    @pytest.mark.asyncio
    async def test_result_has_model(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [{"role": "user", "content": "hello"}],
            auth=_TEST_AUTH,
        )
        assert "model" in result
        assert result["model"]  # Non-empty

    @pytest.mark.asyncio
    async def test_routing_metadata_has_reason(self) -> None:
        llm = FakeLLMClient()
        llm.set_simple_response("ok")
        container = await _build_container(llm=llm)

        result = await container.route_request(
            [{"role": "user", "content": "hello"}],
            auth=_TEST_AUTH,
        )
        assert "reason" in result["_routing"]
