"""MCP deployer client protocol — sidecar pod boundary for tool deployment.

Issue #381 ('Remove Kubeconfig with Cluster-Admin') replaces the in-process
MCP deployer that mounted ``.kubeconfig-docker`` with cluster-admin
credentials. The replacement is a separate pod with a namespace-scoped
Role talking to the main Stronghold service over gRPC.

This module defines the seam ONLY. No gRPC client. No K8s client. No
deployer state. Just the typed interface that both the gRPC stub (#742)
and the in-test fake (#744) implement, so callers can be wired through
the DI container without any concrete deployer in scope.

Three operations cover the deployer's whole surface for v0.9:

- ``deploy_tool_mcp(tool_name, image)`` — create a Deployment for an MCP
  server in the deployer's namespace.
- ``stop_tool_mcp(deployment_name)`` — tear it down.
- ``health()`` — liveness probe so the router can fail fast on a
  deployer outage.

Anything richer (configmap injection, scaling, log streaming) is a v1
extension and will land as additional protocol methods, not a parallel
module.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class McpDeployerClient(Protocol):
    """Stable abstraction over the MCP deployer sidecar.

    Implementations are expected to be safe to call concurrently. The
    contract intentionally hides every transport detail (gRPC, mTLS,
    cert paths, ServiceAccount tokens) — callers MUST NOT inspect the
    underlying client.
    """

    async def deploy_tool_mcp(self, tool_name: str, image: str) -> str:
        """Create a Deployment for a tool MCP server.

        Args:
            tool_name: Logical tool name (e.g. ``"github"``,
                ``"dev-tools"``). Used to derive the deployment name and
                the Service the Stronghold API will talk to.
            image: Container image reference, including tag and digest
                if available. The deployer is expected to refuse to
                deploy an image without an explicit tag — never ``latest``.

        Returns:
            The Deployment name the deployer assigned (the caller may
            need this to stop the MCP later).

        Raises:
            ValueError: ``tool_name`` is empty, ``image`` is empty, or
                ``image`` lacks a tag.
            PermissionError: The deployer's namespace-scoped Role does
                not authorize this operation. ADR-K8S-002 says the
                deployer cannot have ClusterRole — so this can fire if
                the caller is asking for a cross-namespace deploy.
            RuntimeError: The deployer is unreachable or returned an
                error the caller cannot recover from. Distinct from
                ``PermissionError`` so callers can retry transient faults
                without retrying authorization failures.
        """
        ...

    async def stop_tool_mcp(self, deployment_name: str) -> None:
        """Stop and remove a tool MCP deployment.

        Idempotent: stopping a deployment that does not exist is a
        no-op, NOT an error. This makes the cleanup path safe to call
        from finalizers and crash-recovery code.

        Args:
            deployment_name: The name returned by a prior
                ``deploy_tool_mcp`` call.

        Raises:
            ValueError: ``deployment_name`` is empty.
            PermissionError: The deployer's Role does not authorize
                deletes in the relevant namespace.
            RuntimeError: The deployer is unreachable.
        """
        ...

    async def health(self) -> bool:
        """Return ``True`` if the deployer is reachable and healthy.

        Implementations MUST NOT raise on a transient failure — return
        ``False`` instead so the caller's circuit-breaker logic can react
        without an exception path.
        """
        ...
