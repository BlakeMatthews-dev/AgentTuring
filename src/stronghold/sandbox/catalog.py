"""Sandbox Pod Catalog — pre-defined pod templates for on-demand execution.

ADR-K8S-025/026: six sandbox types spawnable by mcp-deployer.
Each template defines image, security context, resources, lifecycle,
and allowed capabilities. Templates enforce restricted-v2 SCC.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger("stronghold.sandbox.catalog")


class SandboxLifecycle(StrEnum):
    """When the sandbox pod is reaped."""

    PER_CALL = "per_call"  # Created and destroyed for each invocation
    PER_SESSION = "per_session"  # Lives for the session duration, TTL-reaped


class SandboxType(StrEnum):
    """Pre-defined sandbox template types."""

    SHELL = "shell"
    PYTHON = "python"
    BROWSER = "browser"
    FILESYSTEM = "filesystem"
    K8S = "k8s"
    NETWORK = "network"


@dataclass(frozen=True)
class ResourceLimits:
    """K8s resource limits for a sandbox pod."""

    cpu_request: str = "100m"
    cpu_limit: str = "500m"
    memory_request: str = "64Mi"
    memory_limit: str = "256Mi"


@dataclass(frozen=True)
class SecurityProfile:
    """Security context for a sandbox pod."""

    run_as_non_root: bool = True
    run_as_user: int = 1000
    read_only_root_filesystem: bool = True
    allow_privilege_escalation: bool = False
    drop_capabilities: tuple[str, ...] = ("ALL",)
    add_capabilities: tuple[str, ...] = ()
    seccomp_profile: str = "RuntimeDefault"


@dataclass(frozen=True)
class SandboxTemplate:
    """A pre-defined sandbox pod template."""

    name: str
    sandbox_type: SandboxType
    image: str
    description: str = ""
    lifecycle: SandboxLifecycle = SandboxLifecycle.PER_CALL
    session_ttl_seconds: int = 3600  # Only for per_session
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    security: SecurityProfile = field(default_factory=SecurityProfile)
    allowed_binaries: tuple[str, ...] = ()  # For shell sandbox
    writable_paths: tuple[str, ...] = ("/tmp",)  # nosec B108 — container-isolated
    network_egress: bool = False  # Default: no outbound network
    mcp_tool_name: str = ""  # Tool name exposed by the MCP guest server
    env: dict[str, str] = field(default_factory=dict)


# ── Built-in templates (ADR-K8S-026) ────────────────────────────────

SHELL_TEMPLATE = SandboxTemplate(
    name="sandbox.shell",
    sandbox_type=SandboxType.SHELL,
    image="stronghold/sandbox-shell:latest",
    description="Allow-listed binaries + scoped FS + per-call lifecycle",
    lifecycle=SandboxLifecycle.PER_CALL,
    resources=ResourceLimits(cpu_limit="500m", memory_limit="256Mi"),
    security=SecurityProfile(read_only_root_filesystem=True),
    allowed_binaries=(
        "bash",
        "sh",
        "grep",
        "sed",
        "awk",
        "curl",
        "jq",
        "head",
        "tail",
        "sort",
        "uniq",
        "wc",
        "cat",
        "echo",
        "date",
        "env",
    ),
    writable_paths=("/tmp",),  # nosec B108
    network_egress=False,
    mcp_tool_name="shell.exec",
)

PYTHON_TEMPLATE = SandboxTemplate(
    name="sandbox.python",
    sandbox_type=SandboxType.PYTHON,
    image="stronghold/sandbox-python:latest",
    description="Restricted Python interpreter + memory/CPU caps",
    lifecycle=SandboxLifecycle.PER_CALL,
    resources=ResourceLimits(cpu_limit="1000m", memory_limit="512Mi"),
    security=SecurityProfile(read_only_root_filesystem=True),
    writable_paths=("/tmp",),  # nosec B108
    network_egress=False,
    mcp_tool_name="python.exec",
)

BROWSER_TEMPLATE = SandboxTemplate(
    name="sandbox.browser",
    sandbox_type=SandboxType.BROWSER,
    image="stronghold/sandbox-browser:latest",
    description="Camoufox/Playwright headless + per-session lifecycle",
    lifecycle=SandboxLifecycle.PER_SESSION,
    session_ttl_seconds=1800,
    resources=ResourceLimits(cpu_limit="2000m", memory_limit="2Gi", memory_request="512Mi"),
    security=SecurityProfile(
        read_only_root_filesystem=False,  # Browser needs writable home
        add_capabilities=("SYS_ADMIN",),  # Chrome sandbox
    ),
    writable_paths=("/tmp", "/home/browser"),  # nosec B108
    network_egress=True,  # Browsers need network access
    mcp_tool_name="browser.fetch",
)

FILESYSTEM_TEMPLATE = SandboxTemplate(
    name="sandbox.filesystem",
    sandbox_type=SandboxType.FILESYSTEM,
    image="stronghold/sandbox-filesystem:latest",
    description="Tenant-scoped FS + no network egress",
    lifecycle=SandboxLifecycle.PER_SESSION,
    session_ttl_seconds=3600,
    resources=ResourceLimits(cpu_limit="500m", memory_limit="256Mi"),
    security=SecurityProfile(read_only_root_filesystem=False),
    writable_paths=("/workspace",),
    network_egress=False,
    mcp_tool_name="filesystem.ops",
)

K8S_TEMPLATE = SandboxTemplate(
    name="sandbox.k8s",
    sandbox_type=SandboxType.K8S,
    image="bitnami/kubectl:latest",
    description="Kubectl with scoped RBAC for read-only cluster inspection",
    lifecycle=SandboxLifecycle.PER_CALL,
    resources=ResourceLimits(cpu_limit="250m", memory_limit="128Mi"),
    security=SecurityProfile(read_only_root_filesystem=True),
    network_egress=True,  # Needs K8s API access
    mcp_tool_name="k8s.exec",
)

NETWORK_TEMPLATE = SandboxTemplate(
    name="sandbox.network",
    sandbox_type=SandboxType.NETWORK,
    image="stronghold/sandbox-network:latest",
    description="curl/wget/dig + egress-allowed for API testing",
    lifecycle=SandboxLifecycle.PER_CALL,
    resources=ResourceLimits(cpu_limit="500m", memory_limit="256Mi"),
    security=SecurityProfile(read_only_root_filesystem=True),
    allowed_binaries=("curl", "wget", "dig", "nslookup", "ping", "traceroute", "nc"),
    network_egress=True,
    mcp_tool_name="network.exec",
)

# All built-in templates
BUILTIN_TEMPLATES: tuple[SandboxTemplate, ...] = (
    SHELL_TEMPLATE,
    PYTHON_TEMPLATE,
    BROWSER_TEMPLATE,
    FILESYSTEM_TEMPLATE,
    K8S_TEMPLATE,
    NETWORK_TEMPLATE,
)


class SandboxPodCatalog:
    """Registry of sandbox pod templates with spawn/reap lifecycle."""

    def __init__(self) -> None:
        self._templates: dict[str, SandboxTemplate] = {}
        self._active_pods: dict[str, dict[str, Any]] = {}  # pod_id -> metadata
        # Register built-ins
        for tmpl in BUILTIN_TEMPLATES:
            self._templates[tmpl.name] = tmpl

    def register(self, template: SandboxTemplate) -> None:
        self._templates[template.name] = template

    def get(self, name: str) -> SandboxTemplate | None:
        return self._templates.get(name)

    def list_templates(self) -> list[SandboxTemplate]:
        return sorted(self._templates.values(), key=lambda t: t.name)

    def list_by_type(self, sandbox_type: SandboxType) -> list[SandboxTemplate]:
        return [t for t in self._templates.values() if t.sandbox_type == sandbox_type]

    async def spawn(
        self,
        template_name: str,
        tenant_id: str,
        user_id: str = "",
        session_id: str = "",
    ) -> dict[str, Any] | None:
        """Spawn a sandbox pod from a template. Returns pod metadata."""
        template = self.get(template_name)
        if not template:
            logger.warning("Unknown sandbox template: %s", template_name)
            return None

        import uuid

        pod_id = f"sandbox-{template.sandbox_type}-{uuid.uuid4().hex[:8]}"

        metadata = {
            "pod_id": pod_id,
            "template": template_name,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "session_id": session_id,
            "lifecycle": template.lifecycle.value,
            "status": "running",
            "endpoint": f"http://{pod_id}.stronghold-mcp.svc.cluster.local:3000",
        }
        self._active_pods[pod_id] = metadata
        logger.info(
            "Spawned sandbox pod: %s (template=%s, tenant=%s)", pod_id, template_name, tenant_id
        )
        return metadata

    async def reap(self, pod_id: str) -> bool:
        """Reap (destroy) a sandbox pod. Returns False if not found."""
        pod = self._active_pods.pop(pod_id, None)
        if not pod:
            return False
        logger.info("Reaped sandbox pod: %s", pod_id)
        return True

    def list_active(self, tenant_id: str = "") -> list[dict[str, Any]]:
        """List active sandbox pods, optionally filtered by tenant."""
        if not tenant_id:
            return list(self._active_pods.values())
        return [p for p in self._active_pods.values() if p["tenant_id"] == tenant_id]
