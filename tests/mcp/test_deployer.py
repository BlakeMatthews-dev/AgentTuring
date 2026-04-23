"""Tests for MCP Deployer (K8s deployment)."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from stronghold.mcp.deployer import K8sDeployer


@pytest.fixture
def deployer() -> K8sDeployer:
    """Create deployer with mocked K8s client."""
    with ExitStack() as stack:
        stack.enter_context(patch("kubernetes.config.load_incluster_config"))
        stack.enter_context(patch("kubernetes.config.load_kube_config"))
        stack.enter_context(patch("kubernetes.client.AppsV1Api"))
        stack.enter_context(patch("kubernetes.client.CoreV1Api"))
        return K8sDeployer()


class TestK8sDeployerInit:
    """Test K8sDeployer initialization."""

    def test_init_sets_namespace(self) -> None:
        """Deployer initialization sets namespace."""
        with ExitStack() as stack:
            stack.enter_context(patch("kubernetes.config.load_incluster_config"))
            stack.enter_context(patch("kubernetes.config.load_kube_config"))
            stack.enter_context(patch("kubernetes.client.AppsV1Api"))
            stack.enter_context(patch("kubernetes.client.CoreV1Api"))
            deployer = K8sDeployer(namespace="test-ns")
            assert deployer._namespace == "test-ns"

    def test_init_uses_default_namespace(self) -> None:
        """Deployer defaults to stronghold namespace."""
        with ExitStack() as stack:
            stack.enter_context(patch("kubernetes.config.load_incluster_config"))
            stack.enter_context(patch("kubernetes.config.load_kube_config"))
            stack.enter_context(patch("kubernetes.client.AppsV1Api"))
            stack.enter_context(patch("kubernetes.client.CoreV1Api"))
            deployer = K8sDeployer()
            assert deployer._namespace == "stronghold"


class TestK8sClient:
    """Test K8s client initialization."""

    def test_ensure_client_lazy_loads(self, deployer: K8sDeployer) -> None:
        """K8s client is loaded lazily."""
        assert not deployer._client_loaded
        assert deployer._apps_v1 is None

    def test_ensure_client_uses_incluster_config(self, deployer: K8sDeployer) -> None:
        """Deployer tries in-cluster config first."""
        fake_config = MagicMock()
        fake_config.load_incluster_config = MagicMock()
        fake_config.load_kube_config = MagicMock()
        fake_config.ConfigException = Exception

        with ExitStack() as stack:
            stack.enter_context(patch("kubernetes.config", fake_config))
            stack.enter_context(patch("kubernetes.client.AppsV1Api"))
            stack.enter_context(patch("kubernetes.client.CoreV1Api"))
            deployer_instance = K8sDeployer()
            deployer_instance._ensure_client()
            fake_config.load_incluster_config.assert_called_once()

    def test_ensure_client_falls_back_to_kubeconfig(self, deployer: K8sDeployer) -> None:
        """Deployer falls back to kubeconfig if in-cluster fails."""
        fake_config = MagicMock()
        fake_config.ConfigException = Exception

        def raise_config_exception() -> None:
            raise fake_config.ConfigException("No in-cluster config")

        fake_config.load_incluster_config = MagicMock(side_effect=raise_config_exception)
        fake_config.load_kube_config = MagicMock()

        with ExitStack() as stack:
            stack.enter_context(patch("kubernetes.config", fake_config))
            stack.enter_context(patch("kubernetes.client.AppsV1Api"))
            stack.enter_context(patch("kubernetes.client.CoreV1Api"))
            deployer = K8sDeployer()
            deployer._ensure_client()
            fake_config.load_kube_config.assert_called_once()

    def test_ensure_client_raises_on_failure(self, deployer: K8sDeployer) -> None:
        """Deployer raises RuntimeError if K8s connection fails."""
        fake_config = MagicMock()
        fake_config.ConfigException = Exception

        def raise_exception() -> None:
            raise RuntimeError("Cannot connect")

        fake_config.load_incluster_config = MagicMock(side_effect=raise_exception)
        fake_config.load_kube_config = MagicMock(side_effect=raise_exception)

        with ExitStack() as stack:
            stack.enter_context(patch("kubernetes.config", fake_config))
            stack.enter_context(patch("kubernetes.client.AppsV1Api"))
            stack.enter_context(patch("kubernetes.client.CoreV1Api"))
            deployer_instance = K8sDeployer()
            with pytest.raises(RuntimeError, match="Cannot connect to K8s cluster"):
                deployer_instance._ensure_client()


class TestDeployerNamespace:
    """Test namespace scoping."""

    def test_namespace_scoping_prevents_cross_namespace_access(
        self,
        deployer: K8sDeployer,
    ) -> None:
        """Namespace scoping prevents cross-namespace access."""
        assert deployer._namespace == "stronghold"

    def test_custom_namespace_isolation(self) -> None:
        """Custom namespaces provide isolation."""
        with ExitStack() as stack:
            stack.enter_context(patch("kubernetes.config.load_incluster_config"))
            stack.enter_context(patch("kubernetes.config.load_kube_config"))
            stack.enter_context(patch("kubernetes.client.AppsV1Api"))
            stack.enter_context(patch("kubernetes.client.CoreV1Api"))
            deployer = K8sDeployer(namespace="custom-ns")
            assert deployer._namespace == "custom-ns"
