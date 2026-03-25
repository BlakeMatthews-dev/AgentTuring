"""MCP server data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class MCPServerStatus(StrEnum):
    """Lifecycle status of a managed MCP server."""

    PENDING = "pending"  # Registered, not yet deployed
    DEPLOYING = "deploying"  # K8s resources being created
    RUNNING = "running"  # Pod healthy, tools discovered
    STOPPED = "stopped"  # Deployment scaled to 0
    FAILED = "failed"  # Pod crash / health check failure
    REMOVED = "removed"  # K8s resources deleted


class MCPSourceType(StrEnum):
    """How the MCP server is hosted."""

    MANAGED = "managed"  # Stronghold deploys + manages in K8s
    REMOTE = "remote"  # External, customer-hosted (Stronghold connects)


class MCPTransport(StrEnum):
    """MCP wire protocol."""

    SSE = "sse"  # Server-Sent Events over HTTP (K8s-friendly)
    STDIO = "stdio"  # Standard I/O (local only, not for K8s)


@dataclass
class MCPServerSpec:
    """Specification for deploying an MCP server."""

    name: str
    image: str  # Container image (e.g., ghcr.io/modelcontextprotocol/server-github)
    transport: MCPTransport = MCPTransport.SSE
    port: int = 3000
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)  # secretKeyRef mappings
    resources: MCPResourceLimits | None = None
    description: str = ""
    source_url: str = ""
    author: str = ""
    trust_tier: str = "t3"  # Community default


@dataclass
class MCPResourceLimits:
    """K8s resource limits for an MCP server pod."""

    cpu_limit: str = "500m"
    memory_limit: str = "256Mi"
    cpu_request: str = "100m"
    memory_request: str = "64Mi"


@dataclass
class MCPDiscoveredTool:
    """A tool discovered from an MCP server."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})


@dataclass
class MCPServer:
    """A registered MCP server with runtime state."""

    spec: MCPServerSpec
    source_type: MCPSourceType = MCPSourceType.MANAGED
    status: MCPServerStatus = MCPServerStatus.PENDING
    endpoint: str = ""  # Internal K8s service URL (e.g., http://github-mcp.stronghold.svc:3000)
    tools: list[MCPDiscoveredTool] = field(default_factory=list)
    org_id: str = ""
    error: str = ""
    pod_name: str = ""
    namespace: str = "stronghold"

    @property
    def k8s_name(self) -> str:
        """K8s-safe name (lowercase, hyphens only)."""
        return f"mcp-{self.spec.name}".lower().replace("_", "-")[:63]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API responses."""
        return {
            "name": self.spec.name,
            "image": self.spec.image,
            "source_type": self.source_type.value,
            "status": self.status.value,
            "endpoint": self.endpoint,
            "transport": self.spec.transport.value,
            "port": self.spec.port,
            "trust_tier": self.spec.trust_tier,
            "description": self.spec.description,
            "author": self.spec.author,
            "org_id": self.org_id,
            "error": self.error,
            "tools": [
                {"name": t.name, "description": t.description, "parameters": t.parameters}
                for t in self.tools
            ],
            "tool_count": len(self.tools),
        }
