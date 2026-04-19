"""Tests for ToolCatalog (ADR-K8S-021)."""

from __future__ import annotations

from stronghold.tools.catalog import CatalogEntry, ToolCatalog
from stronghold.tools.decorator import get_decorated_tools, tool
from stronghold.types.tool import ToolDefinition


def _entry(
    name: str,
    scope: str = "builtin",
    tenant_id: str = "",
    user_id: str = "",
    version: str = "1.0.0",
) -> CatalogEntry:
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


# ---------------------------------------------------------------------------
# Coverage tests for ToolCatalog — lines 64, 97-110
# ---------------------------------------------------------------------------


def test_resolve_skips_non_matching_tool_names() -> None:
    """Line 64: entry.definition.name != tool_name -> continue."""
    cat = ToolCatalog()
    cat.register(_entry("alpha"))
    cat.register(_entry("beta"))
    result = cat.resolve("alpha")
    assert result is not None
    assert result.definition.name == "alpha"
    # beta should not interfere
    result_beta = cat.resolve("beta")
    assert result_beta is not None
    assert result_beta.definition.name == "beta"


def test_resolve_returns_none_when_only_invisible_matches() -> None:
    """Line 64 + visibility: all matching entries invisible -> None."""
    cat = ToolCatalog()
    cat.register(_entry("secret", scope="user", user_id="alice"))
    # Resolve as a different user
    result = cat.resolve("secret", user_id="bob")
    assert result is None


def test_list_tools_skips_invisible_user_entry() -> None:
    """Line 97-98: _is_visible returns False for wrong user -> skip."""
    cat = ToolCatalog()
    cat.register(_entry("my_tool", scope="user", user_id="alice"))
    cat.register(_entry("shared", scope="builtin"))
    tools = cat.list_tools(user_id="bob")
    names = [t.definition.name for t in tools]
    assert "my_tool" not in names
    assert "shared" in names


def test_load_plugins_no_entry_point(monkeypatch: object) -> None:
    """Lines 97-102: load_plugins with no stronghold.tools entry-points."""
    from unittest.mock import patch

    cat = ToolCatalog()
    # Mock entry_points to return empty for our group
    with patch("stronghold.tools.catalog.entry_points", return_value={}):
        cat.load_plugins()  # should not raise
    assert len(cat._entries) == 0


def test_load_plugins_with_catalog_entry(monkeypatch: object) -> None:
    """Lines 103-108: plugin with _catalog_entry attribute gets registered."""
    from unittest.mock import MagicMock, patch

    cat = ToolCatalog()
    mock_ep = MagicMock()
    mock_ep.name = "my_plugin_tool"

    # Create a callable with _catalog_entry
    mock_tool_fn = MagicMock()
    mock_tool_fn._catalog_entry = _entry("plugin_tool", version="3.0.0")
    mock_ep.load.return_value = mock_tool_fn

    with patch(
        "stronghold.tools.catalog.entry_points", return_value={"stronghold.tools": [mock_ep]}
    ):
        cat.load_plugins()

    assert len(cat._entries) == 1
    assert cat._entries[0].definition.name == "plugin_tool"
    assert cat._entries[0].version == "3.0.0"


def test_load_plugins_without_catalog_entry_attr() -> None:
    """Lines 106-107: plugin loaded but no _catalog_entry -> skip."""
    from unittest.mock import MagicMock, patch

    cat = ToolCatalog()
    mock_ep = MagicMock()
    mock_ep.name = "bare_plugin"
    mock_ep.load.return_value = lambda: None  # no _catalog_entry

    with patch(
        "stronghold.tools.catalog.entry_points", return_value={"stronghold.tools": [mock_ep]}
    ):
        cat.load_plugins()

    assert len(cat._entries) == 0


def test_load_plugins_handles_exception() -> None:
    """Lines 109-110: exception during ep.load -> warning, continue."""
    from unittest.mock import MagicMock, patch

    cat = ToolCatalog()
    mock_ep = MagicMock()
    mock_ep.name = "broken_plugin"
    mock_ep.load.side_effect = ImportError("module not found")

    with patch(
        "stronghold.tools.catalog.entry_points", return_value={"stronghold.tools": [mock_ep]}
    ):
        cat.load_plugins()  # should not raise

    assert len(cat._entries) == 0


def test_load_plugins_select_api() -> None:
    """Lines 98-101: non-dict entry_points (SelectableGroups API)."""
    from unittest.mock import MagicMock, patch

    cat = ToolCatalog()
    mock_tool_fn = MagicMock()
    mock_tool_fn._catalog_entry = _entry("select_tool")

    mock_ep = MagicMock()
    mock_ep.name = "select_plugin"
    mock_ep.load.return_value = mock_tool_fn

    # Simulate SelectableGroups (not a dict, has .select method)
    mock_eps = MagicMock()
    mock_eps.__class__ = type("SelectableGroups", (), {})  # not dict
    mock_eps.select.return_value = [mock_ep]
    # Make isinstance(eps, dict) return False
    del mock_eps.__getitem__

    with patch("stronghold.tools.catalog.entry_points", return_value=mock_eps):
        cat.load_plugins()

    assert len(cat._entries) == 1
    assert cat._entries[0].definition.name == "select_tool"
