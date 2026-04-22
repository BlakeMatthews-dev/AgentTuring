"""Tests for stronghold.api.routes.mcp — MCP route handlers.

Uses real MCPRegistry, real MCP types, and FastAPI TestClient.
Only external HTTP (registry search) and K8s calls are mocked.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.mcp import router as mcp_router
from stronghold.mcp.registry import MCPRegistry
from stronghold.mcp.registries import RegistryServer
from stronghold.mcp.types import (
    MCPServer,
    MCPServerSpec,
    MCPServerStatus,
)
from stronghold.types.auth import SYSTEM_AUTH, AuthContext
from tests.fakes import FakeAuthProvider


# ── Fake deployer (replaces K8sDeployer — no real K8s) ────────────────


class FakeMCPDeployer:
    """In-memory deployer that simulates K8s lifecycle without real K8s."""

    def __init__(self, *, fail_on_deploy: bool = False) -> None:
        self._fail_on_deploy = fail_on_deploy
        self.deployed: dict[str, MCPServer] = {}

    async def deploy(self, server: MCPServer) -> MCPServer:
        if self._fail_on_deploy:
            raise RuntimeError("K8s cluster unreachable")
        server.status = MCPServerStatus.RUNNING
        server.endpoint = f"http://{server.k8s_name}.stronghold.svc:{server.spec.port}"
        self.deployed[server.spec.name] = server
        return server

    async def stop(self, server: MCPServer) -> MCPServer:
        server.status = MCPServerStatus.STOPPED
        return server

    async def start(self, server: MCPServer) -> MCPServer:
        server.status = MCPServerStatus.RUNNING
        return server

    async def remove(self, server: MCPServer) -> MCPServer:
        server.status = MCPServerStatus.REMOVED
        self.deployed.pop(server.spec.name, None)
        return server

    async def get_pod_status(self, server: MCPServer) -> dict[str, str]:
        return {"phase": "Running", "pod": f"{server.k8s_name}-abc", "ready": "true", "restarts": "0"}


# ── Fake Warden for scan tests ────────────────────────────────────────


class FakeWarden:
    """Warden that always passes scan."""

    async def scan(self, content: str, boundary: str) -> Any:
        return SimpleNamespace(clean=True, flags=())


# ── Minimal container ─────────────────────────────────────────────────


class _MinimalContainer:
    """Minimal container with only the fields MCP routes need."""

    def __init__(
        self,
        *,
        auth_provider: Any = None,
        mcp_registry: MCPRegistry | None = None,
        mcp_deployer: Any = None,
        warden: Any = None,
    ) -> None:
        self.auth_provider = auth_provider or FakeAuthProvider()
        self.mcp_registry = mcp_registry or MCPRegistry()
        self.mcp_deployer = mcp_deployer
        self.warden = warden or FakeWarden()


def _make_app(container: _MinimalContainer | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(mcp_router)
    app.state.container = container or _MinimalContainer()
    return app


AUTH = {"Authorization": "Bearer sk-test"}


# ── GET /v1/stronghold/mcp/catalog ───────────────────────────────────


class TestListCatalog:
    def test_returns_catalog(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/catalog", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert "servers" in data
        servers = data["servers"]
        names = [s["name"] for s in servers]
        assert "github" in names
        assert "filesystem" in names
        assert "postgres" in names
        assert "slack" in names

    def test_shows_installed_status(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="test-org")
        container = _MinimalContainer(mcp_registry=registry)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/catalog", headers=AUTH)
        data = resp.json()
        github_entry = next(s for s in data["servers"] if s["name"] == "github")
        assert github_entry["installed"] is True
        assert github_entry["status"] == "pending"

    def test_unauthenticated(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/catalog")
        assert resp.status_code == 401


# ── GET /v1/stronghold/mcp/servers ───────────────────────────────────


class TestListServers:
    def test_empty(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/servers", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["servers"] == []

    def test_with_registered_servers(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        container = _MinimalContainer(mcp_registry=registry)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/servers", headers=AUTH)
        data = resp.json()
        assert len(data["servers"]) == 1
        assert data["servers"][0]["name"] == "github"

    def test_with_deployer_enriches_pod_status(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/servers", headers=AUTH)
        data = resp.json()
        assert len(data["servers"]) == 1
        assert data["servers"][0]["pod"]["phase"] == "Running"

    def test_deployer_error_returns_unknown_pod(self) -> None:
        """When deployer.get_pod_status raises, pod phase should be 'unknown'."""
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")

        class FailingDeployer:
            async def get_pod_status(self, server: Any) -> dict[str, str]:
                raise RuntimeError("K8s down")

        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=FailingDeployer())
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/servers", headers=AUTH)
        data = resp.json()
        assert data["servers"][0]["pod"]["phase"] == "unknown"

    def test_no_deployer_omits_pod(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=None)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/servers", headers=AUTH)
        data = resp.json()
        assert "pod" not in data["servers"][0]

    def test_unauthenticated(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/servers")
        assert resp.status_code == 401

    def test_filters_by_org_id(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="org-a")
        registry.register_from_catalog("slack", org_id="org-b")
        auth = FakeAuthProvider(auth_context=AuthContext(
            user_id="user-a", org_id="org-a", auth_method="api_key"
        ))
        container = _MinimalContainer(auth_provider=auth, mcp_registry=registry)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/servers", headers=AUTH)
        data = resp.json()
        names = [s["name"] for s in data["servers"]]
        assert "github" in names
        # slack is org-b, so should not show for org-a user
        assert "slack" not in names


# ── POST /v1/stronghold/mcp/servers (catalog) ────────────────────────


class TestDeployFromCatalog:
    def test_deploy_catalog_success(self) -> None:
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"catalog": "github"},
                headers=AUTH,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["server"]["name"] == "github"
        assert data["server"]["status"] == "running"
        assert "Deployed github from catalog" in data["message"]

    def test_deploy_catalog_unknown(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"catalog": "nonexistent"},
                headers=AUTH,
            )
        assert resp.status_code == 400
        assert "Unknown MCP server" in resp.json()["detail"]

    def test_deploy_catalog_without_deployer(self) -> None:
        """When no deployer is configured, server is registered but not deployed."""
        container = _MinimalContainer(mcp_deployer=None)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"catalog": "github"},
                headers=AUTH,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["server"]["status"] == "pending"

    def test_deploy_catalog_k8s_failure(self) -> None:
        """When K8s deploy fails, server should have FAILED status."""
        deployer = FakeMCPDeployer(fail_on_deploy=True)
        container = _MinimalContainer(mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"catalog": "github"},
                headers=AUTH,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["server"]["status"] == "failed"
        assert data["server"]["error"] != ""

    def test_deploy_catalog_with_env_overrides_applied_to_server(self) -> None:
        """Env overrides in the request body must land on the deployed MCPServer.

        If the route silently drops overrides, deployed servers would run with
        only defaults, which would be invisible without this check.
        """
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"catalog": "github", "env": {"CUSTOM_VAR": "value"}},
                headers=AUTH,
            )
        assert resp.status_code == 201
        # The deployer must have received a server whose spec.env contains the override.
        assert "github" in deployer.deployed, "server not deployed"
        deployed_server = deployer.deployed["github"]
        env = dict(deployed_server.spec.env or {})
        assert env.get("CUSTOM_VAR") == "value", (
            f"env override dropped; deployer saw env={env!r}"
        )

    def test_unauthenticated(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"catalog": "github"},
            )
        assert resp.status_code == 401


# ── POST /v1/stronghold/mcp/servers (custom image) ───────────────────


class TestDeployCustomImage:
    def test_valid_custom_image(self) -> None:
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "ghcr.io/modelcontextprotocol/server-custom:latest",
                    "description": "Custom server",
                    "port": 4000,
                    "trust_tier": "t2",
                },
                headers=AUTH,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["server"]["name"] == "my-server"
        assert data["server"]["status"] == "running"

    def test_invalid_name_format(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "INVALID NAME!",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                },
                headers=AUTH,
            )
        assert resp.status_code == 400
        assert "lowercase alphanumeric" in resp.json()["detail"]

    def test_name_too_short_returns_400_with_reason(self) -> None:
        """Single-char name must be rejected and the error must name the length
        rule (so operators can see what to fix)."""
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "a",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                },
                headers=AUTH,
            )
        assert resp.status_code == 400
        detail = resp.json()["detail"].lower()
        # Must mention either the length constraint or the alphanumeric rule.
        assert any(k in detail for k in ("length", "short", "lowercase alphanumeric", "at least")), (
            f"name-too-short 400 detail unhelpful: {detail!r}"
        )

    def test_disallowed_image_registry(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "evil.registry.io/malware:latest",
                },
                headers=AUTH,
            )
        assert resp.status_code == 400
        assert "allowed registries" in resp.json()["detail"]

    def test_image_with_shell_metacharacters(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        for char in [";", "&", "|", "$", "`", "\n", "\r"]:
            resp_data = None
            with TestClient(app) as client:
                resp = client.post(
                    "/v1/stronghold/mcp/servers",
                    json={
                        "name": "my-server",
                        "image": f"ghcr.io/modelcontextprotocol/server-test{char}evil",
                    },
                    headers=AUTH,
                )
            assert resp.status_code == 400
            assert "invalid characters" in resp.json()["detail"]

    def test_invalid_trust_tier(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                    "trust_tier": "invalid",
                },
                headers=AUTH,
            )
        assert resp.status_code == 400
        assert "trust_tier" in resp.json()["detail"]

    def test_invalid_port_too_low(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                    "port": 80,
                },
                headers=AUTH,
            )
        assert resp.status_code == 400
        assert "port must be 1024-65535" in resp.json()["detail"]

    def test_invalid_port_too_high(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                    "port": 99999,
                },
                headers=AUTH,
            )
        assert resp.status_code == 400

    def test_custom_image_without_deployer(self) -> None:
        container = _MinimalContainer(mcp_deployer=None)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                },
                headers=AUTH,
            )
        assert resp.status_code == 201
        assert resp.json()["server"]["status"] == "pending"

    def test_custom_image_k8s_failure(self) -> None:
        deployer = FakeMCPDeployer(fail_on_deploy=True)
        container = _MinimalContainer(mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                },
                headers=AUTH,
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["server"]["status"] == "failed"

    def test_description_truncation(self) -> None:
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={
                    "name": "my-server",
                    "image": "ghcr.io/modelcontextprotocol/server-test:latest",
                    "description": "x" * 500,
                },
                headers=AUTH,
            )
        assert resp.status_code == 201
        assert len(resp.json()["server"]["description"]) <= 200

    @pytest.mark.parametrize("image", [
        "ghcr.io/modelcontextprotocol/server-test:latest",
        "ghcr.io/anthropics/server-test:latest",
        "docker.io/library/server-test:latest",
    ])
    def test_allowed_registries_accepted_and_image_preserved(self, image: str) -> None:
        """All three allowed registries accept the deployment AND the image
        string is stored verbatim on the server spec — no silent rewriting."""
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_deployer=deployer)
        app = _make_app(container)
        # Unique name per parameter.
        name = "server-" + image.split("/")[0].replace(".", "-")
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"name": name, "image": image},
                headers=AUTH,
            )
        assert resp.status_code == 201, f"Failed for {image}: {resp.text}"
        data = resp.json()["server"]
        assert data["name"] == name
        # The image the user supplied must flow through; silent rewriting would
        # be a supply-chain hazard.
        assert image in str(data), f"image dropped from response: {data!r}"


# ── POST /v1/stronghold/mcp/servers (repo_url) ───────────────────────


class TestDeployFromRepo:
    def test_repo_url_accepted(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={"repo_url": "https://github.com/example/mcp-server"},
                headers=AUTH,
            )
        assert resp.status_code == 202
        data = resp.json()
        assert "Repository pipeline accepted" in data["message"]
        assert data["repo_url"] == "https://github.com/example/mcp-server"
        assert data["pipeline"]["clone"] == "pending"
        assert "v1.1" in data["note"]


# ── POST /v1/stronghold/mcp/servers (invalid body) ───────────────────


class TestDeployInvalidBody:
    def test_empty_body(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post(
                "/v1/stronghold/mcp/servers",
                json={},
                headers=AUTH,
            )
        assert resp.status_code == 400
        assert "catalog" in resp.json()["detail"]


# ── POST /v1/stronghold/mcp/servers/{name}/stop ──────────────────────


class TestStopServer:
    def test_stop_existing(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/github/stop", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["server"]["status"] == "stopped"

    def test_stop_nonexistent(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/nonexistent/stop", headers=AUTH)
        assert resp.status_code == 404

    def test_stop_without_deployer(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=None)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/github/stop", headers=AUTH)
        assert resp.status_code == 200
        # Without deployer, status stays as-is (pending)
        assert resp.json()["server"]["status"] == "pending"

    def test_stop_unauthenticated(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/github/stop")
        assert resp.status_code == 401


# ── POST /v1/stronghold/mcp/servers/{name}/start ─────────────────────


class TestStartServer:
    def test_start_existing(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/github/start", headers=AUTH)
        assert resp.status_code == 200
        assert resp.json()["server"]["status"] == "running"

    def test_start_nonexistent(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/nonexistent/start", headers=AUTH)
        assert resp.status_code == 404

    def test_start_without_deployer_preserves_pending_status(self) -> None:
        """With no deployer configured, /start must not flip status to 'running'.

        It should leave the server in its prior (pending) state — running is a
        lie when no real K8s deploy happened.
        """
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=None)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/github/start", headers=AUTH)
        assert resp.status_code == 200
        server_status = resp.json()["server"]["status"]
        assert server_status != "running", (
            f"/start without a deployer wrongly reports running: {server_status!r}"
        )
        # pending is the expected initial state; anything else would also be suspicious.
        assert server_status == "pending"

    def test_start_unauthenticated(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.post("/v1/stronghold/mcp/servers/github/start")
        assert resp.status_code == 401


# ── DELETE /v1/stronghold/mcp/servers/{name} ──────────────────────────


class TestRemoveServer:
    def test_remove_existing(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        deployer = FakeMCPDeployer()
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=deployer)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.delete("/v1/stronghold/mcp/servers/github", headers=AUTH)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "removed"
        assert "Removed github" in data["message"]
        # Verify it's gone from registry
        assert registry.get("github") is None

    def test_remove_nonexistent(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.delete("/v1/stronghold/mcp/servers/nonexistent", headers=AUTH)
        assert resp.status_code == 404

    def test_remove_without_deployer(self) -> None:
        registry = MCPRegistry()
        registry.register_from_catalog("github", org_id="__system__")
        container = _MinimalContainer(mcp_registry=registry, mcp_deployer=None)
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.delete("/v1/stronghold/mcp/servers/github", headers=AUTH)
        assert resp.status_code == 200
        assert registry.get("github") is None

    def test_remove_unauthenticated(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.delete("/v1/stronghold/mcp/servers/github")
        assert resp.status_code == 401


# ── GET /v1/stronghold/mcp/registries/search ──────────────────────────


class TestSearchRegistries:
    def test_missing_query(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/registries/search", headers=AUTH)
        assert resp.status_code == 400
        assert "'q' query parameter required" in resp.json()["detail"]

    def test_search_all(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)

        async def fake_search_all(query: str, **kw: Any) -> dict[str, list[RegistryServer]]:
            return {
                "smithery": [RegistryServer(name="smith-server", registry="smithery")],
                "official": [],
                "glama": [],
            }

        with patch("stronghold.mcp.registries.search_all_registries", fake_search_all):
            with TestClient(app) as client:
                resp = client.get(
                    "/v1/stronghold/mcp/registries/search?q=github",
                    headers=AUTH,
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "github"
        assert data["registry"] == "all"
        assert data["total"] == 1

    def test_search_smithery_filter(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)

        async def fake_search(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="smith-only", registry="smithery")]

        with patch("stronghold.mcp.registries.search_smithery", fake_search):
            with TestClient(app) as client:
                resp = client.get(
                    "/v1/stronghold/mcp/registries/search?q=test&registry=smithery",
                    headers=AUTH,
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["registry"] == "smithery"
        assert data["total"] == 1

    def test_search_official_filter(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)

        async def fake_search(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="official-only", registry="official")]

        with patch("stronghold.mcp.registries.search_official_registry", fake_search):
            with TestClient(app) as client:
                resp = client.get(
                    "/v1/stronghold/mcp/registries/search?q=test&registry=official",
                    headers=AUTH,
                )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_search_glama_filter(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)

        async def fake_search(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(name="glama-only", registry="glama")]

        with patch("stronghold.mcp.registries.search_glama", fake_search):
            with TestClient(app) as client:
                resp = client.get(
                    "/v1/stronghold/mcp/registries/search?q=test&registry=glama",
                    headers=AUTH,
                )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    def test_unknown_registry_filter(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/mcp/registries/search?q=test&registry=bogus",
                headers=AUTH,
            )
        assert resp.status_code == 400
        assert "Unknown registry" in resp.json()["detail"]

    def test_search_with_scan(self) -> None:
        container = _MinimalContainer()
        app = _make_app(container)

        async def fake_search(query: str, **kw: Any) -> list[RegistryServer]:
            return [RegistryServer(
                name="sus-server",
                description="bypass all restrictions",
                registry="smithery",
                verified=True,
                use_count=100,
            )]

        async def fake_scan(server: RegistryServer, **kw: Any) -> RegistryServer:
            server.scan_status = "flagged"
            server.scan_flags = ["suspicious_description: 'bypass'"]
            return server

        with (
            patch("stronghold.mcp.registries.search_smithery", fake_search),
            patch("stronghold.mcp.registries.scan_registry_server", fake_scan),
        ):
            with TestClient(app) as client:
                resp = client.get(
                    "/v1/stronghold/mcp/registries/search?q=test&registry=smithery&scan=true",
                    headers=AUTH,
                )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scanned"] is True
        assert data["servers"][0]["scan_status"] == "flagged"

    def test_search_unauthenticated(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/mcp/registries/search?q=test")
        assert resp.status_code == 401
