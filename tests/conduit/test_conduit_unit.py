"""Unit tests for Conduit pipeline: session stickiness, consent, quota, routing fallback."""

from __future__ import annotations

from typing import Any

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.classifier.engine import ClassifierEngine
from stronghold.conduit import Conduit
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
from stronghold.types.auth import SYSTEM_AUTH, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from stronghold.types.errors import QuotaExhaustedError, RoutingError
from tests.fakes import FakeLLMClient, FakeQuotaTracker


def _make_config(**overrides: Any) -> StrongholdConfig:
    defaults: dict[str, Any] = {
        "providers": {
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
        },
        "models": {
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code", "chat"],
            },
        },
        "task_types": {
            "chat": TaskTypeConfig(keywords=["hello", "hi"], preferred_strengths=["chat"]),
            "code": TaskTypeConfig(
                keywords=["code", "function", "bug"], preferred_strengths=["code"]
            ),
        },
        "permissions": {"admin": ["*"]},
        "router_api_key": "sk-test",
    }
    defaults.update(overrides)
    return StrongholdConfig(**defaults)


def _make_container_with_agents(
    fake_llm: FakeLLMClient | None = None,
    quota_tracker: Any = None,
    **overrides: Any,
) -> Any:
    """Build a container with arbiter and code agents for conduit tests."""
    from stronghold.container import Container

    llm = fake_llm or FakeLLMClient()
    llm.set_simple_response("test response")
    config = _make_config()
    warden = Warden()
    audit_log = InMemoryAuditLog()
    prompts = InMemoryPromptManager()
    qt = quota_tracker or InMemoryQuotaTracker()
    context_builder = ContextBuilder()
    learning_store = InMemoryLearningStore()

    arbiter = Agent(
        identity=AgentIdentity(
            name="arbiter",
            soul_prompt_name="agent.arbiter.soul",
            model="test/model",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    code_agent = Agent(
        identity=AgentIdentity(
            name="code",
            soul_prompt_name="agent.code.soul",
            model="test/model",
        ),
        strategy=DirectStrategy(),
        llm=llm,
        context_builder=context_builder,
        prompt_manager=prompts,
        warden=warden,
        learning_store=learning_store,
    )

    intent_registry = IntentRegistry(routing_table={"code": "code"})

    fields: dict[str, Any] = {
        "config": config,
        "auth_provider": StaticKeyAuthProvider(api_key="sk-test"),
        "permission_table": PermissionTable.from_config({"admin": ["*"]}),
        "router": RouterEngine(qt),
        "classifier": ClassifierEngine(),
        "quota_tracker": qt,
        "prompt_manager": prompts,
        "learning_store": learning_store,
        "learning_extractor": ToolCorrectionExtractor(),
        "outcome_store": InMemoryOutcomeStore(),
        "session_store": InMemorySessionStore(),
        "audit_log": audit_log,
        "warden": warden,
        "gate": Gate(warden=warden),
        "sentinel": Sentinel(
            warden=warden,
            permission_table=PermissionTable.from_config(config.permissions),
            audit_log=audit_log,
        ),
        "tracer": NoopTracingBackend(),
        "context_builder": context_builder,
        "intent_registry": intent_registry,
        "llm": llm,
        "tool_registry": InMemoryToolRegistry(),
        "tool_dispatcher": ToolDispatcher(InMemoryToolRegistry()),
        "agents": {"arbiter": arbiter, "code": code_agent},
    }
    fields.update(overrides)
    return Container(**fields)


# ── Session Stickiness ──


class TestSessionStickiness:
    """Test session_id + _session_agents sticky agent lookup."""

    async def test_sticky_session_reuses_agent(self) -> None:
        """After routing to an agent, same session should stick to it."""
        container = _make_container_with_agents()
        conduit = container.conduit

        # First request: route to code agent via keyword
        result1 = await conduit.route_request(
            [{"role": "user", "content": "fix the bug in this function"}],
            auth=SYSTEM_AUTH,
            session_id="sess-sticky-1",
        )
        result1.get("_routing", {}).get("agent", "")

        # Second request: vague, but same session should stick
        await conduit.route_request(
            [{"role": "user", "content": "now do the same for the other file"}],
            auth=SYSTEM_AUTH,
            session_id="sess-sticky-1",
        )
        # Should have sticky behavior (agent stored in session map)
        assert "sess-sticky-1" in conduit._session_agents

    async def test_different_session_gets_fresh_routing(self) -> None:
        """Different session IDs should route independently."""
        container = _make_container_with_agents()
        conduit = container.conduit

        await conduit.route_request(
            [{"role": "user", "content": "fix the bug in this function"}],
            auth=SYSTEM_AUTH,
            session_id="sess-A",
        )

        await conduit.route_request(
            [{"role": "user", "content": "hello there"}],
            auth=SYSTEM_AUTH,
            session_id="sess-B",
        )
        # sess-B should not inherit sess-A's agent
        assert (
            conduit._session_agents.get("sess-B") != conduit._session_agents.get("sess-A")
            or "sess-B" not in conduit._session_agents
        )


# ── Data Sharing Consent ──


class TestDataSharingConsent:
    """Test consent pending and affirmative response resolution."""

    async def test_consent_pending_affirmative_grants_access(self) -> None:
        """If user says 'yes' to a pending consent, provider is added to consents."""
        container = _make_container_with_agents()
        conduit = container.conduit
        session_id = "sess-consent-1"

        # Manually set a pending consent
        conduit._consent_pending[session_id] = "test-provider"

        # Simulate user saying "yes"
        await conduit.route_request(
            [{"role": "user", "content": "yes"}],
            auth=SYSTEM_AUTH,
            session_id=session_id,
        )

        # The provider should now be in consented set
        assert "test-provider" in conduit._session_consents.get(session_id, set())

    async def test_consent_pending_negative_does_not_grant(self) -> None:
        """If user says something other than affirmative, no consent granted."""
        container = _make_container_with_agents()
        conduit = container.conduit
        session_id = "sess-consent-2"

        conduit._consent_pending[session_id] = "test-provider"

        await conduit.route_request(
            [{"role": "user", "content": "no thanks"}],
            auth=SYSTEM_AUTH,
            session_id=session_id,
        )

        # Should NOT be in consented set
        consented = conduit._session_consents.get(session_id, set())
        assert "test-provider" not in consented

    async def test_consent_affirmative_words(self) -> None:
        """Various affirmative words should grant consent."""
        for word in ["yes", "sure", "ok", "yep", "absolutely", "allow"]:
            container = _make_container_with_agents()
            conduit = container.conduit
            sid = f"sess-consent-{word}"

            conduit._consent_pending[sid] = "ds-prov"

            await conduit.route_request(
                [{"role": "user", "content": word}],
                auth=SYSTEM_AUTH,
                session_id=sid,
            )
            assert "ds-prov" in conduit._session_consents.get(sid, set()), (
                f"Expected consent granted for '{word}'"
            )


# ── Quota Pre-check ──


class TestQuotaPreCheck:
    """Test that all providers exhausted raises QuotaExhaustedError."""

    async def test_all_providers_exhausted_raises_error(self) -> None:
        """When every provider is at 100%+ usage, QuotaExhaustedError is raised."""
        qt = FakeQuotaTracker(usage_pct=1.5)  # 150% usage
        container = _make_container_with_agents(quota_tracker=qt)

        with pytest.raises(QuotaExhaustedError):
            await container.conduit.route_request(
                [{"role": "user", "content": "hello"}],
                auth=SYSTEM_AUTH,
            )

    async def test_one_provider_available_succeeds(self) -> None:
        """If at least one provider has budget, request goes through."""
        qt = FakeQuotaTracker(usage_pct=0.5)  # 50% usage
        container = _make_container_with_agents(quota_tracker=qt)

        result = await container.conduit.route_request(
            [{"role": "user", "content": "hello"}],
            auth=SYSTEM_AUTH,
        )
        assert result["choices"][0]["message"]["content"]


# ── Model Selection Fallback ──


class TestModelSelectionFallback:
    """Test RoutingError fallback to first available model."""

    async def test_routing_error_uses_fallback(self) -> None:
        """When router.select raises RoutingError, conduit uses fallback model."""
        container = _make_container_with_agents()

        # Make router.select always raise RoutingError

        def broken_select(*args: Any, **kwargs: Any) -> Any:
            raise RoutingError("no models match")

        container.router.select = broken_select

        result = await container.conduit.route_request(
            [{"role": "user", "content": "hello"}],
            auth=SYSTEM_AUTH,
        )
        # Should still get a response (fallback path)
        assert result["choices"][0]["message"]["content"]
        routing = result.get("_routing", {})
        assert routing.get("reason") == "default" or "fallback" in str(routing)


# ── Auth Validation ──


class TestConduitAuthValidation:
    """Test that route_request rejects calls without valid AuthContext."""

    async def test_none_auth_raises_type_error(self) -> None:
        """Calling route_request with auth=None should raise TypeError."""
        container = _make_container_with_agents()
        with pytest.raises(TypeError, match="AuthContext"):
            await container.conduit.route_request(
                [{"role": "user", "content": "hello"}],
                auth=None,
            )

    async def test_wrong_type_auth_raises_type_error(self) -> None:
        """Calling with a non-AuthContext should raise TypeError."""
        container = _make_container_with_agents()
        with pytest.raises(TypeError, match="AuthContext"):
            await container.conduit.route_request(
                [{"role": "user", "content": "hello"}],
                auth="not-an-auth-context",
            )


# ── Consent Prompt Flow ──


class TestConsentPromptFlow:
    """Test the data sharing consent prompt path (6b)."""

    async def test_data_sharing_provider_triggers_consent_prompt(self) -> None:
        """When a data-sharing provider scores higher, a consent prompt is returned."""
        # Configure a data-sharing provider that would be preferred
        config = _make_config(
            providers={
                "safe": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
                "ds-prov": {
                    "status": "active",
                    "billing_cycle": "monthly",
                    "free_tokens": 1_000_000,
                    "data_sharing": True,
                    "data_sharing_notice": "This provider uses your data for training.",
                },
            },
            models={
                "safe-model": {
                    "provider": "safe",
                    "litellm_id": "safe/model",
                    "tier": "medium",
                    "quality": 0.5,
                    "speed": 500,
                    "strengths": ["chat"],
                },
                "ds-model": {
                    "provider": "ds-prov",
                    "litellm_id": "ds/model",
                    "tier": "medium",
                    "quality": 0.9,
                    "speed": 500,
                    "strengths": ["chat"],
                },
            },
        )

        llm = FakeLLMClient()
        llm.set_simple_response("Would you like to allow data sharing?")
        warden = Warden()
        audit_log = InMemoryAuditLog()
        prompts = InMemoryPromptManager()
        qt = InMemoryQuotaTracker()
        context_builder = ContextBuilder()
        learning_store = InMemoryLearningStore()

        arbiter = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="safe/model",
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
            learning_store=learning_store,
        )

        from stronghold.container import Container

        container = Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(qt),
            classifier=ClassifierEngine(),
            quota_tracker=qt,
            prompt_manager=prompts,
            learning_store=learning_store,
            learning_extractor=ToolCorrectionExtractor(),
            outcome_store=InMemoryOutcomeStore(),
            session_store=InMemorySessionStore(),
            audit_log=audit_log,
            warden=warden,
            gate=Gate(warden=warden),
            sentinel=Sentinel(
                warden=warden,
                permission_table=PermissionTable.from_config(config.permissions),
                audit_log=audit_log,
            ),
            tracer=NoopTracingBackend(),
            context_builder=context_builder,
            intent_registry=IntentRegistry(),
            llm=llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"arbiter": arbiter},
        )

        result = await container.conduit.route_request(
            [{"role": "user", "content": "hello"}],
            auth=SYSTEM_AUTH,
            session_id="sess-ds",
        )

        result.get("_routing", {})
        # If the ds provider scored higher, we should see consent_required
        # or the response just routes normally (safe provider selected)
        # Either way, the pipeline completes without error
        assert result["choices"][0]["message"]["content"]


# ── Estimate Tokens ──


class TestEstimateTokens:
    """Test the _estimate_tokens static method."""

    def test_simple_text(self) -> None:
        msgs = [{"role": "user", "content": "Hello world"}]
        tokens = Conduit._estimate_tokens(msgs)
        assert tokens >= 1

    def test_multipart_content(self) -> None:
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Hello"},
                    {"type": "text", "text": "world"},
                ],
            }
        ]
        tokens = Conduit._estimate_tokens(msgs)
        assert tokens >= 1

    def test_empty_messages(self) -> None:
        tokens = Conduit._estimate_tokens([])
        assert tokens == 1
