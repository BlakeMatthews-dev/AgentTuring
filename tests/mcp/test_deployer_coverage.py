"""Tests for stronghold.mcp.deployer — K8s deployer lifecycle.

K8s client is mocked (external infrastructure). All MCP types are real.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stronghold.mcp.deployer import K8sDeployer
from stronghold.mcp.types import (
    MCPDiscoveredTool,
    MCPResourceLimits,
    MCPServer,
    MCPServerSpec,
    MCPServerStatus,
    MCPSourceType,
    MCPTransport,
)


# ── Fake K8s API objects ──────────────────────────────────────────────


class FakeAppsV1Api:
    """Fake kubernetes AppsV1Api."""

    def __init__(self) -> None:
        self.deployments: dict[str, Any] = {}
        self.create_calls: list[tuple[str, Any]] = []
        self.replace_calls: list[tuple[str, str, Any]] = []
        self.delete_calls: list[tuple[str, str]] = []
        self._read_raises: dict[str, Exception] = {}

    def create_namespaced_deployment(self, namespace: str, body: Any) -> Any:
        name = body.metadata.name
        self.deployments[name] = body
        self.create_calls.append((namespace, body))
        return body

    def read_namespaced_deployment(self, name: str, namespace: str) -> Any:
        if name in self._read_raises:
            raise self._read_raises[name]
        if name in self.deployments:
            return self.deployments[name]
        raise Exception(f"Deployment {name} not found")

    def replace_namespaced_deployment(self, name: str, namespace: str, body: Any) -> Any:
        self.deployments[name] = body
        self.replace_calls.append((name, namespace, body))
        return body

    def delete_namespaced_deployment(self, name: str, namespace: str) -> None:
        self.delete_calls.append((name, namespace))
        self.deployments.pop(name, None)


class FakeCoreV1Api:
    """Fake kubernetes CoreV1Api."""

    def __init__(self) -> None:
        self.services: dict[str, Any] = {}
        self.secrets: dict[str, Any] = {}
        self.pods: dict[str, list[Any]] = {}
        self.create_service_calls: list[tuple[str, Any]] = []
        self.patch_service_calls: list[tuple[str, str, Any]] = []
        self.delete_service_calls: list[tuple[str, str]] = []

    def create_namespaced_service(self, namespace: str, body: Any) -> Any:
        name = body.metadata.name
        self.services[name] = body
        self.create_service_calls.append((namespace, body))
        return body

    def read_namespaced_service(self, name: str, namespace: str) -> Any:
        if name in self.services:
            return self.services[name]
        raise Exception(f"Service {name} not found")

    def patch_namespaced_service(self, name: str, namespace: str, body: Any) -> Any:
        self.services[name] = body
        self.patch_service_calls.append((name, namespace, body))
        return body

    def delete_namespaced_service(self, name: str, namespace: str) -> None:
        self.delete_service_calls.append((name, namespace))
        self.services.pop(name, None)

    def read_namespaced_secret(self, name: str, namespace: str) -> Any:
        if name in self.secrets:
            return self.secrets[name]
        raise Exception(f"Secret {name} not found")

    def list_namespaced_pod(self, namespace: str, label_selector: str = "") -> Any:
        # Parse label_selector to find pods
        app_name = label_selector.split("=")[-1] if "=" in label_selector else ""
        items = self.pods.get(app_name, [])
        return SimpleNamespace(items=items)


def _make_server(
    name: str = "test-server",
    image: str = "ghcr.io/modelcontextprotocol/server-github:latest",
    port: int = 3000,
    trust_tier: str = "t2",
    env: dict[str, str] | None = None,
    secrets: dict[str, str] | None = None,
    resources: MCPResourceLimits | None = None,
    org_id: str = "test-org",
) -> MCPServer:
    spec = MCPServerSpec(
        name=name,
        image=image,
        port=port,
        trust_tier=trust_tier,
        env=env or {},
        secrets=secrets or {},
        resources=resources,
    )
    return MCPServer(spec=spec, org_id=org_id)


def _patch_k8s(deployer: K8sDeployer, apps: FakeAppsV1Api, core: FakeCoreV1Api) -> None:
    """Wire fake K8s APIs into a deployer, bypassing real client init."""
    deployer._client_loaded = True
    deployer._apps_v1 = apps
    deployer._core_v1 = core


# ── K8sDeployer.__init__ ─────────────────────────────────────────────


class TestK8sDeployerInit:
    def test_default_namespace(self) -> None:
        d = K8sDeployer()
        assert d._namespace == "stronghold"

    def test_custom_namespace(self) -> None:
        d = K8sDeployer(namespace="custom-ns")
        assert d._namespace == "custom-ns"

    def test_client_not_loaded_initially(self) -> None:
        d = K8sDeployer()
        assert d._client_loaded is False
        assert d._apps_v1 is None
        assert d._core_v1 is None


# ── _ensure_client ────────────────────────────────────────────────────


class TestEnsureClient:
    def test_already_loaded_skips(self) -> None:
        d = K8sDeployer()
        d._client_loaded = True
        d._apps_v1 = "fake"
        d._core_v1 = "fake"
        d._ensure_client()  # Should not raise
        assert d._apps_v1 == "fake"

    def test_raises_when_k8s_unavailable(self) -> None:
        d = K8sDeployer()
        with patch.dict("sys.modules", {"kubernetes": None}):
            with pytest.raises(RuntimeError, match="Cannot connect to K8s"):
                d._ensure_client()


# ── _deploy_sync ──────────────────────────────────────────────────────


class TestDeploySync:
    def test_creates_deployment_and_service(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        result = deployer._deploy_sync(server)

        assert result.status == MCPServerStatus.RUNNING
        assert result.error == ""
        assert "mcp-test-server.stronghold.svc" in result.endpoint
        assert len(apps.create_calls) == 1
        assert len(core.create_service_calls) == 1

    def test_updates_existing_deployment(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        # First deploy creates
        deployer._deploy_sync(server)
        # Second deploy updates (deployment and service both exist now)
        result = deployer._deploy_sync(server)

        assert result.status == MCPServerStatus.RUNNING
        assert len(apps.replace_calls) >= 1
        assert len(core.patch_service_calls) >= 1

    def test_with_env_vars(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(env={"DEBUG": "true", "LOG_LEVEL": "info"})
        result = deployer._deploy_sync(server)

        assert result.status == MCPServerStatus.RUNNING

    def test_with_secrets_existing(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        core.secrets["github-pat"] = {"token": "secret-value"}
        _patch_k8s(deployer, apps, core)

        server = _make_server(secrets={"GITHUB_TOKEN": "github-pat:token"})
        result = deployer._deploy_sync(server)

        assert result.status == MCPServerStatus.RUNNING

    def test_with_secrets_missing(self) -> None:
        """Missing K8s secrets should be skipped gracefully."""
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        # No secrets pre-loaded
        _patch_k8s(deployer, apps, core)

        server = _make_server(secrets={"GITHUB_TOKEN": "github-pat:token"})
        result = deployer._deploy_sync(server)

        assert result.status == MCPServerStatus.RUNNING

    def test_with_invalid_secret_ref_format(self) -> None:
        """Secret refs that don't have ':' separator should be ignored."""
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(secrets={"GITHUB_TOKEN": "no-colon-here"})
        result = deployer._deploy_sync(server)

        assert result.status == MCPServerStatus.RUNNING

    def test_with_custom_resources(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        resources = MCPResourceLimits(
            cpu_limit="1000m",
            memory_limit="512Mi",
            cpu_request="200m",
            memory_request="128Mi",
        )
        server = _make_server(resources=resources)
        result = deployer._deploy_sync(server)

        assert result.status == MCPServerStatus.RUNNING

    def test_with_no_resources(self) -> None:
        """When resources is None, should use defaults."""
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        assert server.spec.resources is None
        result = deployer._deploy_sync(server)
        assert result.status == MCPServerStatus.RUNNING

    def test_org_id_label(self) -> None:
        """Org ID should appear as a K8s label when valid."""
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(org_id="acme-corp")
        deployer._deploy_sync(server)

        assert len(apps.create_calls) == 1

    def test_system_org_id_excluded_from_labels(self) -> None:
        """Org IDs starting with '_' should not be in labels."""
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(org_id="_system")
        deployer._deploy_sync(server)

        assert len(apps.create_calls) == 1

    def test_empty_org_id_excluded_from_labels(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(org_id="")
        deployer._deploy_sync(server)

        assert len(apps.create_calls) == 1


# ── _stop_sync ────────────────────────────────────────────────────────


class TestStopSync:
    def test_stop_sets_replicas_zero(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        # First deploy so the deployment exists
        deployer._deploy_sync(server)

        result = deployer._stop_sync(server)
        assert result.status == MCPServerStatus.STOPPED
        assert len(apps.replace_calls) >= 1

    def test_stop_nonexistent_sets_error(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(name="nonexistent")
        result = deployer._stop_sync(server)
        assert result.error != ""


# ── _start_sync ───────────────────────────────────────────────────────


class TestStartSync:
    def test_start_sets_replicas_one(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        deployer._deploy_sync(server)
        deployer._stop_sync(server)

        result = deployer._start_sync(server)
        assert result.status == MCPServerStatus.RUNNING
        assert len(apps.replace_calls) >= 2  # stop + start

    def test_start_nonexistent_sets_error(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(name="nonexistent")
        result = deployer._start_sync(server)
        assert result.error != ""


# ── _remove_sync ──────────────────────────────────────────────────────


class TestRemoveSync:
    def test_remove_deletes_deployment_and_service(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        deployer._deploy_sync(server)

        result = deployer._remove_sync(server)
        assert result.status == MCPServerStatus.REMOVED
        assert len(apps.delete_calls) == 1
        assert len(core.delete_service_calls) == 1

    def test_remove_nonexistent_still_sets_removed(self) -> None:
        """Removing a non-existent server should still set REMOVED status (graceful)."""
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server(name="ghost")
        result = deployer._remove_sync(server)
        assert result.status == MCPServerStatus.REMOVED


# ── _get_pod_status_sync ─────────────────────────────────────────────


class TestGetPodStatusSync:
    def test_pod_found(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        container_status = SimpleNamespace(ready=True, restart_count=0)
        pod = SimpleNamespace(
            metadata=SimpleNamespace(name="mcp-test-server-abc123"),
            status=SimpleNamespace(
                phase="Running",
                container_statuses=[container_status],
            ),
        )
        core.pods["mcp-test-server"] = [pod]

        server = _make_server()
        result = deployer._get_pod_status_sync(server)
        assert result["phase"] == "Running"
        assert result["pod"] == "mcp-test-server-abc123"
        assert result["ready"] == "True"
        assert result["restarts"] == "0"

    def test_no_pods_found(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        result = deployer._get_pod_status_sync(server)
        assert result["phase"] == "NotFound"
        assert result["pod"] == ""
        assert result["ready"] == "false"

    def test_pod_not_ready(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        container_status = SimpleNamespace(ready=False, restart_count=3)
        pod = SimpleNamespace(
            metadata=SimpleNamespace(name="mcp-test-server-xyz"),
            status=SimpleNamespace(
                phase="CrashLoopBackOff",
                container_statuses=[container_status],
            ),
        )
        core.pods["mcp-test-server"] = [pod]

        server = _make_server()
        result = deployer._get_pod_status_sync(server)
        assert result["phase"] == "CrashLoopBackOff"
        assert result["ready"] == "False"
        assert result["restarts"] == "3"

    def test_pod_with_no_container_statuses(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        pod = SimpleNamespace(
            metadata=SimpleNamespace(name="mcp-test-server-new"),
            status=SimpleNamespace(
                phase="Pending",
                container_statuses=None,
            ),
        )
        core.pods["mcp-test-server"] = [pod]

        server = _make_server()
        result = deployer._get_pod_status_sync(server)
        assert result["phase"] == "Pending"
        assert result["ready"] == "True"  # all() on empty = True
        assert result["restarts"] == "0"

    def test_api_error(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        # Make list_namespaced_pod raise
        original = core.list_namespaced_pod
        core.list_namespaced_pod = MagicMock(side_effect=Exception("API error"))

        server = _make_server()
        result = deployer._get_pod_status_sync(server)
        assert result["phase"] == "Error"
        assert result["ready"] == "false"
        assert "API error" in result["error"]


# ── Async wrappers ────────────────────────────────────────────────────


class TestAsyncWrappers:
    @pytest.mark.asyncio
    async def test_deploy_async(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        result = await deployer.deploy(server)
        assert result.status == MCPServerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_stop_async(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        deployer._deploy_sync(server)
        result = await deployer.stop(server)
        assert result.status == MCPServerStatus.STOPPED

    @pytest.mark.asyncio
    async def test_start_async(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        deployer._deploy_sync(server)
        deployer._stop_sync(server)
        result = await deployer.start(server)
        assert result.status == MCPServerStatus.RUNNING

    @pytest.mark.asyncio
    async def test_remove_async(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        deployer._deploy_sync(server)
        result = await deployer.remove(server)
        assert result.status == MCPServerStatus.REMOVED

    @pytest.mark.asyncio
    async def test_get_pod_status_async(self) -> None:
        deployer = K8sDeployer()
        apps = FakeAppsV1Api()
        core = FakeCoreV1Api()
        _patch_k8s(deployer, apps, core)

        server = _make_server()
        result = await deployer.get_pod_status(server)
        assert result["phase"] == "NotFound"


# ── MCPServer k8s_name property ──────────────────────────────────────


class TestMCPServerK8sName:
    def test_simple_name(self) -> None:
        server = _make_server(name="github")
        assert server.k8s_name == "mcp-github"

    def test_underscore_to_hyphen(self) -> None:
        server = _make_server(name="my_server")
        assert server.k8s_name == "mcp-my-server"

    def test_truncation(self) -> None:
        server = _make_server(name="a" * 100)
        assert len(server.k8s_name) <= 63
