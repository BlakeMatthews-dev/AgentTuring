"""MCP Deployer integration — spawns sandbox pods via K8s API.

ADR-K8S-025/026: mcp-deployer creates pods from sandbox catalog templates,
waits for ready, returns MCP endpoint. Reaps on lifecycle expiry.

In production, mcp-deployer runs as a sidecar with namespace-scoped RBAC
(stronghold-mcp only). This module is the client that talks to it.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger("stronghold.sandbox.deployer")

# mcp-deployer sidecar endpoint (Unix socket in prod, HTTP in dev)
_DEPLOYER_URL = os.environ.get(
    "MCP_DEPLOYER_URL", "http://localhost:8300",
)


class MCPDeployerClient:
    """Client for the mcp-deployer sidecar.

    In production, mcp-deployer runs as a sidecar container in the
    stronghold-api pod, communicating over localhost. It has namespace-scoped
    RBAC to create/delete pods in stronghold-mcp only.
    """

    def __init__(self, base_url: str = "") -> None:
        self._base_url = base_url or _DEPLOYER_URL
        self._client = httpx.AsyncClient(
            base_url=self._base_url, timeout=30.0,
        )

    async def spawn(
        self,
        template_name: str,
        tenant_id: str,
        user_id: str = "",
        session_id: str = "",
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Request mcp-deployer to spawn a sandbox pod.

        Returns pod metadata including the MCP endpoint URL.
        """
        resp = await self._client.post(
            "/spawn",
            json={
                "template": template_name,
                "tenant_id": tenant_id,
                "user_id": user_id,
                "session_id": session_id,
                "env": env_overrides or {},
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def reap(self, pod_id: str) -> bool:
        """Request mcp-deployer to reap (delete) a sandbox pod."""
        resp = await self._client.post(
            "/reap",
            json={"pod_id": pod_id},
        )
        if resp.status_code == 404:
            return False
        resp.raise_for_status()
        return True

    async def status(self, pod_id: str) -> dict[str, Any]:
        """Get status of a sandbox pod."""
        resp = await self._client.get(f"/status/{pod_id}")
        resp.raise_for_status()
        return resp.json()

    async def list_active(self, tenant_id: str = "") -> list[dict[str, Any]]:
        """List active sandbox pods, optionally filtered by tenant."""
        params = {}
        if tenant_id:
            params["tenant_id"] = tenant_id
        resp = await self._client.get("/list", params=params)
        resp.raise_for_status()
        return resp.json().get("pods", [])

    async def health(self) -> bool:
        """Check if mcp-deployer is healthy."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self._client.aclose()


class FakeMCPDeployerClient:
    """In-memory fake for testing without a real mcp-deployer sidecar."""

    def __init__(self) -> None:
        self._pods: dict[str, dict[str, Any]] = {}
        self._counter = 0

    async def spawn(
        self,
        template_name: str,
        tenant_id: str,
        user_id: str = "",
        session_id: str = "",
        env_overrides: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self._counter += 1
        pod_id = f"sandbox-{self._counter}"
        mcp_ns = os.environ.get("STRONGHOLD_MCP_NAMESPACE", "stronghold-mcp")
        pod = {
            "pod_id": pod_id,
            "template": template_name,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "status": "running",
            "endpoint": f"http://{pod_id}.{mcp_ns}.svc.cluster.local:3000",
        }
        self._pods[pod_id] = pod
        return pod

    async def reap(self, pod_id: str) -> bool:
        return self._pods.pop(pod_id, None) is not None

    async def status(self, pod_id: str) -> dict[str, Any]:
        pod = self._pods.get(pod_id)
        if not pod:
            return {"pod_id": pod_id, "status": "not_found"}
        return pod

    async def list_active(self, tenant_id: str = "") -> list[dict[str, Any]]:
        if not tenant_id:
            return list(self._pods.values())
        return [p for p in self._pods.values() if p["tenant_id"] == tenant_id]

    async def health(self) -> bool:
        return True

    async def close(self) -> None:
        pass
