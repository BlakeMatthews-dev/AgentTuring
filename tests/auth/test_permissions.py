"""Tests for config-driven RBAC permission table."""

from stronghold.types.auth import AuthContext, PermissionTable


class TestPermissionTable:
    def test_admin_wildcard(self) -> None:
        table = PermissionTable.from_config({"admin": ["*"]})
        ctx = AuthContext(user_id="u", username="u", roles=frozenset({"admin"}))
        assert ctx.can_use_tool("anything", table)

    def test_engineer_allowed_tool(self) -> None:
        table = PermissionTable.from_config(
            {
                "engineer": ["web_search", "file_ops"],
            }
        )
        ctx = AuthContext(user_id="u", username="u", roles=frozenset({"engineer"}))
        assert ctx.can_use_tool("web_search", table)

    def test_engineer_denied_tool(self) -> None:
        table = PermissionTable.from_config(
            {
                "engineer": ["web_search", "file_ops"],
            }
        )
        ctx = AuthContext(user_id="u", username="u", roles=frozenset({"engineer"}))
        assert not ctx.can_use_tool("ha_control", table)

    def test_viewer_limited(self) -> None:
        table = PermissionTable.from_config({"viewer": ["web_search"]})
        ctx = AuthContext(user_id="u", username="u", roles=frozenset({"viewer"}))
        assert ctx.can_use_tool("web_search", table)
        assert not ctx.can_use_tool("shell", table)

    def test_multiple_roles_union(self) -> None:
        table = PermissionTable.from_config(
            {
                "viewer": ["web_search"],
                "operator": ["ha_control"],
            }
        )
        ctx = AuthContext(
            user_id="u",
            username="u",
            roles=frozenset({"viewer", "operator"}),
        )
        assert ctx.can_use_tool("web_search", table)
        assert ctx.can_use_tool("ha_control", table)

    def test_no_roles_denied(self) -> None:
        table = PermissionTable.from_config({"admin": ["*"]})
        ctx = AuthContext(user_id="u", username="u", roles=frozenset())
        assert not ctx.can_use_tool("anything", table)
