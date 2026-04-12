"""Tests for SandboxPodCatalog (ADR-K8S-025/026)."""

from __future__ import annotations

from stronghold.sandbox.catalog import (
    BUILTIN_TEMPLATES,
    SandboxLifecycle,
    SandboxPodCatalog,
    SandboxTemplate,
    SandboxType,
)


def test_builtin_templates_registered() -> None:
    cat = SandboxPodCatalog()
    templates = cat.list_templates()
    assert len(templates) == 6
    names = {t.name for t in templates}
    assert "sandbox.shell" in names
    assert "sandbox.python" in names
    assert "sandbox.browser" in names
    assert "sandbox.filesystem" in names
    assert "sandbox.k8s" in names
    assert "sandbox.network" in names


def test_get_template() -> None:
    cat = SandboxPodCatalog()
    tmpl = cat.get("sandbox.shell")
    assert tmpl is not None
    assert tmpl.sandbox_type == SandboxType.SHELL
    assert "bash" in tmpl.allowed_binaries


def test_get_unknown_template() -> None:
    assert SandboxPodCatalog().get("sandbox.nonexistent") is None


def test_list_by_type() -> None:
    cat = SandboxPodCatalog()
    shells = cat.list_by_type(SandboxType.SHELL)
    assert len(shells) == 1
    assert shells[0].name == "sandbox.shell"


def test_shell_template_properties() -> None:
    cat = SandboxPodCatalog()
    shell = cat.get("sandbox.shell")
    assert shell is not None
    assert shell.lifecycle == SandboxLifecycle.PER_CALL
    assert shell.network_egress is False
    assert shell.security.read_only_root_filesystem is True
    assert shell.mcp_tool_name == "shell.exec"


def test_python_template_properties() -> None:
    cat = SandboxPodCatalog()
    py = cat.get("sandbox.python")
    assert py is not None
    assert py.resources.memory_limit == "512Mi"
    assert py.network_egress is False
    assert py.mcp_tool_name == "python.exec"


def test_browser_template_properties() -> None:
    cat = SandboxPodCatalog()
    browser = cat.get("sandbox.browser")
    assert browser is not None
    assert browser.lifecycle == SandboxLifecycle.PER_SESSION
    assert browser.network_egress is True
    assert "SYS_ADMIN" in browser.security.add_capabilities
    assert browser.resources.memory_limit == "2Gi"


def test_filesystem_template_properties() -> None:
    cat = SandboxPodCatalog()
    fs = cat.get("sandbox.filesystem")
    assert fs is not None
    assert fs.network_egress is False
    assert "/workspace" in fs.writable_paths


async def test_spawn_and_reap() -> None:
    cat = SandboxPodCatalog()
    result = await cat.spawn("sandbox.shell", tenant_id="acme", user_id="alice")
    assert result is not None
    assert result["status"] == "running"
    assert result["tenant_id"] == "acme"
    pod_id = result["pod_id"]

    active = cat.list_active("acme")
    assert len(active) == 1

    assert await cat.reap(pod_id) is True
    assert cat.list_active("acme") == []


async def test_spawn_unknown_template() -> None:
    cat = SandboxPodCatalog()
    result = await cat.spawn("sandbox.nonexistent", tenant_id="acme")
    assert result is None


async def test_reap_unknown_pod() -> None:
    cat = SandboxPodCatalog()
    assert await cat.reap("nonexistent-pod") is False


async def test_list_active_filtered_by_tenant() -> None:
    cat = SandboxPodCatalog()
    await cat.spawn("sandbox.shell", tenant_id="acme")
    await cat.spawn("sandbox.python", tenant_id="evil")
    assert len(cat.list_active("acme")) == 1
    assert len(cat.list_active("evil")) == 1
    assert len(cat.list_active()) == 2


def test_register_custom_template() -> None:
    cat = SandboxPodCatalog()
    custom = SandboxTemplate(
        name="sandbox.custom",
        sandbox_type=SandboxType.SHELL,
        image="my-org/custom-sandbox:v1",
        description="Custom sandbox",
    )
    cat.register(custom)
    assert cat.get("sandbox.custom") is not None
    assert len(cat.list_templates()) == 7


def test_all_builtins_have_security_profiles() -> None:
    for tmpl in BUILTIN_TEMPLATES:
        assert tmpl.security is not None
        assert tmpl.security.run_as_non_root is True
        assert "ALL" in tmpl.security.drop_capabilities


def test_all_builtins_have_mcp_tool_name() -> None:
    for tmpl in BUILTIN_TEMPLATES:
        assert tmpl.mcp_tool_name, f"{tmpl.name} missing mcp_tool_name"
