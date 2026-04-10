"""Tests for sandbox AKS/vanilla-k8s compatibility."""

from __future__ import annotations

import os

from stronghold.sandbox.compat import (
    MCP_NAMESPACE,
    browser_security_profile_for_platform,
    sandbox_endpoint,
)


def test_sandbox_endpoint_default_namespace() -> None:
    endpoint = sandbox_endpoint("sandbox-shell-abc123")
    assert "stronghold-mcp" in endpoint
    assert "sandbox-shell-abc123" in endpoint
    assert endpoint.endswith(":3000")


def test_sandbox_endpoint_custom_namespace(monkeypatch: object) -> None:
    os.environ["STRONGHOLD_MCP_NAMESPACE"] = "custom-ns"
    try:
        # Re-import to pick up env change
        from importlib import reload
        import stronghold.sandbox.compat as compat_mod
        reload(compat_mod)
        endpoint = compat_mod.sandbox_endpoint("pod-1")
        assert "custom-ns" in endpoint
    finally:
        os.environ.pop("STRONGHOLD_MCP_NAMESPACE", None)
        reload(compat_mod)


def test_browser_profile_openshift() -> None:
    profile = browser_security_profile_for_platform("openshift")
    assert "SYS_ADMIN" in profile["add_capabilities"]
    assert not profile["chrome_flags"]


def test_browser_profile_aks() -> None:
    profile = browser_security_profile_for_platform("aks")
    assert not profile["add_capabilities"]
    assert "--no-sandbox" in profile["chrome_flags"]


def test_browser_profile_vanilla_k8s() -> None:
    """Empty platform = vanilla k8s = no SYS_ADMIN."""
    profile = browser_security_profile_for_platform("")
    assert not profile["add_capabilities"]
    assert "--no-sandbox" in profile["chrome_flags"]


def test_browser_profile_auto_detect(monkeypatch: object) -> None:
    os.environ["STRONGHOLD_PLATFORM"] = "aks"
    try:
        profile = browser_security_profile_for_platform()  # no arg = auto
        assert not profile["add_capabilities"]
    finally:
        os.environ.pop("STRONGHOLD_PLATFORM", None)
