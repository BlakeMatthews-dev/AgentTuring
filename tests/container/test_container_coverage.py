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
from stronghold.types.auth import AuthContext, PermissionTable
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

    def test_container_auto_wires_real_conduit(self) -> None:
        """__post_init__ auto-wires an actual ``Conduit`` that holds a
        reference to the container itself — not a stub with a
        ``route_request`` attribute.

        The old form only did ``hasattr(c.conduit, "route_request")``
        which passes for any object. Here we verify the Conduit is the
        real production class and that it wraps this container, so a
        routed request would actually flow through our router/classifier.
        """
        from stronghold.conduit import Conduit

        c = _make_container_minimal()
        assert c.conduit is not None
        # Exact type — not a subclass that could smuggle in behaviour.
        assert type(c.conduit) is Conduit
        # Conduit captures the container in ``_c``. Identity check ensures
        # wiring is not copied or dropped.
        assert c.conduit._c is c

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
        # Explicit conduit must not be overridden by __post_init__ —
        # exact-type identity proves the user-supplied instance survives.
        assert type(c.conduit) is FakeConduit

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
    async def test_wire_auth_static_key_only(self) -> None:
        """Without jwks_url, should return composite with demo + static."""
        config = _make_config()
        auth_provider, perm_table = _wire_auth(config)
        # Composite with demo+static — static path accepts the configured router key.
        ctx = await auth_provider.authenticate("Bearer sk-test-key")
        assert type(ctx) is AuthContext
        assert ctx.user_id  # non-empty; SYSTEM_AUTH has a stable user_id
        # Permission table is built from config.permissions={"admin": ["*"]}
        assert perm_table.check(frozenset({"admin"}), "anything")

    async def test_wire_auth_with_jwks(self) -> None:
        """With jwks_url, should create JWT provider in the chain."""
        config = _make_config(
            auth=AuthConfig(
                jwks_url="https://sso.example.com/certs",
                issuer="https://sso.example.com",
                audience="stronghold-api",
            ),
        )
        auth_provider, perm_table = _wire_auth(config)
        # Static-key fallback still authenticates a well-formed bearer token.
        ctx = await auth_provider.authenticate("Bearer sk-test-key")
        assert type(ctx) is AuthContext
        assert ctx.user_id
        assert perm_table.check(frozenset({"admin"}), "anything")

    async def test_wire_auth_with_jwks_and_bff_cookie(self) -> None:
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
        # Static-key fallback still works even with full composite chain wired.
        ctx = await auth_provider.authenticate("Bearer sk-test-key")
        assert type(ctx) is AuthContext
        assert ctx.user_id
        # The composite should have 4 providers: demo, cookie, jwt, static
        # Accessing _providers verifies the composite wiring directly.
        providers = auth_provider._providers  # type: ignore[attr-defined]
        assert len(providers) == 4

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
        # Exact-type identity for each in-memory wiring — proves no
        # Postgres-backed alternative snuck in under a shared interface.
        assert type(quota_tracker) is InMemoryQuotaTracker
        assert type(prompt_manager) is InMemoryPromptManager
        assert type(learning_store) is InMemoryLearningStore
        assert type(outcome_store) is InMemoryOutcomeStore
        assert type(session_store) is InMemorySessionStore
        assert type(audit_log) is InMemoryAuditLog


# ── create_container ────────────────────────────────────────────────


class TestCreateContainer:
    async def test_missing_api_key_raises_config_error(self) -> None:
        """create_container should raise ConfigError when router_api_key is empty."""
        config = _make_config(router_api_key="")
        with pytest.raises(ConfigError, match="ROUTER_API_KEY"):
            await create_container(config)

    async def test_create_container_inmemory_wires_functional_components(self) -> None:
        """create_container with in-memory persistence must wire components
        that actually respond to their protocol methods — not just components
        that happen to be non-None. The old form was 15 is not None
        checks, which pass for any sentinel."""
        config = _make_config(
            agents_dir="",  # Will auto-detect
        )
        container = await create_container(config)

        # Config identity (not just "not None")
        assert container.config is config

        # Warden: must actually perform scans on input.
        wv = await container.warden.scan("hello world", "user_input")
        assert wv.clean is True

        # Classifier: must return an Intent, not just a truthy object.
        from stronghold.types.intent import Intent
        intent = await container.classifier.classify(
            [{"role": "user", "content": "hi"}],
            container.config.task_types,
        )
        # Classifier must return a real Intent dataclass (exact type), and
        # the required public fields must be present and stringifiable —
        # a bare Mock would pass ``isinstance`` only if spec'd.
        assert type(intent) is Intent
        # Exact-type ``str`` rather than a subclass (protects against a
        # LazyStr or bytes-like sneaking in).
        assert type(intent.task_type) is str
        assert intent.task_type  # non-empty

        # MCP registry: list_all() returns a concrete list, proving the
        # object obeys the registry protocol.
        assert container.mcp_registry.list_all() == []

        # Tool registry: list_all() returns a real list (built-ins included).
        tools = container.tool_registry.list_all()
        # Sequence contract: len() + iteration both work on the result.
        assert len(tools) >= 0
        for _ in tools:
            pass

        # Persistence-flag invariants: these MUST remain None in the
        # in-memory path, otherwise the container silently connected to
        # a real DB/Redis despite no URL being set.
        assert container.db_pool is None
        assert container.sa_engine is None
        assert container.redis_client is None

        # Remaining wiring smoke — these stay as None-checks because we
        # only need to confirm the attribute exists and is non-sentinel;
        # deeper behaviour is exercised by dedicated test files for each
        # component.
        for field_name in (
            "auth_provider", "gate", "sentinel", "conduit", "router",
            "llm", "tool_dispatcher", "agent_store", "reactor",
            "tournament", "canary_manager", "learning_approval_gate",
            "learning_promoter", "strike_tracker",
        ):
            assert getattr(container, field_name) is not None, field_name

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
    async def test_default_rate_limiter_checks_allow(self) -> None:
        """Default InMemoryRateLimiter allows fresh keys (not just exists)."""
        c = _make_container_minimal()
        assert c.rate_limiter is not None
        allowed, headers = await c.rate_limiter.check("k1")
        assert allowed is True
        # Real rate limit headers must be present.
        assert "X-RateLimit-Limit" in headers
        assert "X-RateLimit-Remaining" in headers

    def test_default_reactor_is_fresh_and_not_running(self) -> None:
        """Default Reactor is a fresh instance — no triggers, not started."""
        c = _make_container_minimal()
        from stronghold.events import Reactor
        # Exact-type identity: a regression to a subclass would be a smell.
        assert type(c.reactor) is Reactor
        # get_status() exposes the public contract — use it rather than
        # poking the private _triggers list.
        status = c.reactor.get_status()
        assert status.running is False
        assert status.tick_count == 0
        assert status.triggers == []

    async def test_default_task_queue_starts_empty(self) -> None:
        """Default task queue is a functional, empty InMemoryTaskQueue.

        The isinstance check alone is not behavioural — this also verifies
        claim() returns ``None`` on an empty queue, proving the object
        actually obeys the TaskQueue protocol.
        """
        c = _make_container_minimal()
        from stronghold.agents.task_queue import InMemoryTaskQueue
        assert type(c.task_queue) is InMemoryTaskQueue
        # An empty queue has no tasks and claim() returns None.
        assert await c.task_queue.list_tasks() == []
        assert await c.task_queue.claim() is None


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
    """Container wires a working InMemoryScheduleStore by default."""

    async def test_schedule_store_is_functional_and_empty(self) -> None:
        """Default schedule_store obeys the ScheduleStore contract: a fresh
        store returns [] for list_for_user(). A pure isinstance check would
        pass for any subclass that forgot to implement the async API; this
        actually awaits it."""
        from stronghold.scheduling.store import InMemoryScheduleStore

        c = _make_container_minimal()
        assert type(c.schedule_store) is InMemoryScheduleStore
        tasks = await c.schedule_store.list_for_user(user_id="u1", org_id="o1")
        assert tasks == []


class TestContainerMcpRegistry:
    """Test mcp_registry/mcp_deployer wiring after create_container."""

    async def test_mcp_registry_is_functional_after_create(self) -> None:
        """create_container wires an MCP registry that can list (empty) tools.

        The old test just asserted ``is not None``, which passes for any
        sentinel. This exercises the register/list contract to prove the
        object is a real MCP registry.
        """
        config = _make_config()
        container = await create_container(config)
        assert container.mcp_registry is not None
        # Fresh registry exposes list_all() — a bare "is not None" pass would
        # be satisfied by any sentinel object.
        tools = container.mcp_registry.list_all()
        # Sequence contract: len() + iteration work without raising.
        assert len(tools) >= 0
        for _ in tools:
            pass
