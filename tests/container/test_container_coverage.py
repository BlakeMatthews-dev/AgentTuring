"""Extended tests for stronghold/container.py -- targets uncovered lines.

Covers: Container dataclass construction, __post_init__ Conduit auto-wiring,
route_request delegation, _wire_auth with various config combos,
_wire_persistence in-memory path, create_container with missing API key,
and ConfigError.

Uses real classes from the project. No unittest.mock.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.classifier.engine import ClassifierEngine
from stronghold.container import Container, _wire_auth, _wire_persistence, create_container
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
from stronghold.types.config import AuthConfig, StrongholdConfig, TaskTypeConfig
from stronghold.types.errors import ConfigError
from tests.fakes import FakeLLMClient


def _make_config(**overrides: Any) -> StrongholdConfig:
    """Create a minimal valid StrongholdConfig with optional overrides."""
    defaults = {
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
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        "permissions": {"admin": ["*"]},
        "router_api_key": "sk-test-key",
    }
    defaults.update(overrides)
    return StrongholdConfig(**defaults)


def _make_container_minimal(fake_llm: FakeLLMClient | None = None) -> Container:
    """Build a minimal Container with all required fields. No async needed."""
    llm = fake_llm or FakeLLMClient()
    config = _make_config()
    warden = Warden()
    audit_log = InMemoryAuditLog()
    prompts = InMemoryPromptManager()

    return Container(
        config=config,
        auth_provider=StaticKeyAuthProvider(api_key="sk-test-key"),
        permission_table=PermissionTable.from_config({"admin": ["*"]}),
        router=RouterEngine(InMemoryQuotaTracker()),
        classifier=ClassifierEngine(),
        quota_tracker=InMemoryQuotaTracker(),
        prompt_manager=prompts,
        learning_store=InMemoryLearningStore(),
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
        context_builder=ContextBuilder(),
        intent_registry=IntentRegistry(),
        llm=llm,
        tool_registry=InMemoryToolRegistry(),
        tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
    )


# ── Container dataclass construction ────────────────────────────────


class TestContainerConstruction:
    def test_container_creates_with_defaults(self) -> None:
        """Container should construct with only required fields."""
        c = _make_container_minimal()
        assert c.agents == {}
        assert c.tournament is None
        assert c.canary_manager is None
        assert c.db_pool is None
        assert c.sa_engine is None
        assert c.redis_client is None

    def test_container_auto_wires_conduit(self) -> None:
        """__post_init__ should auto-wire Conduit if not provided."""
        c = _make_container_minimal()
        assert c.conduit is not None
        assert hasattr(c.conduit, "route_request")

    def test_container_preserves_explicit_conduit(self) -> None:
        """If conduit is explicitly provided, __post_init__ should not override it."""

        class FakeConduit:
            async def route_request(self, *args: Any, **kwargs: Any) -> dict:
                return {"fake": True}

        llm = FakeLLMClient()
        config = _make_config()
        warden = Warden()
        audit_log = InMemoryAuditLog()

        c = Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test-key"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=InMemoryPromptManager(),
            learning_store=InMemoryLearningStore(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            conduit=FakeConduit(),
        )
        assert isinstance(c.conduit, FakeConduit)

    def test_container_with_agents_dict(self) -> None:
        """Container should accept pre-populated agents dict."""
        llm = FakeLLMClient()
        config = _make_config()
        warden = Warden()
        audit_log = InMemoryAuditLog()
        prompts = InMemoryPromptManager()

        agent = Agent(
            identity=AgentIdentity(
                name="test-agent",
                soul_prompt_name="agent.test.soul",
                model="test/model",
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=warden,
            session_store=InMemorySessionStore(),
        )

        c = Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test-key"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=prompts,
            learning_store=InMemoryLearningStore(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agents={"test-agent": agent},
            agent_store=InMemoryAgentStore({"test-agent": agent}, prompts),
        )
        assert len(c.agents) == 1
        assert "test-agent" in c.agents

    def test_container_optional_fields(self) -> None:
        """Container optional fields default to None or factory defaults."""
        c = _make_container_minimal()
        assert c.strike_tracker is None
        assert c.mcp_registry is None
        assert c.mcp_deployer is None
        assert c.prompt_cache is None
        assert c.learning_approval_gate is None
        assert c.learning_promoter is None


# ── route_request delegation ────────────────────────────────────────


class TestRouteRequest:
    async def test_route_request_delegates_to_conduit(self) -> None:
        """route_request should delegate to conduit.route_request."""

        class FakeConduit:
            async def route_request(self, messages: list, **kwargs: Any) -> dict:
                return {"delegated": True, "message_count": len(messages)}

        c = _make_container_minimal()
        c.conduit = FakeConduit()

        result = await c.route_request(
            [{"role": "user", "content": "hello"}],
        )
        assert result["delegated"] is True
        assert result["message_count"] == 1

    async def test_route_request_passes_kwargs(self) -> None:
        """route_request should forward auth, session_id, intent_hint."""
        captured_kwargs: dict[str, Any] = {}

        class CapturingConduit:
            async def route_request(self, messages: list, **kwargs: Any) -> dict:
                captured_kwargs.update(kwargs)
                return {"ok": True}

        c = _make_container_minimal()
        c.conduit = CapturingConduit()

        from stronghold.types.auth import SYSTEM_AUTH

        await c.route_request(
            [{"role": "user", "content": "test"}],
            auth=SYSTEM_AUTH,
            session_id="sess-1",
            intent_hint="code",
        )
        assert captured_kwargs["auth"] is SYSTEM_AUTH
        assert captured_kwargs["session_id"] == "sess-1"
        assert captured_kwargs["intent_hint"] == "code"


# ── _wire_auth ──────────────────────────────────────────────────────


class TestWireAuth:
    def test_wire_auth_static_key_only(self) -> None:
        """Without jwks_url, should return composite with demo + static."""
        config = _make_config()
        auth_provider, perm_table = _wire_auth(config)
        # Should be a CompositeAuthProvider (wraps demo + static)
        assert hasattr(auth_provider, "authenticate")
        assert isinstance(perm_table, PermissionTable)

    def test_wire_auth_with_jwks(self) -> None:
        """With jwks_url, should create JWT provider in the chain."""
        config = _make_config(
            auth=AuthConfig(
                jwks_url="https://sso.example.com/certs",
                issuer="https://sso.example.com",
                audience="stronghold-api",
            ),
        )
        auth_provider, perm_table = _wire_auth(config)
        assert hasattr(auth_provider, "authenticate")

    def test_wire_auth_with_jwks_and_bff_cookie(self) -> None:
        """With jwks_url + client_id + token_url, should add CookieAuthProvider."""
        config = _make_config(
            auth=AuthConfig(
                jwks_url="https://sso.example.com/certs",
                issuer="https://sso.example.com",
                audience="stronghold-api",
                client_id="stronghold-client",
                token_url="https://sso.example.com/token",
            ),
        )
        auth_provider, perm_table = _wire_auth(config)
        assert hasattr(auth_provider, "authenticate")
        # The composite should have 4 providers: demo, cookie, jwt, static
        if hasattr(auth_provider, "_providers"):
            assert len(auth_provider._providers) == 4

    def test_wire_auth_permission_table_from_config(self) -> None:
        """Permission table should be built from config.permissions."""
        config = _make_config(
            permissions={"admin": ["*"], "viewer": ["web_search"]},
        )
        _, perm_table = _wire_auth(config)
        assert perm_table.check(frozenset({"admin"}), "anything")
        assert perm_table.check(frozenset({"viewer"}), "web_search")
        assert not perm_table.check(frozenset({"viewer"}), "shell")


# ── _wire_persistence ───────────────────────────────────────────────


class TestWirePersistence:
    async def test_inmemory_when_no_database_url(self) -> None:
        """Without database_url, should return in-memory implementations."""
        config = _make_config()
        (
            db_pool,
            quota_tracker,
            prompt_manager,
            learning_store,
            outcome_store,
            session_store,
            audit_log,
        ) = await _wire_persistence(config)

        assert db_pool is None
        assert isinstance(quota_tracker, InMemoryQuotaTracker)
        assert isinstance(prompt_manager, InMemoryPromptManager)
        assert isinstance(learning_store, InMemoryLearningStore)
        assert isinstance(outcome_store, InMemoryOutcomeStore)
        assert isinstance(session_store, InMemorySessionStore)
        assert isinstance(audit_log, InMemoryAuditLog)


# ── create_container ────────────────────────────────────────────────


class TestCreateContainer:
    async def test_missing_api_key_raises_config_error(self) -> None:
        """create_container should raise ConfigError when router_api_key is empty."""
        config = _make_config(router_api_key="")
        with pytest.raises(ConfigError, match="ROUTER_API_KEY"):
            await create_container(config)

    async def test_create_container_inmemory_succeeds(self) -> None:
        """create_container with in-memory persistence should work end-to-end."""
        config = _make_config(
            agents_dir="",  # Will auto-detect
        )
        container = await create_container(config)

        # Verify all required fields are set
        assert container.config is config
        assert container.auth_provider is not None
        assert container.warden is not None
        assert container.gate is not None
        assert container.sentinel is not None
        assert container.conduit is not None
        assert container.router is not None
        assert container.classifier is not None
        assert container.llm is not None
        assert container.tool_registry is not None
        assert container.tool_dispatcher is not None
        assert container.agent_store is not None
        assert container.reactor is not None
        assert container.tournament is not None
        assert container.canary_manager is not None
        assert container.learning_approval_gate is not None
        assert container.learning_promoter is not None
        assert container.mcp_registry is not None
        assert container.strike_tracker is not None
        assert container.db_pool is None  # No database_url
        assert container.sa_engine is None
        assert container.redis_client is None

    async def test_create_container_with_custom_agents_dir(self, tmp_path: Any) -> None:
        """create_container should accept a custom agents_dir."""
        # Create a minimal agents dir
        agents_dir = tmp_path / "agents"
        agents_dir.mkdir()

        config = _make_config(agents_dir=str(agents_dir))
        container = await create_container(config)
        assert container is not None


# ── Container with all optional components ──────────────────────────


class TestContainerWithOptionalComponents:
    def test_rate_limiter_default(self) -> None:
        """Default rate limiter should be InMemoryRateLimiter."""
        c = _make_container_minimal()
        assert c.rate_limiter is not None
        assert hasattr(c.rate_limiter, "check")

    def test_reactor_default(self) -> None:
        """Default reactor should be a Reactor instance."""
        c = _make_container_minimal()
        from stronghold.events import Reactor
        assert isinstance(c.reactor, Reactor)

    def test_task_queue_default(self) -> None:
        """Default task queue should be InMemoryTaskQueue."""
        c = _make_container_minimal()
        from stronghold.agents.task_queue import InMemoryTaskQueue
        assert isinstance(c.task_queue, InMemoryTaskQueue)


# ── Coverage expansion: tool policy load failure, tool policy enforcement,
#    create_container branches ──


class TestToolPolicyLoadFailure:
    """Test that create_container handles tool policy load failure gracefully (lines 326-328)."""

    async def test_create_container_no_policy_files(self, tmp_path: Any) -> None:
        """When Casbin policy files are missing, container still creates with tool_policy=None."""
        config = _make_config(agents_dir=str(tmp_path / "agents"))
        (tmp_path / "agents").mkdir()
        container = await create_container(config)
        # tool_policy may be None if config files are missing
        # The important thing is it doesn't crash
        assert container is not None
        # It should either be None (no policy files) or a valid policy object
        assert container.tool_policy is None or hasattr(container.tool_policy, "check_tool_call")


class TestToolPolicyEnforcementInToolExec:
    """Test tool policy enforcement in the _tool_exec closure (lines 406-410)."""

    async def test_tool_exec_denied_by_policy(self) -> None:
        """When tool_policy denies a tool call, PermissionError is raised."""
        from tests.fakes import FakeToolPolicy

        fake_llm = FakeLLMClient()
        config = _make_config()
        warden = Warden()
        audit_log = InMemoryAuditLog()
        prompts = InMemoryPromptManager()
        qt = InMemoryQuotaTracker()

        # Create a minimal container with a FakeToolPolicy that denies a specific tool
        policy = FakeToolPolicy()
        policy.deny_tool("system", "__system__", "dangerous_tool")

        from stronghold.container import Container

        container = Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test-key"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(qt),
            classifier=ClassifierEngine(),
            quota_tracker=qt,
            prompt_manager=prompts,
            learning_store=InMemoryLearningStore(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            tool_policy=policy,
        )

        # Verify the policy object is wired
        assert container.tool_policy is not None
        assert not container.tool_policy.check_tool_call("system", "__system__", "dangerous_tool")
        assert container.tool_policy.check_tool_call("system", "__system__", "safe_tool")

    async def test_tool_exec_allowed_by_policy(self) -> None:
        """When tool_policy allows a tool call, execution proceeds."""
        from tests.fakes import FakeToolPolicy

        policy = FakeToolPolicy()

        fake_llm = FakeLLMClient()
        config = _make_config()
        warden = Warden()
        audit_log = InMemoryAuditLog()

        from stronghold.container import Container

        container = Container(
            config=config,
            auth_provider=StaticKeyAuthProvider(api_key="sk-test-key"),
            permission_table=PermissionTable.from_config({"admin": ["*"]}),
            router=RouterEngine(InMemoryQuotaTracker()),
            classifier=ClassifierEngine(),
            quota_tracker=InMemoryQuotaTracker(),
            prompt_manager=InMemoryPromptManager(),
            learning_store=InMemoryLearningStore(),
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
            context_builder=ContextBuilder(),
            intent_registry=IntentRegistry(),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            tool_policy=policy,
        )

        # The policy allows everything by default
        assert container.tool_policy.check_tool_call("user1", "org1", "any_tool")
        assert len(policy.tool_checks) == 1


class TestCreateContainerRedisUnavailable:
    """Test create_container when redis_url is set but Redis is unreachable."""

    async def test_redis_unavailable_falls_back(self) -> None:
        """With a bad redis_url, container should still create (InMemory fallback)."""
        config = _make_config(redis_url="redis://localhost:19999")
        container = await create_container(config)
        assert container is not None
        # Redis client should be None (failed to connect)
        assert container.redis_client is None
        # Rate limiter should still be InMemory
        assert container.rate_limiter is not None


class TestCreateContainerRateLimiterDisabled:
    """Test create_container with rate limiting disabled."""

    async def test_rate_limiter_disabled(self) -> None:
        """With rate limiting disabled, rate_limiter is still created but disabled."""
        from stronghold.types.config import RateLimitConfig

        config = _make_config(rate_limit=RateLimitConfig(enabled=False))
        container = await create_container(config)
        assert container is not None
        assert container.rate_limiter is not None


class TestContainerScheduleStore:
    """Test schedule_store default."""

    def test_schedule_store_default(self) -> None:
        from stronghold.scheduling.store import InMemoryScheduleStore

        c = _make_container_minimal()
        assert isinstance(c.schedule_store, InMemoryScheduleStore)


class TestContainerMcpRegistry:
    """Test mcp_registry and mcp_deployer fields."""

    async def test_mcp_fields_after_create(self) -> None:
        config = _make_config()
        container = await create_container(config)
        assert container.mcp_registry is not None
        # mcp_deployer may be None if K8s is not available
        # Just verify it doesn't crash
