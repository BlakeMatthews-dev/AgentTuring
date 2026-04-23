"""Sandbox templates for isolated agent execution.

Provides template configurations for Python, JavaScript, Browser, and Shell
sandbox environments with security rules.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("stronghold.sandbox.templates")


@dataclass
class SandboxTemplate:
    """Sandbox template configuration."""

    name: str
    runtime: str
    description: str
    network_access: bool = False
    filesystem_access: str = "none"
    host_access: bool = False
    memory_limit: str = "256Mi"
    cpu_limit: str = "0.5"
    security_rules: list[str] = field(default_factory=list)


class SandboxTemplates:
    """Registry of sandbox templates."""

    def __init__(self) -> None:
        """Initialize Sandbox Templates."""
        self._templates: dict[str, SandboxTemplate] = {}
        self._register_default_templates()

    def _register_default_templates(self) -> None:
        """Register default sandbox templates."""
        self.register_template(
            SandboxTemplate(
                name="python-isolated",
                runtime="python:3.13",
                description=(
                    "Isolated Python execution with no network access. "
                    "Suitable for code testing and analysis."
                ),
                network_access=False,
                filesystem_access="none",
                host_access=False,
                memory_limit="256Mi",
                cpu_limit="0.5",
                security_rules=[
                    "No network access",
                    "No filesystem access",
                    "No host access",
                ],
            )
        )

        self.register_template(
            SandboxTemplate(
                name="javascript-isolated",
                runtime="node:20",
                description=(
                    "Isolated Node.js execution with Deno. "
                    "No filesystem or network access by default."
                ),
                network_access=False,
                filesystem_access="none",
                host_access=False,
                memory_limit="256Mi",
                cpu_limit="0.5",
                security_rules=[
                    "No network access by default",
                    "No filesystem access by default",
                    "Deno runtime enforces security",
                ],
            )
        )

        self.register_template(
            SandboxTemplate(
                name="browser-playwright",
                runtime="node:20",
                description=(
                    "Browser automation with Playwright in isolated container. "
                    "No direct filesystem access to host."
                ),
                network_access=False,
                filesystem_access="read-only",
                host_access=False,
                memory_limit="512Mi",
                cpu_limit="1.0",
                security_rules=[
                    "Read-only filesystem access to container",
                    "No network access to host",
                    "Playwright enforces sandbox",
                ],
            )
        )

        self.register_template(
            SandboxTemplate(
                name="shell-restricted",
                runtime="bash:5",
                description=(
                    "Restricted shell with no write access to / or sudo. "
                    "Suitable for command execution and testing."
                ),
                network_access=False,
                filesystem_access="read-only",
                host_access=False,
                memory_limit="128Mi",
                cpu_limit="0.5",
                security_rules=[
                    "No write access to /",
                    "No sudo access",
                    "Read-only filesystem access",
                ],
            )
        )

    def register_template(self, template: SandboxTemplate) -> None:
        """Register a custom sandbox template.

        Args:
            template: Template configuration
        """
        self._templates[template.name] = template
        logger.info("Sandbox template registered: %s", template.name)

    def get_template(self, name: str) -> SandboxTemplate | None:
        """Get sandbox template by name.

        Args:
            name: Template name

        Returns:
            SandboxTemplate or None
        """
        return self._templates.get(name)

    def list_templates(self) -> list[SandboxTemplate]:
        """List all registered templates.

        Returns:
            List of all templates
        """
        return list(self._templates.values())

    def list_by_runtime(self, runtime: str) -> list[SandboxTemplate]:
        """List templates by runtime.

        Args:
            runtime: Runtime type (python, node, bash)

        Returns:
            List of templates with matching runtime
        """
        return [t for t in self.list_templates() if t.runtime == runtime]

    def get_security_rules_for_template(self, name: str) -> list[str]:
        """Get security rules for a template.

        Args:
            name: Template name

        Returns:
            List of security rules
        """
        template = self.get_template(name)
        return template.security_rules if template else []

    def validate_template(self, template: SandboxTemplate) -> bool:
        """Validate sandbox template configuration.

        Args:
            template: Template to validate

        Returns:
            True if template is valid, False otherwise
        """
        if not template.network_access and template.filesystem_access in ["none", "read-only"]:
            return False

        if template.host_access:
            return False

        try:
            int(template.memory_limit.rstrip("Mi"))
        except ValueError:
            return False

        try:
            float(template.cpu_limit)
        except ValueError:
            return False

        return True
