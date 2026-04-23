"""K8s deployer: creates and manages MCP server pods.

Uses the kubernetes Python client to create Deployment + Service
in the stronghold namespace. Each MCP server gets:
- A Deployment (1 replica, resource-limited)
- A ClusterIP Service (accessible only within the cluster)
- Network isolation via namespace scoping
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stronghold.mcp.types import MCPServer

logger = logging.getLogger("stronghold.mcp.deployer")


class K8sDeployer:
    """Deploy MCP servers as K8s pods."""

    def __init__(self, namespace: str = "stronghold") -> None:
        self._namespace = namespace
        self._client_loaded = False
        self._apps_v1: Any = None
        self._core_v1: Any = None

    def _ensure_client(self) -> None:
        """Lazy-load K8s client (avoids import cost at startup)."""
        if self._client_loaded:
            return
        try:
            from kubernetes import client, config  # type: ignore[import-untyped]  # noqa: PLC0415

            # Try in-cluster first (running inside K8s), fall back to kubeconfig
            try:
                config.load_incluster_config()
                logger.info("K8s: loaded in-cluster config")
            except config.ConfigException:
                config.load_kube_config()
                logger.info("K8s: loaded kubeconfig")

            self._apps_v1 = client.AppsV1Api()
            self._core_v1 = client.CoreV1Api()
            self._client_loaded = True
        except Exception as e:
            logger.error("K8s client init failed: %s", e)
            raise RuntimeError(f"Cannot connect to K8s cluster: {e}") from e

    async def deploy(self, server: MCPServer) -> MCPServer:
        """Create K8s Deployment + Service for an MCP server."""
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(None, self._deploy_sync, server)

    def _deploy_sync(self, server: MCPServer) -> MCPServer:
        """Sync deployment (runs in thread pool to avoid blocking event loop)."""
        from kubernetes import client  # noqa: PLC0415

        from stronghold.mcp.types import MCPServerStatus  # noqa: PLC0415

        self._ensure_client()

        name = server.k8s_name
        ns = self._namespace
        spec = server.spec
        limits = spec.resources

        # Build env vars (skip secrets that reference non-existent K8s secrets)
        env_vars = []
        for k, v in spec.env.items():
            env_vars.append(client.V1EnvVar(name=k, value=v))
        for k, secret_ref in spec.secrets.items():
            parts = secret_ref.split(":", 1)
            if len(parts) == 2:  # noqa: PLR2004
                # Check if the secret exists before referencing it
                try:
                    self._core_v1.read_namespaced_secret(parts[0], ns)
                    env_vars.append(
                        client.V1EnvVar(
                            name=k,
                            value_from=client.V1EnvVarSource(
                                secret_key_ref=client.V1SecretKeySelector(
                                    name=parts[0], key=parts[1]
                                )
                            ),
                        )
                    )
                except Exception:
                    # Logs the k8s Secret *name* and env-var key, never the value. The
                    # semgrep keyword match on "Secret" is a false positive here.
                    # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure  # noqa: E501
                    logger.warning(
                        "k8s Secret resource %s not found, skipping env var %s",
                        parts[0],
                        k,
                    )

        # Resource limits
        resources = client.V1ResourceRequirements(
            limits={
                "cpu": limits.cpu_limit if limits else "500m",
                "memory": limits.memory_limit if limits else "256Mi",
            },
            requests={
                "cpu": limits.cpu_request if limits else "100m",
                "memory": limits.memory_request if limits else "64Mi",
            },
        )

        # Container
        container = client.V1Container(
            name=name,
            image=spec.image,
            ports=[client.V1ContainerPort(container_port=spec.port)],
            args=spec.args or ["--transport", spec.transport.value],
            env=env_vars or None,
            resources=resources,
        )

        # Labels for governance tracking (all values sanitized for K8s)
        import re as _re  # noqa: PLC0415

        def _safe_label(value: str, max_len: int = 63) -> str:
            """Sanitize a value for K8s label compliance."""
            sanitized = _re.sub(r"[^a-zA-Z0-9._-]", "-", str(value))[:max_len]
            return sanitized.strip("-._") or "unknown"

        labels = {
            "app": _safe_label(name),
            "stronghold.io/component": "mcp-server",
            "stronghold.io/trust-tier": _safe_label(spec.trust_tier),
            "stronghold.io/managed-by": "stronghold",
        }
        if server.org_id and not server.org_id.startswith("_"):
            labels["stronghold.io/org"] = _safe_label(server.org_id)

        # C11: Pod security context — run as non-root with read-only fs
        pod_security = client.V1PodSecurityContext(
            run_as_non_root=True,
            run_as_user=1000,
            run_as_group=1000,
            fs_group=1000,
        )
        container_security = client.V1SecurityContext(
            read_only_root_filesystem=True,
            allow_privilege_escalation=False,
            capabilities=client.V1Capabilities(drop=["ALL"]),
        )
        container.security_context = container_security

        # Deployment
        deployment = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=name, namespace=ns, labels=labels),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(match_labels={"app": name}),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=labels),
                    spec=client.V1PodSpec(
                        containers=[container],
                        security_context=pod_security,
                        service_account_name=f"stronghold-mcp-{_safe_label(name)}",
                        automount_service_account_token=False,
                    ),
                ),
            ),
        )

        # Service (ClusterIP — only reachable within cluster)
        service = client.V1Service(
            metadata=client.V1ObjectMeta(name=name, namespace=ns, labels=labels),
            spec=client.V1ServiceSpec(
                selector={"app": name},
                ports=[client.V1ServicePort(port=spec.port, target_port=spec.port)],
                type="ClusterIP",
            ),
        )

        try:
            server.status = MCPServerStatus.DEPLOYING

            # Create or update deployment
            try:
                self._apps_v1.read_namespaced_deployment(name, ns)
                self._apps_v1.replace_namespaced_deployment(name, ns, deployment)
                logger.info("Updated deployment: %s/%s", ns, name)
            except Exception:
                self._apps_v1.create_namespaced_deployment(ns, deployment)
                logger.info("Created deployment: %s/%s", ns, name)

            # Create or update service
            try:
                self._core_v1.read_namespaced_service(name, ns)
                # Service exists, patch it
                self._core_v1.patch_namespaced_service(name, ns, service)
            except Exception:
                self._core_v1.create_namespaced_service(ns, service)
                logger.info("Created service: %s/%s", ns, name)

            server.endpoint = f"http://{name}.{ns}.svc:{spec.port}"
            server.status = MCPServerStatus.RUNNING
            server.error = ""

        except Exception as e:
            logger.error("Deploy failed for %s: %s", name, e)
            server.status = MCPServerStatus.FAILED
            server.error = str(e)

        return server

    async def stop(self, server: MCPServer) -> MCPServer:
        """Scale deployment to 0."""
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(None, self._stop_sync, server)

    def _stop_sync(self, server: MCPServer) -> MCPServer:
        from stronghold.mcp.types import MCPServerStatus  # noqa: PLC0415

        self._ensure_client()
        name = server.k8s_name
        try:
            deployment = self._apps_v1.read_namespaced_deployment(name, self._namespace)
            deployment.spec.replicas = 0
            self._apps_v1.replace_namespaced_deployment(name, self._namespace, deployment)
            server.status = MCPServerStatus.STOPPED
            logger.info("Stopped: %s", name)
        except Exception as e:
            server.error = str(e)
            logger.error("Stop failed for %s: %s", name, e)
        return server

    async def start(self, server: MCPServer) -> MCPServer:
        """Scale deployment back to 1."""
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(None, self._start_sync, server)

    def _start_sync(self, server: MCPServer) -> MCPServer:
        from stronghold.mcp.types import MCPServerStatus  # noqa: PLC0415

        self._ensure_client()
        name = server.k8s_name
        try:
            deployment = self._apps_v1.read_namespaced_deployment(name, self._namespace)
            deployment.spec.replicas = 1
            self._apps_v1.replace_namespaced_deployment(name, self._namespace, deployment)
            server.status = MCPServerStatus.RUNNING
            logger.info("Started: %s", name)
        except Exception as e:
            server.error = str(e)
            logger.error("Start failed for %s: %s", name, e)
        return server

    async def remove(self, server: MCPServer) -> MCPServer:
        """Delete K8s resources entirely."""
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(None, self._remove_sync, server)

    def _remove_sync(self, server: MCPServer) -> MCPServer:
        from stronghold.mcp.types import MCPServerStatus  # noqa: PLC0415

        self._ensure_client()
        name = server.k8s_name
        ns = self._namespace
        try:
            self._apps_v1.delete_namespaced_deployment(name, ns)
            logger.info("Deleted deployment: %s", name)
        except Exception:
            pass
        try:
            self._core_v1.delete_namespaced_service(name, ns)
            logger.info("Deleted service: %s", name)
        except Exception:
            pass
        server.status = MCPServerStatus.REMOVED
        return server

    async def get_pod_status(self, server: MCPServer) -> dict[str, str]:
        """Get pod status for an MCP server."""
        import asyncio

        return await asyncio.get_event_loop().run_in_executor(
            None, self._get_pod_status_sync, server
        )

    def _get_pod_status_sync(self, server: MCPServer) -> dict[str, str]:
        self._ensure_client()
        try:
            pods = self._core_v1.list_namespaced_pod(
                self._namespace,
                label_selector=f"app={server.k8s_name}",
            )
            if pods.items:
                pod = pods.items[0]
                server.pod_name = pod.metadata.name
                phase = pod.status.phase
                return {
                    "pod": pod.metadata.name,
                    "phase": phase,
                    "ready": str(all(c.ready for c in (pod.status.container_statuses or []))),
                    "restarts": str(
                        sum(c.restart_count for c in (pod.status.container_statuses or []))
                    ),
                }
            return {"pod": "", "phase": "NotFound", "ready": "false", "restarts": "0"}
        except Exception as e:
            return {"pod": "", "phase": "Error", "ready": "false", "error": str(e)}
