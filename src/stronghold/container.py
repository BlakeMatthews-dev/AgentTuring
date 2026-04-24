"""DI container: wires protocols to implementations."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.factory import create_agents
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.task_queue import InMemoryTaskQueue
from stronghold.api.litellm_client import LiteLLMClient
from stronghold.classifier.engine import ClassifierEngine
from stronghold.events import Reactor
from stronghold.memory.learnings.extractor import ToolCorrectionExtractor
from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.playbooks.registry import InMemoryPlaybookRegistry
from stronghold.prompts.store import InMemoryPromptManager
from stronghold.quota.tracker import InMemoryQuotaTracker
from stronghold.router.selector import RouterEngine
from stronghold.scheduling.store import InMemoryScheduleStore
from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.security.gate import Gate
from stronghold.security.rate_limiter import InMemoryRateLimiter
from stronghold.security.sentinel.audit import InMemoryAuditLog
from stronghold.security.sentinel.policy import Sentinel
from stronghold.security.strikes import InMemoryStrikeTracker
from stronghold.security.tool_policy import ToolPolicyProtocol, create_tool_policy
from stronghold.security.warden.detector import Warden
from stronghold.sessions.store import InMemorySessionStore
from stronghold.tools.executor import ToolDispatcher
from stronghold.tools.registry import InMemoryToolRegistry
from stronghold.tracing.noop import NoopTracingBackend
from stronghold.tracing.phoenix_backend import PhoenixTracingBackend
from stronghold.types.auth import PermissionTable
from stronghold.types.errors import ConfigError

if TYPE_CHECKING:
    from stronghold.agents.base import Agent
    from stronghold.protocols.memory import AuditLog, LearningStore, OutcomeStore, SessionStore
    from stronghold.protocols.prompts import PromptManager
    from stronghold.protocols.quota import QuotaTracker
    from stronghold.protocols.tracing import TracingBackend
    from stronghold.types.config import StrongholdConfig

logger = logging.getLogger("stronghold.container")


@dataclass
class Container:
    """Holds all wired dependencies."""

    config: StrongholdConfig
    auth_provider: StaticKeyAuthProvider
    permission_table: PermissionTable
    router: RouterEngine
    classifier: ClassifierEngine
    quota_tracker: QuotaTracker
    prompt_manager: PromptManager
    learning_store: LearningStore
    learning_extractor: ToolCorrectionExtractor
    outcome_store: OutcomeStore
    session_store: SessionStore
    audit_log: AuditLog
    warden: Warden
    gate: Gate
    sentinel: Sentinel
    tracer: TracingBackend
    context_builder: ContextBuilder
    intent_registry: IntentRegistry
    llm: LiteLLMClient
    tool_registry: InMemoryToolRegistry
    tool_dispatcher: ToolDispatcher
    playbook_registry: InMemoryPlaybookRegistry = field(default_factory=InMemoryPlaybookRegistry)
    tool_policy: ToolPolicyProtocol | None = None
    checkpoint_store: Any = None  # CheckpointStore protocol (S1.3)
    tool_catalog: Any = None
    skill_catalog: Any = None
    resource_catalog: Any = None
    vault_client: Any = None
    mason_queue: Any = None
    agent_store: InMemoryAgentStore = field(default_factory=lambda: InMemoryAgentStore({}))
    rate_limiter: Any = field(default_factory=InMemoryRateLimiter)  # RateLimiter protocol
    reactor: Reactor = field(default_factory=Reactor)
    task_queue: InMemoryTaskQueue = field(default_factory=InMemoryTaskQueue)
    agents: dict[str, Agent] = field(default_factory=dict)
    coin_ledger: Any = None
    tournament: Any = None
    canary_manager: Any = None
    orchestrator: Any = None  # OrchestratorEngine, set in app.py lifespan
    learning_approval_gate: Any = None
    learning_promoter: Any = None
    strike_tracker: Any = None  # InMemoryStrikeTracker
    db_pool: Any = None  # asyncpg.Pool when using PostgreSQL
    sa_engine: Any = None  # SQLAlchemy async engine (for SQLModel queries)
    redis_client: Any = None  # redis.asyncio.Redis (distributed cache/sessions/rate-limit)
    prompt_cache: Any = None  # RedisPromptCache (write-through cache)
    mcp_registry: Any = None  # MCPRegistry
    schedule_store: InMemoryScheduleStore = field(default_factory=InMemoryScheduleStore)
    mcp_deployer: Any = None  # K8sDeployer
    conduit: Any = None  # Conduit — wired in __post_init__ or create_container

    def __post_init__(self) -> None:
        """Auto-wire Conduit pipeline if not already set."""
        if self.conduit is None:
            from stronghold.conduit import Conduit as ConduitPipeline  # noqa: PLC0415

            self.conduit = ConduitPipeline(self)

    async def route_request(
        self,
        messages: list[dict[str, Any]],
        *,
        auth: Any = None,
        session_id: str | None = None,
        intent_hint: str = "",
        status_callback: Any = None,
    ) -> dict[str, Any]:
        """Delegate to Conduit pipeline. All requests flow through here."""
        result: dict[str, Any] = await self.conduit.route_request(
            messages,
            auth=auth,
            session_id=session_id,
            intent_hint=intent_hint,
            status_callback=status_callback,
        )
        return result


def _wire_auth(
    config: StrongholdConfig,
) -> tuple[StaticKeyAuthProvider, PermissionTable]:
    """Wire auth provider chain: demo cookie → cookie (BFF) → JWT → static key."""
    from stronghold.security.auth_composite import CompositeAuthProvider  # noqa: PLC0415
    from stronghold.security.auth_demo_cookie import DemoCookieAuthProvider  # noqa: PLC0415

    static_auth = StaticKeyAuthProvider(api_key=config.router_api_key)
    demo_cookie_auth = DemoCookieAuthProvider(
        api_key=config.router_api_key,
        cookie_name=config.auth.session_cookie_name,
    )

    if config.auth.jwks_url:
        from stronghold.security.auth_cookie import CookieAuthProvider  # noqa: PLC0415
        from stronghold.security.auth_jwt import JWTAuthProvider  # noqa: PLC0415

        jwt_auth = JWTAuthProvider(
            jwks_url=config.auth.jwks_url,
            issuer=config.auth.issuer,
            audience=config.auth.audience,
        )
        providers: list[StaticKeyAuthProvider] = [demo_cookie_auth, jwt_auth, static_auth]  # type: ignore[list-item]

        if config.auth.client_id and config.auth.token_url:
            cookie_auth = CookieAuthProvider(
                jwt_provider=jwt_auth,
                cookie_name=config.auth.session_cookie_name,
            )
            providers.insert(1, cookie_auth)  # type: ignore[arg-type]
            logger.info(
                "Auth: BFF cookie auth enabled (cookie=%s)",
                config.auth.session_cookie_name,
            )

        auth_provider: StaticKeyAuthProvider = CompositeAuthProvider(providers)  # type: ignore[assignment]
        logger.info(
            "Auth: composite (demo + cookie + JWT + static key) — JWKS: %s",
            config.auth.jwks_url,
        )
    else:
        auth_provider = CompositeAuthProvider([demo_cookie_auth, static_auth])  # type: ignore[assignment]
        logger.info("Auth: composite (demo cookie + static key)")

    permission_table = PermissionTable.from_config(config.permissions)
    return auth_provider, permission_table


async def _wire_persistence(
    config: StrongholdConfig,
) -> tuple[Any, QuotaTracker, PromptManager, LearningStore, OutcomeStore, SessionStore, AuditLog]:
    """Wire persistence layer: PostgreSQL or InMemory."""
    db_pool: Any = None

    if config.database_url:
        from stronghold.persistence import get_pool, run_migrations  # noqa: PLC0415
        from stronghold.persistence.pg_audit import PgAuditLog  # noqa: PLC0415
        from stronghold.persistence.pg_learnings import PgLearningStore  # noqa: PLC0415
        from stronghold.persistence.pg_outcomes import PgOutcomeStore  # noqa: PLC0415
        from stronghold.persistence.pg_prompts import PgPromptManager  # noqa: PLC0415
        from stronghold.persistence.pg_quota import PgQuotaTracker  # noqa: PLC0415
        from stronghold.persistence.pg_sessions import PgSessionStore  # noqa: PLC0415

        db_pool = await get_pool(config.database_url)
        await run_migrations(db_pool)
        logger.info("Persistence: PostgreSQL (%s)", config.database_url.split("@")[-1])
        return (
            db_pool,
            PgQuotaTracker(db_pool),
            PgPromptManager(db_pool),
            PgLearningStore(db_pool),
            PgOutcomeStore(db_pool),
            PgSessionStore(db_pool),
            PgAuditLog(db_pool),
        )

    logger.info("Persistence: InMemory (no DATABASE_URL set)")
    return (
        None,
        InMemoryQuotaTracker(),
        InMemoryPromptManager(),
        InMemoryLearningStore(),
        InMemoryOutcomeStore(),
        InMemorySessionStore(),
        InMemoryAuditLog(),
    )


async def create_container(config: StrongholdConfig) -> Container:
    """Wire all dependencies and create the container."""
    if not config.router_api_key:
        msg = (
            "ROUTER_API_KEY is required. Set it via environment variable or config. "
            "Refusing to start with empty/default API key."
        )
        raise ConfigError(msg)

    if not config.jwt_secret:
        config.jwt_secret = config.router_api_key

    # ── Auth ──
    auth_provider, permission_table = _wire_auth(config)
    learning_extractor = ToolCorrectionExtractor()

    # ── Persistence (PostgreSQL or InMemory) ──
    (
        db_pool,
        quota_tracker,
        prompt_manager,
        learning_store,
        outcome_store,
        session_store,
        audit_log,
    ) = await _wire_persistence(config)

    # ── SQLAlchemy engine (for SQLModel queries) ──
    # NOTE: This creates a second connection pool alongside asyncpg. Both hit the
    # same database. The asyncpg pool serves the legacy pg_* modules; the SQLAlchemy
    # engine serves new SQLModel-based code (PgAgentRegistry). As modules migrate
    # to SQLModel, the asyncpg pool will be removed. Track max_connections accordingly.
    sa_engine = None
    if config.database_url:
        from stronghold.models.engine import get_engine  # noqa: PLC0415

        sa_engine = get_engine(config.database_url)
        logger.info("SQLAlchemy async engine initialized")

    # ── Redis (distributed sessions, rate limiting, cache) ──
    redis_client = None
    if config.redis_url:
        from stronghold.cache import get_redis  # noqa: PLC0415

        try:
            redis_client = await get_redis(config.redis_url)
            masked = (
                config.redis_url.split("@")[-1] if "@" in config.redis_url else config.redis_url
            )
            logger.info("Redis connected: %s", masked)
        except Exception:
            logger.warning("Redis unavailable at %s — falling back to InMemory", config.redis_url)

    # ── Rate limiter (Redis if available + enabled, InMemory otherwise) ──
    rate_limiter: Any
    if redis_client and config.rate_limit.enabled:
        from stronghold.cache.rate_limiter import RedisRateLimiter  # noqa: PLC0415

        rate_limiter = RedisRateLimiter(
            redis=redis_client,
            max_requests=config.rate_limit.requests_per_minute,
            window_seconds=60,
        )
        logger.info("Rate limiter: Redis (distributed)")
    else:
        rate_limiter = InMemoryRateLimiter(config.rate_limit)
        if not config.rate_limit.enabled:
            logger.info("Rate limiter: disabled by config")
        else:
            logger.info("Rate limiter: InMemory (local)")

    # ── Session store override (Redis if available) ──
    if redis_client:
        from stronghold.cache.session_store import RedisSessionStore  # noqa: PLC0415

        session_store = RedisSessionStore(
            redis=redis_client,
            ttl_seconds=config.sessions.ttl_seconds,
            max_messages=config.sessions.max_messages,
        )
        logger.info("Sessions: Redis (distributed, TTL=%ds)", config.sessions.ttl_seconds)

    # ── Prompt/agent cache (Redis if available) ──
    prompt_cache = None
    if redis_client:
        from stronghold.cache.prompt_cache import RedisPromptCache  # noqa: PLC0415

        prompt_cache = RedisPromptCache(redis=redis_client, ttl_seconds=300)
        logger.info("Prompt cache: Redis (TTL=300s)")

    # ── Core services ──
    router = RouterEngine(quota_tracker)
    classifier = ClassifierEngine()
    warden = Warden()
    strike_tracker = InMemoryStrikeTracker()
    gate = Gate(warden=warden, strike_tracker=strike_tracker)
    sentinel = Sentinel(
        warden=warden,
        permission_table=permission_table,
        audit_log=audit_log,
    )
    if config.phoenix_endpoint:
        tracer: TracingBackend = PhoenixTracingBackend(endpoint=config.phoenix_endpoint)
    else:
        tracer: TracingBackend = NoopTracingBackend()
    context_builder = ContextBuilder()
    intent_registry = IntentRegistry()

    # Create tool registry + dispatcher
    tool_registry = InMemoryToolRegistry()
    tool_dispatcher = ToolDispatcher(tool_registry)

    # Agent-oriented playbook registry (peer of tool_registry).
    # Empty at startup; playbooks register themselves from phase D onward.
    playbook_registry = InMemoryPlaybookRegistry()

    # Tool policy (Casbin-based, ADR-K8S-019)
    try:
        tool_policy: ToolPolicyProtocol | None = create_tool_policy()
        logger.info("Tool policy loaded")
    except Exception:
        logger.warning("Tool policy config not found, running without policy enforcement")
        tool_policy = None

    # Catalogs (ADR-K8S-021/022/023)
    from stronghold.resources.catalog import ResourceCatalog  # noqa: PLC0415
    from stronghold.skills.catalog import SkillCatalog  # noqa: PLC0415
    from stronghold.tools.catalog import ToolCatalog  # noqa: PLC0415

    tool_catalog = ToolCatalog()
    skill_catalog = SkillCatalog()
    resource_catalog = ResourceCatalog()

    # Register all Mason tools
    from stronghold.tools.file_ops import FILE_OPS_TOOL_DEF, FileOpsExecutor  # noqa: PLC0415
    from stronghold.tools.github import GITHUB_TOOL_DEF, GitHubToolExecutor  # noqa: PLC0415
    from stronghold.tools.shell_exec import (  # noqa: PLC0415
        RUN_BANDIT_DEF,
        RUN_MYPY_DEF,
        RUN_PYTEST_DEF,
        RUN_RUFF_CHECK_DEF,
        RUN_RUFF_FORMAT_DEF,
        SHELL_TOOL_DEF,
        QualityGateExecutor,
        ShellExecutor,
    )
    from stronghold.tools.workspace import WORKSPACE_TOOL_DEF, WorkspaceManager  # noqa: PLC0415

    github_tool = GitHubToolExecutor()
    tool_registry.register(GITHUB_TOOL_DEF, github_tool.execute)

    file_ops = FileOpsExecutor()
    tool_registry.register(FILE_OPS_TOOL_DEF, file_ops.execute)

    shell = ShellExecutor()
    tool_registry.register(SHELL_TOOL_DEF, shell.execute)

    workspace = WorkspaceManager()
    tool_registry.register(WORKSPACE_TOOL_DEF, workspace.execute)

    # Quality gate convenience tools
    qg = QualityGateExecutor(shell)
    tool_registry.register(RUN_PYTEST_DEF, qg.make_executor("pytest {path} -v"))
    tool_registry.register(RUN_RUFF_CHECK_DEF, qg.make_executor("ruff check src/stronghold/"))
    tool_registry.register(
        RUN_RUFF_FORMAT_DEF,
        qg.make_executor("ruff format --check src/stronghold/"),
    )
    tool_registry.register(RUN_MYPY_DEF, qg.make_executor("mypy src/stronghold/ --strict"))
    tool_registry.register(RUN_BANDIT_DEF, qg.make_executor("bandit -r src/stronghold/ -ll"))

    # Create the LLM client — the ONLY connection to LiteLLM
    llm = LiteLLMClient(
        base_url=config.litellm_url,
        api_key=config.litellm_key,
    )

    # ── Load agents from GitAgent directory (seed data) ──
    # In production with PostgreSQL, agents persist in the database.
    # This seeds from the filesystem on first boot or when using InMemory stores.
    from pathlib import Path  # noqa: PLC0415

    from stronghold.agents.strategies.tool_http import HTTPToolExecutor  # noqa: PLC0415
    from stronghold.quota.coins import NoOpCoinLedger, PgCoinLedger  # noqa: PLC0415

    if config.agents_dir:
        agents_dir = Path(config.agents_dir)
    else:
        # Try source layout first, then /app/ (Docker), then relative
        candidates = [
            Path(__file__).resolve().parents[2] / "agents",
            Path("/app/agents"),
            Path("agents"),
        ]
        agents_dir = next((p for p in candidates if p.is_dir()), candidates[0])
    # Tool executor: use registered tools first, fall back to HTTP MCP
    dev_tools = HTTPToolExecutor(base_url="http://dev-tools-mcp:8300")

    async def _tool_exec(name: str, args: dict, *, auth: Any = None) -> str:  # type: ignore[type-arg]
        # Policy gate (ADR-K8S-019): check before any execution
        if tool_policy is not None and auth is not None:
            user_id = getattr(auth, "user_id", "")
            org_id = getattr(auth, "org_id", "")
            if not tool_policy.check_tool_call(user_id, org_id, name):
                raise PermissionError(f"Tool call denied by policy: {name}")

        # Try registered native tools first
        if name in tool_registry:
            return await tool_dispatcher.execute(name, args)
        # Fall back to HTTP MCP server
        return await dev_tools.call(name, args)

    coin_ledger = PgCoinLedger(db_pool, config) if db_pool else NoOpCoinLedger()

    agents = await create_agents(
        agents_dir=agents_dir,
        prompt_manager=prompt_manager,
        llm=llm,
        context_builder=context_builder,
        warden=warden,
        sentinel=sentinel,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        outcome_store=outcome_store,
        session_store=session_store,
        quota_tracker=quota_tracker,
        coin_ledger=coin_ledger,
        tracer=tracer,
        tool_executor=_tool_exec,
        sa_engine=sa_engine,
    )

    reactor = Reactor()

    # Tournament system
    from stronghold.agents.tournament import Tournament  # noqa: PLC0415

    tournament = Tournament()

    # Canary deployment manager
    from stronghold.skills.canary import CanaryManager  # noqa: PLC0415

    canary_manager = CanaryManager()

    # Learning approval gate
    from stronghold.memory.learnings.approval import LearningApprovalGate  # noqa: PLC0415

    approval_gate = LearningApprovalGate()

    # Learning promoter (with approval gate)
    from stronghold.memory.learnings.promoter import LearningPromoter  # noqa: PLC0415

    learning_promoter = LearningPromoter(
        learning_store,
        threshold=5,
        approval_gate=approval_gate,
    )

    # MCP server registry + K8s deployer
    from stronghold.mcp.registry import MCPRegistry  # noqa: PLC0415

    mcp_registry = MCPRegistry()
    mcp_deployer = None
    try:
        from stronghold.mcp.deployer import K8sDeployer  # noqa: PLC0415

        mcp_deployer = K8sDeployer()
        logger.info("MCP: K8s deployer available")
    except Exception:
        logger.info("MCP: K8s deployer unavailable (no cluster access)")

    container = Container(
        config=config,
        auth_provider=auth_provider,
        permission_table=permission_table,
        router=router,
        classifier=classifier,
        quota_tracker=quota_tracker,
        prompt_manager=prompt_manager,
        learning_store=learning_store,
        learning_extractor=learning_extractor,
        outcome_store=outcome_store,
        session_store=session_store,
        audit_log=audit_log,
        warden=warden,
        gate=gate,
        sentinel=sentinel,
        tracer=tracer,
        context_builder=context_builder,
        intent_registry=intent_registry,
        llm=llm,
        tool_registry=tool_registry,
        tool_dispatcher=tool_dispatcher,
        playbook_registry=playbook_registry,
        tool_policy=tool_policy,
        tool_catalog=tool_catalog,
        skill_catalog=skill_catalog,
        resource_catalog=resource_catalog,
        agent_store=InMemoryAgentStore(agents, prompt_manager),
        rate_limiter=rate_limiter,
        reactor=reactor,
        agents=agents,
        coin_ledger=coin_ledger,
        tournament=tournament,
        canary_manager=canary_manager,
        learning_approval_gate=approval_gate,
        learning_promoter=learning_promoter,
        strike_tracker=strike_tracker,
        db_pool=db_pool,
        sa_engine=sa_engine,
        redis_client=redis_client,
        prompt_cache=prompt_cache,
        mcp_registry=mcp_registry,
        mcp_deployer=mcp_deployer,
    )

    # Conduit pipeline is auto-wired via __post_init__

    # Register reactor triggers (after container is built)
    from stronghold.triggers import register_core_triggers  # noqa: PLC0415

    register_core_triggers(container)

    return container
