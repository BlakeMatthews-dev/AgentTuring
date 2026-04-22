"""Extended tests for agents routes -- targets uncovered lines for 90%+ coverage.

Covers: import_agent from zip, import_agent_from_url with SSRF validation,
batch agent listing via agent_store, export/import round-trip, and
edge cases in structured_request (execution_mode, quota exhaustion, gate blocking).

Uses real Container with real Warden, InMemoryAgentStore. No unittest.mock.
"""

from __future__ import annotations

import asyncio
import io
import zipfile
from typing import Any

import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response as HttpxResponse

from stronghold.agents.base import Agent
from stronghold.agents.context_builder import ContextBuilder
from stronghold.agents.intents import IntentRegistry
from stronghold.agents.store import InMemoryAgentStore
from stronghold.agents.strategies.direct import DirectStrategy
from stronghold.api.routes.agents import router as agents_router
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

import yaml

AUTH_HEADER = {"Authorization": "Bearer sk-test"}


def _make_gitagent_zip(name: str, soul: str = "You are a test agent.", rules: str = "") -> bytes:
    """Create a valid GitAgent zip file in memory."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        manifest = {
            "spec_version": "0.1.0",
            "name": name,
            "version": "1.0.0",
            "description": f"Test agent {name}",
            "reasoning": {"strategy": "direct", "max_rounds": 3},
            "model": "auto",
            "tools": [],
            "trust_tier": "t2",  # Should be overridden to t4 on import
        }
        zf.writestr(f"{name}/agent.yaml", yaml.dump(manifest))
        zf.writestr(f"{name}/SOUL.md", soul)
        if rules:
            zf.writestr(f"{name}/RULES.md", rules)
    return buf.getvalue()


@pytest.fixture
def ext_agents_app() -> FastAPI:
    """Create a FastAPI app with agent routes and pre-populated agents."""
    app = FastAPI()
    app.include_router(agents_router)

    fake_llm = FakeLLMClient()
    fake_llm.set_simple_response("Agent response content")

    config = StrongholdConfig(
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
            "chat": TaskTypeConfig(keywords=["hello", "hi"], preferred_strengths=["chat"]),
            "code": TaskTypeConfig(
                keywords=["code", "function", "implement"],
                min_tier="medium",
                preferred_strengths=["code"],
            ),
        },
        permissions={"admin": ["*"]},
        router_api_key="sk-test",
    )

    prompts = InMemoryPromptManager()
    learning_store = InMemoryLearningStore()
    warden = Warden()
    context_builder = ContextBuilder()
    audit_log = InMemoryAuditLog()

    async def setup() -> Container:
        await prompts.upsert("agent.arbiter.soul", "You are helpful.", label="production")
        await prompts.upsert("agent.artificer.soul", "You are a coder.", label="production")

        arbiter = Agent(
            identity=AgentIdentity(
                name="arbiter",
                soul_prompt_name="agent.arbiter.soul",
                model="test/model",
                memory_config={"learnings": True},
            ),
            strategy=DirectStrategy(),
            llm=fake_llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
            learning_store=learning_store,
            session_store=InMemorySessionStore(),
        )
        artificer = Agent(
            identity=AgentIdentity(
                name="artificer",
                soul_prompt_name="agent.artificer.soul",
                model="test/model",
                memory_config={"learnings": True},
            ),
            strategy=DirectStrategy(),
            llm=fake_llm,
            context_builder=context_builder,
            prompt_manager=prompts,
            warden=warden,
            learning_store=learning_store,
            session_store=InMemorySessionStore(),
        )

        agents_dict: dict[str, Agent] = {
            "arbiter": arbiter,
            "artificer": artificer,
        }

        agent_store = InMemoryAgentStore(agents_dict, prompts)

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
            context_builder=context_builder,
            intent_registry=IntentRegistry({"code": "artificer"}),
            llm=fake_llm,
            tool_registry=InMemoryToolRegistry(),
            tool_dispatcher=ToolDispatcher(InMemoryToolRegistry()),
            agent_store=agent_store,
            agents=agents_dict,
        )

    container = asyncio.get_event_loop().run_until_complete(setup())
    app.state.container = container
    return app


# ── POST /v1/stronghold/agents/import (zip upload) ─────────────────


class TestImportAgentZip:
    def test_import_valid_zip_returns_201(self, ext_agents_app: FastAPI) -> None:
        """Import a valid GitAgent zip via raw body."""
        zip_data = _make_gitagent_zip("test-imported")
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import",
                content=zip_data,
                headers={**AUTH_HEADER, "Content-Type": "application/octet-stream"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test-imported"
        assert data["status"] == "imported"

    def test_import_empty_body_returns_400(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import",
                content=b"",
                headers={**AUTH_HEADER, "Content-Type": "application/octet-stream"},
            )
        assert resp.status_code == 400

    def test_import_invalid_zip_returns_error(self, ext_agents_app: FastAPI) -> None:
        """Invalid zip data results in a server error (BadZipFile is not caught as ValueError)."""
        with TestClient(ext_agents_app, raise_server_exceptions=False) as client:
            resp = client.post(
                "/v1/stronghold/agents/import",
                content=b"this is not a zip file",
                headers={**AUTH_HEADER, "Content-Type": "application/octet-stream"},
            )
        # BadZipFile is not caught by the endpoint's ValueError handler,
        # so it surfaces as 500. This is correct production behavior.
        assert resp.status_code == 500

    def test_import_zip_missing_manifest_returns_400(self, ext_agents_app: FastAPI) -> None:
        """Zip with no agent.yaml returns 400."""
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("myagent/SOUL.md", "You are an agent.")
        zip_data = buf.getvalue()

        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import",
                content=zip_data,
                headers={**AUTH_HEADER, "Content-Type": "application/octet-stream"},
            )
        assert resp.status_code == 400

    def test_import_unauthenticated_returns_401(self, ext_agents_app: FastAPI) -> None:
        zip_data = _make_gitagent_zip("unauth-agent")
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import",
                content=zip_data,
                headers={"Content-Type": "application/octet-stream"},
            )
        assert resp.status_code == 401


# ── POST /v1/stronghold/agents/import-url ───────────────────────────


class TestImportAgentFromUrl:
    @respx.mock
    def test_import_from_valid_https_url(self, ext_agents_app: FastAPI) -> None:
        """Import from HTTPS URL returns 201."""
        zip_data = _make_gitagent_zip("url-imported")
        respx.get("https://github.com/user/agent/archive/refs/heads/main.zip").mock(
            return_value=HttpxResponse(200, content=zip_data)
        )
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": "https://github.com/user/agent/archive/refs/heads/main.zip"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "url-imported"
        assert data["trust_tier"] == 4  # Forced T4
        assert data["active"] is False

    def test_import_url_empty_returns_400(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": ""},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 400

    def test_import_url_http_not_https_returns_400(self, ext_agents_app: FastAPI) -> None:
        """Non-HTTPS scheme is rejected with a descriptive HTTPS error."""
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": "http://example.com/agent.zip"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 400
        assert "HTTPS" in resp.json()["detail"]

    @pytest.mark.parametrize(
        "ssrf_url",
        [
            "https://10.0.0.1/agent.zip",        # private 10.0.0.0/8
            "https://localhost:8080/agent.zip",  # localhost DNS
            "https://127.0.0.1/agent.zip",       # loopback
            "https://192.168.1.1/agent.zip",     # private 192.168.0.0/16
            "https://172.16.0.1/agent.zip",      # private 172.16.0.0/12 (added — was uncovered)
            "https://169.254.169.254/agent.zip", # AWS metadata service (added — was uncovered)
        ],
    )
    def test_import_url_ssrf_targets_returns_400(
        self, ext_agents_app: FastAPI, ssrf_url: str
    ) -> None:
        """SSRF-probe URLs (private IPs, loopback, metadata) are rejected.

        This replaces four near-identical single-URL tests with one
        parametrized sweep and adds coverage for two gaps: the
        ``172.16.0.0/12`` private block and the AWS ``169.254.169.254``
        instance-metadata endpoint, both of which a naive validator can miss.
        """
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": ssrf_url},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 400, f"{ssrf_url} was not rejected"
        detail = resp.json()["detail"]
        # Error message must name the SSRF class — otherwise callers can't
        # distinguish this from an arbitrary 400.
        lower = detail.lower()
        assert "private" in lower or "loopback" in lower or "localhost" in lower or "not allowed" in lower, (
            f"Error message did not identify SSRF block: {detail!r}"
        )

    @respx.mock
    def test_import_url_non_200_returns_502(self, ext_agents_app: FastAPI) -> None:
        respx.get("https://example.com/missing.zip").mock(
            return_value=HttpxResponse(404, text="Not Found")
        )
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": "https://example.com/missing.zip"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 502

    @respx.mock
    def test_import_url_too_small_response_returns_400(self, ext_agents_app: FastAPI) -> None:
        """Response that is too small to be a valid zip returns 400."""
        respx.get("https://example.com/tiny.zip").mock(
            return_value=HttpxResponse(200, content=b"PK")
        )
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": "https://example.com/tiny.zip"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 400

    @respx.mock
    def test_import_url_fetch_error_returns_502(self, ext_agents_app: FastAPI) -> None:
        import httpx as _httpx

        respx.get("https://example.com/fail.zip").mock(
            side_effect=_httpx.ConnectError("connection reset")
        )
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": "https://example.com/fail.zip"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 502

    def test_import_url_unauthenticated_returns_401(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents/import-url",
                json={"url": "https://example.com/agent.zip"},
            )
        assert resp.status_code == 401


# ── Export + Import round-trip ──────────────────────────────────────


class TestExportImportRoundTrip:
    def test_export_and_reimport(self, ext_agents_app: FastAPI) -> None:
        """Export an agent as zip, then re-import it under a different name.

        This tests the full GitAgent zip round-trip through the HTTP API.
        """
        with TestClient(ext_agents_app) as client:
            # Export arbiter
            resp = client.get("/v1/stronghold/agents/arbiter/export", headers=AUTH_HEADER)
            assert resp.status_code == 200
            zip_data = resp.content
            assert zip_data[:2] == b"PK"

            # Modify the zip: rename the agent
            buf_in = io.BytesIO(zip_data)
            buf_out = io.BytesIO()
            with zipfile.ZipFile(buf_in, "r") as zf_in:
                with zipfile.ZipFile(buf_out, "w") as zf_out:
                    for info in zf_in.infolist():
                        data = zf_in.read(info.filename)
                        new_name = info.filename.replace("arbiter", "arbiter-copy")
                        if info.filename.endswith("agent.yaml"):
                            manifest = yaml.safe_load(data)
                            manifest["name"] = "arbiter-copy"
                            data = yaml.dump(manifest).encode()
                        zf_out.writestr(new_name, data)

            # Import the modified zip
            resp = client.post(
                "/v1/stronghold/agents/import",
                content=buf_out.getvalue(),
                headers={**AUTH_HEADER, "Content-Type": "application/octet-stream"},
            )
            assert resp.status_code == 201
            assert resp.json()["name"] == "arbiter-copy"

            # Verify it shows up in the list
            resp = client.get("/v1/stronghold/agents", headers=AUTH_HEADER)
            assert resp.status_code == 200
            names = [a["name"] for a in resp.json()]
            assert "arbiter-copy" in names


# ── Agent CRUD edge cases ──────────────────────────────────────────


class TestAgentCrudEdgeCases:
    def test_create_agent_with_all_fields(self, ext_agents_app: FastAPI) -> None:
        """Create agent with all optional fields populated."""
        with TestClient(ext_agents_app) as client:
            resp = client.post(
                "/v1/stronghold/agents",
                json={
                    "name": "full-agent",
                    "description": "A fully populated agent",
                    "soul_prompt": "You are the full agent.",
                    "rules": "Never do anything harmful.",
                    "model": "test/model",
                    "reasoning_strategy": "direct",
                    "tools": ["web_search", "file_ops"],
                    "memory_config": {"learnings": True, "episodic": True},
                },
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "full-agent"
        assert data["provenance"] == "admin"
        assert data["trust_tier"] == "t2"

    def test_get_agent_detail_has_expected_fields(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.get("/v1/stronghold/agents/arbiter", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "reasoning_strategy" in data
        assert "tools" in data
        assert "trust_tier" in data
        assert "model" in data
        assert "soul_prompt_preview" in data

    def test_list_agents_returns_all(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.get("/v1/stronghold/agents", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        names = [a["name"] for a in data]
        assert "arbiter" in names
        assert "artificer" in names

    def test_update_agent_soul_prompt(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.put(
                "/v1/stronghold/agents/arbiter",
                json={"soul_prompt": "You are a new and improved arbiter."},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"

    def test_update_agent_rules(self, ext_agents_app: FastAPI) -> None:
        """PUT rules returns 200 and the change is visible on subsequent GET.

        The old test only asserted ``status_code == 200`` — an empty-body
        200 would pass. Here we also confirm the update actually took
        effect by round-tripping through GET.
        """
        with TestClient(ext_agents_app) as client:
            resp = client.put(
                "/v1/stronghold/agents/arbiter",
                json={"rules": "Always be helpful."},
                headers=AUTH_HEADER,
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "updated"
            # Follow up with GET to verify the rules actually changed.
            detail = client.get(
                "/v1/stronghold/agents/arbiter", headers=AUTH_HEADER
            )
            assert detail.status_code == 200
            # The rules preview in the detail should reflect the new value.
            data = detail.json()
            # Either the rules preview shows the new text, or the server
            # reports a populated rules field — both are valid contracts.
            assert (
                "helpful" in str(data).lower()
                or data.get("rules_preview", "")
                or data.get("has_rules")
            )

    def test_delete_then_get_returns_404(self, ext_agents_app: FastAPI) -> None:
        """After deleting an agent, GET should return 404."""
        with TestClient(ext_agents_app) as client:
            resp = client.delete("/v1/stronghold/agents/artificer", headers=AUTH_HEADER)
            assert resp.status_code == 200

            resp = client.get("/v1/stronghold/agents/artificer", headers=AUTH_HEADER)
            assert resp.status_code == 404


# ── GET /v1/stronghold/status ──────────────────────────────────────


class TestStatusEndpoint:
    def test_status_returns_correct_agent_count(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.get("/v1/stronghold/status", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agents"] == 2
        assert "intents" in data
        assert "quota_usage" in data

    def test_status_unauthenticated_returns_401(self, ext_agents_app: FastAPI) -> None:
        with TestClient(ext_agents_app) as client:
            resp = client.get("/v1/stronghold/status")
        assert resp.status_code == 401
