"""Tests for ToolCatalog (ADR-K8S-021)."""

from __future__ import annotations

from stronghold.tools.catalog import CatalogEntry, ToolCatalog
from stronghold.tools.decorator import get_decorated_tools, tool
from stronghold.types.tool import ToolDefinition


def _entry(name: str, scope: str = "builtin", tenant_id: str = "", user_id: str = "", version: str = "1.0.0") -> CatalogEntry:
    return CatalogEntry(
        definition=ToolDefinition(name=name),
        version=version,
        scope=scope,
        tenant_id=tenant_id,
        user_id=user_id,
    )


def test_register_and_resolve_builtin() -> None:
    cat = ToolCatalog()
    cat.register(_entry("web_search"))
    result = cat.resolve("web_search")
    assert result is not None
    assert result.definition.name == "web_search"


def test_resolve_unknown_returns_none() -> None:
    cat = ToolCatalog()
    assert cat.resolve("nonexistent") is None


def test_tenant_override_shadows_builtin() -> None:
    cat = ToolCatalog()
    cat.register(_entry("shell", scope="builtin"))
    cat.register(_entry("shell", scope="tenant", tenant_id="acme"))
    result = cat.resolve("shell", tenant_id="acme")
    assert result is not None
    assert result.scope == "tenant"
    assert result.tenant_id == "acme"


def test_user_override_shadows_tenant() -> None:
    cat = ToolCatalog()
    cat.register(_entry("shell", scope="builtin"))
    cat.register(_entry("shell", scope="tenant", tenant_id="acme"))
    cat.register(_entry("shell", scope="user", tenant_id="acme", user_id="alice"))
    result = cat.resolve("shell", tenant_id="acme", user_id="alice")
    assert result is not None
    assert result.scope == "user"
    assert result.user_id == "alice"


def test_list_tools_cascaded_dedup() -> None:
    cat = ToolCatalog()
    cat.register(_entry("web_search", scope="builtin"))
    cat.register(_entry("shell", scope="builtin"))
    cat.register(_entry("shell", scope="tenant", tenant_id="acme"))
    tools = cat.list_tools(tenant_id="acme")
    names = [t.definition.name for t in tools]
    assert sorted(names) == ["shell", "web_search"]
    shell_entry = next(t for t in tools if t.definition.name == "shell")
    assert shell_entry.scope == "tenant"


def test_list_tools_user_scope() -> None:
    cat = ToolCatalog()
    cat.register(_entry("shell", scope="builtin"))
    cat.register(_entry("shell", scope="user", user_id="alice"))
    tools = cat.list_tools(user_id="alice")
    assert len(tools) == 1
    assert tools[0].scope == "user"


def test_semver_stored() -> None:
    cat = ToolCatalog()
    cat.register(_entry("my_tool", version="2.1.0"))
    result = cat.resolve("my_tool")
    assert result is not None
    assert result.version == "2.1.0"


def test_tenant_tool_not_visible_to_other_tenant() -> None:
    cat = ToolCatalog()
    cat.register(_entry("secret_tool", scope="tenant", tenant_id="acme"))
    result = cat.resolve("secret_tool", tenant_id="other-corp")
    assert result is None


def test_tool_decorator_registers() -> None:
    initial_count = len(get_decorated_tools())

    @tool("test_ping", version="1.0.0", description="Test ping tool")
    def ping(target: str) -> str:
        return f"pong {target}"

    tools = get_decorated_tools()
    assert len(tools) == initial_count + 1
    latest = tools[-1]
    assert latest.definition.name == "test_ping"
    assert latest.version == "1.0.0"
    assert "target" in latest.definition.parameters.get("properties", {})


def test_tool_decorator_infers_types() -> None:
    @tool("typed_tool")
    def typed(count: int, rate: float, active: bool) -> None:
        pass

    entry = typed._catalog_entry
    props = entry.definition.parameters["properties"]
    assert props["count"]["type"] == "integer"
    assert props["rate"]["type"] == "number"
    assert props["active"]["type"] == "boolean"


def test_resolve_falls_back_to_builtin_when_tenant_mismatch() -> None:
    cat = ToolCatalog()
    cat.register(_entry("shell", scope="builtin", version="1.0.0"))
    cat.register(_entry("shell", scope="tenant", tenant_id="acme", version="2.0.0"))
    result = cat.resolve("shell", tenant_id="other-corp")
    assert result is not None
    assert result.scope == "builtin"
    assert result.version == "1.0.0"


def test_list_tools_no_args_returns_builtins_only() -> None:
    cat = ToolCatalog()
    cat.register(_entry("builtin_tool", scope="builtin"))
    cat.register(_entry("tenant_tool", scope="tenant", tenant_id="acme"))
    tools = cat.list_tools()
    assert len(tools) == 1
    assert tools[0].definition.name == "builtin_tool"


# ── Coverage: load_plugins ──────────────────────────────────────────


def test_load_plugins_no_plugins_installed() -> None:
    """load_plugins with no entry points should not crash."""
    cat = ToolCatalog()
    before = len(cat._entries)
    cat.load_plugins()  # No stronghold.tools entry points in test env
    after = len(cat._entries)
    # May or may not find plugins, but must not crash
    assert after >= before


def test_load_plugins_handles_broken_plugin(monkeypatch) -> None:
    """A plugin that raises on load should be logged, not fatal."""
    from unittest.mock import MagicMock

    class BrokenEP:
        name = "broken"
        def load(self):
            raise RuntimeError("plugin broken")

    class FakeEPs:
        def select(self, group):
            return [BrokenEP()]

    monkeypatch.setattr(
        "stronghold.tools.catalog.entry_points", lambda: FakeEPs(),
    )
    cat = ToolCatalog()
    cat.load_plugins()  # Should not raise


def test_load_plugins_registers_catalog_entry() -> None:
    """Plugins with _catalog_entry attribute get registered."""
    from unittest.mock import MagicMock
    import pytest

    test_entry = CatalogEntry(
        definition=ToolDefinition(name="plugin_tool"),
        version="1.0.0",
        scope="builtin",
    )

    class FakeFn:
        _catalog_entry = test_entry

    class FakeEP:
        name = "my-plugin"
        def load(self):
            return FakeFn

    class FakeEPs:
        def select(self, group):
            return [FakeEP()]

    cat = ToolCatalog()
    from unittest.mock import patch
    with patch("stronghold.tools.catalog.entry_points", return_value=FakeEPs()):
        cat.load_plugins()

    result = cat.resolve("plugin_tool")
    assert result is not None
    assert result.version == "1.0.0"
