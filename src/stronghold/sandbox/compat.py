"""Sandbox compatibility layer for AKS + vanilla K8s.

Fixes for running sandboxes on clusters with PSA enforcement
(Azure AKS, vanilla k8s) vs. SCC enforcement (OpenShift/OKD).

Key differences:
  - PSA restricted rejects SYS_ADMIN capability (browser sandbox needs it)
  - AKS uses PSA admission, not SCCs
  - Namespace names may differ from default topology
"""

from __future__ import annotations

import os

# MCP namespace is configurable, not hardcoded
MCP_NAMESPACE = os.environ.get("STRONGHOLD_MCP_NAMESPACE", "stronghold-mcp")


def sandbox_endpoint(pod_id: str, port: int = 3000) -> str:
    """Build a DNS endpoint for a sandbox pod, using configurable namespace."""
    return f"http://{pod_id}.{MCP_NAMESPACE}.svc.cluster.local:{port}"


def browser_security_profile_for_platform(platform: str = "") -> dict:
    """Return browser sandbox security overrides based on platform.

    PSA restricted (AKS, vanilla k8s) rejects SYS_ADMIN capability.
    The browser sandbox needs either:
      - SYS_ADMIN on OpenShift (SCC allows it)
      - --no-sandbox Chrome flag on PSA-restricted clusters
      - A baseline or privileged PSA namespace exception

    Args:
        platform: "openshift", "aks", or "" (auto-detect from env)
    """
    if not platform:
        platform = os.environ.get("STRONGHOLD_PLATFORM", "")

    if platform == "openshift":
        return {
            "add_capabilities": ("SYS_ADMIN",),
            "chrome_flags": (),
        }

    # AKS / vanilla k8s: no SYS_ADMIN, use --no-sandbox instead
    return {
        "add_capabilities": (),
        "chrome_flags": ("--no-sandbox", "--disable-setuid-sandbox"),
    }
