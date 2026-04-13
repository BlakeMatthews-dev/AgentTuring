"""Security vulnerability fix tests for API routes.

Covers:
- C1:  Mason endpoints must require authentication
- C2:  Webhook must reject unsigned payloads when GITHUB_WEBHOOK_SECRET is unset
- C16: Marketplace _require_auth must run CSRF check (not dead code)
- H3:  Dashboard 404 must HTML-escape the filename
- H4:  SSE stream must not leak raw exception details to clients
- H5:  Agent list_agents must apply org filter even when _agents is empty

Uses real classes from tests/fakes.py per project rules.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.agents import router as agents_router
from stronghold.api.routes.agents_stream import router as stream_router
from stronghold.api.routes.dashboard import _serve_page
from stronghold.api.routes.marketplace import router as marketplace_router
from stronghold.api.routes.mason import (
    _issues_cache,
    configure_mason_router,
)
from stronghold.api.routes.mason import (
    router as mason_router,
)
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
from stronghold.types.auth import AuthContext, PermissionTable
from stronghold.types.config import StrongholdConfig, TaskTypeConfig
from tests.fakes import FakeAuthProvider, FakeLLMClient

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


def _make_config() -> StrongholdConfig:
    return StrongholdConfig(
        providers={
            "test": {"status": "active", "billing_cycle": "monthly", "free_tokens": 1_000_000},
        },
        models={
            "test-model": {
                "provider": "test",
                "litellm_id": "test/model",
                "tier": "medium",
                "quality": 0.7,
                "speed": 500,
                "strengths": ["code", "chat"],
            },
        },
        task_types={
            "chat": TaskTypeConfig(keywords=["hello"], preferred_strengths=["chat"]),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )


def _make_container(fake_llm: FakeLLMClient | None = None) -> Container:
    llm = fake_llm or FakeLLMClient()
    llm.set_simple_response("test response")
    config = _make_config()
    prompts = InMemoryPromptManager()
    learning_store = InMemoryLearningStore()
    warden = Warden()
    audit_log = InMemoryAuditLog()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")
        agent = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
                memory_config={"learnings": True},
            ),
            strategy=DirectStrategy(),
            llm=llm,
            context_builder=ContextBuilder(),
            prompt_manager=prompts,
            warden=warden,
            learning_store=learning_store,
        )
        agents_dict: dict[str, Agent] = {"arbiter": agent}
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
            agent_store=InMemoryAgentStore(agents_dict, prompts),
            agents=agents_dict,
        )

    return asyncio.get_event_loop().run_until_complete(setup())


# ---------------------------------------------------------------------------
# Fake queue / reactor for Mason tests (same pattern as test_mason_routes.py)
# ---------------------------------------------------------------------------


class _FakeIssue:
    def __init__(self, issue_number: int, title: str = "", owner: str = "", repo: str = "") -> None:
        self.issue_number = issue_number
        self.title = title
        self.owner = owner
        self.repo = repo


class _FakeQueue:
    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []

    def assign(
        self, *, issue_number: int, title: str = "", owner: str = "", repo: str = ""
    ) -> _FakeIssue:
        self.issues.append({"number": issue_number, "status": "queued"})
        return _FakeIssue(issue_number, title, owner, repo)

    def list_all(self) -> list[dict[str, Any]]:
        return self.issues

    def status(self) -> dict[str, Any]:
        return {"running": 0, "queued": len(self.issues)}

    def start(self, issue_number: int) -> None:
        pass

    def complete(self, issue_number: int) -> None:
        pass

    def fail(self, issue_number: int, error: str = "") -> None:
        pass

    def add_log(self, issue_number: int, msg: str) -> None:
        pass


class _FakeReactor:
    def __init__(self) -> None:
        self.emitted: list[Any] = []

    def emit(self, event: Any) -> None:
        self.emitted.append(event)


# ===================================================================
# C1: Mason endpoints must require authentication
# ===================================================================


class TestC1MasonAuthRequired:
    """All 7 Mason management endpoints must return 401 without valid auth."""

    @pytest.fixture(autouse=True)
    def _reset_cache(self) -> None:
        _issues_cache.clear()
        _issues_cache.update({"data": None, "fetched_at": 0.0})

    @pytest.fixture
    def mason_app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(mason_router)
        container = _make_container()
        app.state.container = container
        q, r = _FakeQueue(), _FakeReactor()
        configure_mason_router(queue=q, reactor=r, container=container)
        return app

    def test_assign_requires_auth(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.post(
                "/v1/stronghold/mason/assign",
                json={"issue_number": 1, "owner": "o", "repo": "r"},
            )
        assert resp.status_code == 401

    def test_review_pr_requires_auth(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.post(
                "/v1/stronghold/mason/review-pr",
                json={"pr_number": 1, "owner": "o", "repo": "r"},
            )
        assert resp.status_code == 401

    def test_get_queue_requires_auth(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.get("/v1/stronghold/mason/queue")
        assert resp.status_code == 401

    def test_get_status_requires_auth(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.get("/v1/stronghold/mason/status")
        assert resp.status_code == 401

    def test_list_issues_requires_auth(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.get("/v1/stronghold/mason/issues?owner=o&repo=r")
        assert resp.status_code == 401

    def test_scan_requires_auth(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.get("/v1/stronghold/mason/scan")
        assert resp.status_code == 401

    def test_scan_create_requires_auth(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.post(
                "/v1/stronghold/mason/scan/create",
                json={"all": True, "owner": "o", "repo": "r"},
            )
        assert resp.status_code == 401

    def test_assign_succeeds_with_auth(self, mason_app: FastAPI) -> None:
        """Verify auth is not rejecting valid requests."""
        with TestClient(mason_app) as client:
            resp = client.post(
                "/v1/stronghold/mason/assign",
                json={"issue_number": 1, "owner": "o", "repo": "r"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 200


# ===================================================================
# C2: Webhook must reject when GITHUB_WEBHOOK_SECRET is unset
# ===================================================================


class TestC2WebhookRejectsUnsigned:
    """When GITHUB_WEBHOOK_SECRET is unset, webhook must return 403."""

    @pytest.fixture(autouse=True)
    def _clear_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)

    @pytest.fixture
    def mason_app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(mason_router)
        container = _make_container()
        app.state.container = container
        q, r = _FakeQueue(), _FakeReactor()
        configure_mason_router(queue=q, reactor=r, container=container)
        return app

    def test_webhook_returns_403_when_secret_unset(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.post(
                "/v1/stronghold/webhooks/github",
                headers={"X-GitHub-Event": "ping"},
                json={"action": "ping"},
            )
        assert resp.status_code == 403

    def test_webhook_error_message_is_clear(self, mason_app: FastAPI) -> None:
        with TestClient(mason_app) as client:
            resp = client.post(
                "/v1/stronghold/webhooks/github",
                headers={"X-GitHub-Event": "ping"},
                json={"action": "ping"},
            )
        body = resp.json()
        assert (
            "secret" in body.get("error", "").lower()
            or "configured" in body.get("error", "").lower()
        )


# ===================================================================
# C16: Marketplace CSRF check must not be dead code
# ===================================================================


class TestC16MarketplaceCsrfReachable:
    """CSRF check in marketplace _require_auth must execute after auth succeeds.

    The bug: `return` on line 104 exits before _check_csrf runs on line 109.
    After the fix, _check_csrf must be reachable.
    """

    def test_csrf_call_is_reachable(self) -> None:
        """Verify _check_csrf is called in _require_auth (not dead code)."""
        import ast
        import inspect
        import textwrap

        from stronghold.api.routes.marketplace import _require_auth

        source = inspect.getsource(_require_auth)
        source = textwrap.dedent(source)
        tree = ast.parse(source)

        func_def = tree.body[0]
        assert isinstance(func_def, ast.AsyncFunctionDef)

        # Walk top-level statements and check that _check_csrf is NOT
        # preceded by an unconditional return/raise.
        found_csrf_call = False
        for stmt in ast.walk(func_def):
            if isinstance(stmt, ast.Call):
                func = stmt.func
                if isinstance(func, ast.Name) and func.id == "_check_csrf":
                    found_csrf_call = True
        assert found_csrf_call, "_check_csrf is not called in _require_auth at all"

        # Verify it's not dead code: _check_csrf must not be inside a
        # try/except block after a return.  The simple check: the
        # _check_csrf call must appear as a top-level statement in the
        # function body (not nested inside the try block after return).
        top_level_csrf = False
        for stmt in func_def.body:
            if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                func = stmt.value.func
                if isinstance(func, ast.Name) and func.id == "_check_csrf":
                    top_level_csrf = True
        assert top_level_csrf, "_check_csrf is inside a try block after return -- it is dead code"

    @pytest.fixture
    def marketplace_app_with_cookie_auth(self) -> FastAPI:
        """App where auth succeeds even without Authorization header (cookie auth)."""
        app = FastAPI()
        app.include_router(marketplace_router)
        container = _make_container()

        class CookieAuthProvider:
            """Auth provider that accepts cookie-based auth."""

            async def authenticate(
                self,
                authorization: str | None,
                headers: dict[str, str] | None = None,
            ) -> AuthContext:
                # Accept either bearer or cookie
                if authorization:
                    return AuthContext(
                        user_id="bearer-user",
                        roles=frozenset({"admin"}),
                        auth_method="api_key",
                    )
                return AuthContext(
                    user_id="cookie-user",
                    roles=frozenset({"admin"}),
                    auth_method="cookie",
                )

        container.auth_provider = CookieAuthProvider()
        app.state.container = container
        return app

    def test_csrf_blocks_cookie_mutation_without_header(
        self,
        marketplace_app_with_cookie_auth: FastAPI,
    ) -> None:
        """POST with cookie auth but no X-Stronghold-Request header must be blocked."""
        with TestClient(
            marketplace_app_with_cookie_auth, cookies={"sh_session": "valid"}
        ) as client:
            resp = client.post(
                "/v1/stronghold/marketplace/fix",
                json={
                    "url": "https://example.com/test.md",
                    "type": "skill",
                    "content": "test",
                },
                # No Authorization header -> cookie auth
                # No X-Stronghold-Request header -> CSRF should block
            )
        assert resp.status_code == 403
        assert "csrf" in resp.json().get("detail", "").lower()


# ===================================================================
# H3: Dashboard 404 must HTML-escape the filename
# ===================================================================


class TestH3DashboardXss:
    """_serve_page must escape filenames in the 404 HTML response."""

    def test_filename_with_script_tag_is_escaped(self) -> None:
        """XSS payload in filename must be HTML-escaped in the 404 response."""
        resp = _serve_page('<script>alert("xss")</script>.html')
        assert resp.status_code == 404
        body = resp.body.decode()
        # The raw script tag must NOT appear in the response
        assert "<script>" not in body
        # The escaped version should appear
        assert "&lt;script&gt;" in body

    def test_filename_with_angle_brackets_is_escaped(self) -> None:
        resp = _serve_page("<img src=x onerror=alert(1)>.html")
        assert resp.status_code == 404
        body = resp.body.decode()
        assert "<img " not in body

    def test_normal_filename_still_works(self) -> None:
        """Normal filenames should appear (escaped, but no change for safe strings)."""
        resp = _serve_page("nonexistent_page.html")
        assert resp.status_code == 404
        body = resp.body.decode()
        assert "nonexistent_page.html" in body


# ===================================================================
# H4: SSE stream must not leak raw exception details
# ===================================================================


class TestH4SseExceptionSanitization:
    """Raw exceptions must not be sent to clients via SSE error events."""

    @pytest.fixture
    def stream_app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(stream_router)
        fake_llm = FakeLLMClient()
        fake_llm.set_simple_response("test")
        container = _make_container(fake_llm)
        app.state.container = container
        return app

    def test_internal_error_returns_generic_message(self, stream_app: FastAPI) -> None:
        """When route_request raises, client gets a generic error, not the traceback."""

        # Patch route_request to raise an internal error with sensitive info
        async def exploding_route(*a: Any, **kw: Any) -> Any:
            msg = "ConnectionError: password=s3cret host=db.internal.corp:5432"
            raise RuntimeError(msg)

        stream_app.state.container.route_request = exploding_route

        with TestClient(stream_app) as client:
            resp = client.post(
                "/v1/stronghold/request/stream",
                json={"goal": "hello there"},
                headers=AUTH_HEADER,
            )
        body = resp.text
        # Parse SSE events
        events = []
        for line in body.strip().split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                events.append(json.loads(payload))

        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) >= 1

        error_msg = error_events[0]["message"]
        # Must NOT contain the sensitive connection string
        assert "s3cret" not in error_msg
        assert "db.internal.corp" not in error_msg
        # Should contain a generic message
        assert "internal" in error_msg.lower() or "error" in error_msg.lower()


# ===================================================================
# H5: Agent list_agents must apply org filter when _agents is empty
# ===================================================================


class TestH5AgentOrgFilterBypass:
    """list_agents must not access private _agents to decide code path.

    The fix: always delegate to agent_store.list_all() when the store exists,
    rather than branching on the truthiness of a private dict.
    """

    @pytest.fixture
    def agents_app(self) -> FastAPI:
        app = FastAPI()
        app.include_router(agents_router)
        container = _make_container()
        # Set auth to a non-admin user in org "org-A"
        container.auth_provider = FakeAuthProvider(
            auth_context=AuthContext(
                user_id="user-a",
                username="user-a",
                roles=frozenset({"viewer"}),
                auth_method="api_key",
                org_id="org-A",
            )
        )
        app.state.container = container
        return app

    def test_list_agents_does_not_access_private_agents(self, agents_app: FastAPI) -> None:
        """The route must not use agent_store._agents (private attribute)."""
        import ast
        import inspect

        from stronghold.api.routes.agents import list_agents

        source = inspect.getsource(list_agents)
        tree = ast.parse(source)

        private_access = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "_agents":
                private_access = True
                break
        assert not private_access, (
            "list_agents accesses private _agents; use agent_store.list_all() instead"
        )
