"""FastAPI app factory."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse

from stronghold.config.loader import load_config
from stronghold.container import create_container

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup: load config, create container, start reactor."""
    import asyncio

    from stronghold.log_config import configure_logging  # noqa: PLC0415

    configure_logging()
    config = load_config()
    container = await create_container(config)
    app.state.container = container

    # Wire Mason queue + router
    from stronghold.agents.mason_queue import MasonQueue  # noqa: PLC0415
    from stronghold.api.routes.mason import configure_mason_router  # noqa: PLC0415

    mason_queue = MasonQueue()
    container.mason_queue = mason_queue
    configure_mason_router(
        queue=mason_queue,
        reactor=container.reactor,
        container=container,
    )

    # Start the Orchestrator engine (agent execution)
    from stronghold.orchestrator.engine import OrchestratorEngine  # noqa: PLC0415

    max_concurrent = int(os.environ.get("STRONGHOLD_MAX_CONCURRENCY", "3"))
    orchestrator = OrchestratorEngine(container, max_concurrent=max_concurrent)
    app.state.orchestrator = orchestrator
    container.orchestrator = orchestrator  # expose to triggers + pipeline

    # Start the reactor loop (1000Hz, runs in background)
    disable_reactor = os.environ.get("STRONGHOLD_DISABLE_REACTOR_AUTOSTART") == "1"
    running_under_pytest = "PYTEST_CURRENT_TEST" in os.environ
    reactor_task: asyncio.Task[None] | None = None
    orchestrator_started = False
    if not disable_reactor and not running_under_pytest:
        reactor_task = asyncio.create_task(container.reactor.start())
        await orchestrator.start()
        orchestrator_started = True
    yield
    if orchestrator_started:
        await orchestrator.stop()
    container.reactor.stop()
    if reactor_task is not None:
        reactor_task.cancel()
    # Close PostgreSQL asyncpg pool
    if container.db_pool is not None:
        from stronghold.persistence import close_pool  # noqa: PLC0415

        await close_pool()
    # Close SQLAlchemy engine
    if container.sa_engine is not None:
        from stronghold.models.engine import close_engine  # noqa: PLC0415

        await close_engine()
    # Close Redis pool
    if container.redis_client is not None:
        from stronghold.cache import close_redis  # noqa: PLC0415

        await close_redis()


def create_app() -> FastAPI:
    """Create the FastAPI application."""
    from stronghold.api.middleware import PayloadSizeLimitMiddleware
    from stronghold.config.loader import load_config as _load_config_for_middleware

    running_under_pytest = "PYTEST_CURRENT_TEST" in os.environ
    app = FastAPI(
        title="Stronghold",
        version="0.1.0",
        description="Secure Agent Governance Platform",
        lifespan=None if running_under_pytest else lifespan,
    )

    if running_under_pytest:

        @app.middleware("http")
        async def _ensure_test_container(
            request: Request,
            call_next: Callable[[Request], Awaitable[Response]],
        ) -> Response:
            if not hasattr(request.app.state, "container"):
                request.app.state.container = await create_container(load_config())
            return await call_next(request)

    # Middleware (order matters: outermost runs first)
    # Load config early for middleware setup (container loads full config in lifespan)
    _mw_config = _load_config_for_middleware()

    # CORS — required for OpenWebUI and dashboard cross-origin requests.
    # Use explicit cors_origins list (top-level config) if set; otherwise fall back
    # to the detailed CORSConfig.  Only add the middleware when at least one origin
    # is configured to avoid overly-permissive defaults.
    _cors_origins = _mw_config.cors_origins or _mw_config.cors.allowed_origins
    if _cors_origins:
        from starlette.middleware.cors import CORSMiddleware  # noqa: PLC0415

        app.add_middleware(
            CORSMiddleware,
            allow_origins=_cors_origins,
            allow_methods=_mw_config.cors.allowed_methods,
            allow_headers=_mw_config.cors.allowed_headers,
            allow_credentials=_mw_config.cors.allow_credentials,
        )

    # Demo cookie → Authorization injection middleware
    # Reads the session cookie and, if it contains a valid HS256 demo JWT,
    # injects a synthetic Authorization header so all route handlers authenticate
    # without needing to pass headers explicitly. Runs before route handlers.
    from stronghold.api.middleware.demo_cookie import DemoCookieMiddleware  # noqa: PLC0415

    app.add_middleware(DemoCookieMiddleware)

    # Payload size limit — reject oversized requests before parsing
    app.add_middleware(
        PayloadSizeLimitMiddleware,
        max_bytes=_mw_config.max_request_body_bytes,
    )

    # Rate limiting — per-user sliding window (runs after auth in request flow)
    if _mw_config.rate_limit.enabled:
        from stronghold.api.middleware.rate_limit import RateLimitMiddleware  # noqa: PLC0415
        from stronghold.security.rate_limiter import InMemoryRateLimiter  # noqa: PLC0415

        _rate_limiter = InMemoryRateLimiter(_mw_config.rate_limit)
        app.add_middleware(RateLimitMiddleware, rate_limiter=_rate_limiter)

    # Import and mount routes
    from stronghold.api.routes.admin import router as admin_router
    from stronghold.api.routes.agents import router as agents_router
    from stronghold.api.routes.agents_stream import router as agents_stream_router
    from stronghold.api.routes.auth import router as auth_router
    from stronghold.api.routes.chat import router as chat_router
    from stronghold.api.routes.dashboard import router as dashboard_router
    from stronghold.api.routes.gate_endpoint import router as gate_router
    from stronghold.api.routes.marketplace import router as marketplace_router
    from stronghold.api.routes.mason import router as mason_router
    from stronghold.api.routes.mcp import router as mcp_router
    from stronghold.api.routes.models import router as models_router
    from stronghold.api.routes.profile import router as profile_router
    from stronghold.api.routes.schedules import router as schedules_router
    from stronghold.api.routes.sessions import router as sessions_router
    from stronghold.api.routes.skills import router as skills_router
    from stronghold.api.routes.status import router as status_router
    from stronghold.api.routes.tasks import router as tasks_router
    from stronghold.api.routes.traces import router as traces_router
    from stronghold.api.routes.webhooks import router as webhooks_router
    from stronghold.orchestrator.routes import router as orchestrator_router
    from stronghold.prompts.routes import router as prompts_router

    app.include_router(auth_router)  # BFF auth (must be before dashboard for /auth/* routes)
    app.include_router(chat_router)
    app.include_router(models_router)
    app.include_router(status_router)
    app.include_router(agents_router)
    app.include_router(prompts_router)
    app.include_router(gate_router)
    app.include_router(tasks_router)
    app.include_router(agents_stream_router)
    app.include_router(skills_router)
    app.include_router(sessions_router)
    app.include_router(admin_router)
    app.include_router(profile_router)
    app.include_router(marketplace_router)
    app.include_router(traces_router)
    app.include_router(dashboard_router)
    app.include_router(webhooks_router)
    app.include_router(mcp_router)
    app.include_router(schedules_router)
    app.include_router(mason_router)
    app.include_router(orchestrator_router)

    # Dashboard — try multiple paths (installed package vs source layout)
    _dashboard_candidates = [
        Path(__file__).parent.parent / "dashboard" / "index.html",
        Path("/app/src/stronghold/dashboard/index.html"),
        Path("src/stronghold/dashboard/index.html"),
    ]

    def _find_dashboard_file(filename: str) -> str:
        """Find a dashboard file across multiple paths."""
        candidates = [
            Path(__file__).parent.parent / "dashboard" / filename,
            Path(f"/app/src/stronghold/dashboard/{filename}"),
            Path(f"src/stronghold/dashboard/{filename}"),
        ]
        for candidate in candidates:
            if candidate.exists():
                return candidate.read_text()
        return f"<h1>Stronghold</h1><p>{filename} not found.</p>"

    @app.get("/", response_class=HTMLResponse)
    async def root_login() -> str:
        """Root is the login page — always."""
        return _find_dashboard_file("login.html")

    @app.get("/greathall", response_class=HTMLResponse)
    async def dashboard() -> str:
        """Serve the main Stronghold dashboard (auth required)."""
        return _find_dashboard_file("index.html")

    @app.get("/prompts", response_class=HTMLResponse)
    async def prompts_ui() -> str:
        """Serve the prompt management UI."""
        return _find_dashboard_file("prompts.html")

    return app
