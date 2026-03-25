"""Test OpenWebUI header extraction in auth."""

from __future__ import annotations

import pytest

from stronghold.security.auth_static import StaticKeyAuthProvider, _extract_openwebui_context
from stronghold.types.auth import SYSTEM_AUTH, IdentityKind


class TestOpenWebUIHeaderExtraction:
    def test_extracts_full_context(self) -> None:
        headers = {
            "x-openwebui-user-email": "blake@example.com",
            "x-openwebui-user-name": "Blake",
            "x-openwebui-user-id": "user-123",
            "x-openwebui-user-role": "admin",
        }
        ctx = _extract_openwebui_context(headers)
        assert ctx is not None
        assert ctx.user_id == "user-123"
        assert ctx.username == "Blake"
        assert ctx.org_id == "openwebui"
        assert ctx.kind == IdentityKind.USER
        # Role from headers is NOT trusted — always "user" only
        assert "user" in ctx.roles
        assert "admin" not in ctx.roles

    def test_falls_back_to_email_for_id(self) -> None:
        headers = {"x-openwebui-user-email": "blake@example.com"}
        ctx = _extract_openwebui_context(headers)
        assert ctx is not None
        assert ctx.user_id == "blake@example.com"
        assert ctx.username == "blake@example.com"

    def test_returns_none_without_identity(self) -> None:
        headers = {"x-openwebui-user-role": "admin"}
        ctx = _extract_openwebui_context(headers)
        assert ctx is None

    def test_returns_none_for_empty_headers(self) -> None:
        ctx = _extract_openwebui_context({})
        assert ctx is None

    @pytest.mark.asyncio
    async def test_static_provider_uses_headers(self) -> None:
        provider = StaticKeyAuthProvider(api_key="sk-test")
        ctx = await provider.authenticate(
            "Bearer sk-test",
            headers={
                "x-openwebui-user-email": "user@corp.com",
                "x-openwebui-user-id": "u-456",
            },
        )
        assert ctx.user_id == "u-456"
        assert ctx.org_id == "openwebui"

    @pytest.mark.asyncio
    async def test_static_provider_returns_system_without_headers(self) -> None:
        provider = StaticKeyAuthProvider(api_key="sk-test")
        ctx = await provider.authenticate("Bearer sk-test")
        assert ctx == SYSTEM_AUTH

    @pytest.mark.asyncio
    async def test_static_provider_returns_system_with_empty_headers(self) -> None:
        provider = StaticKeyAuthProvider(api_key="sk-test")
        ctx = await provider.authenticate("Bearer sk-test", headers={})
        assert ctx == SYSTEM_AUTH


class TestCompositeAuthProvider:
    @pytest.mark.asyncio
    async def test_first_success_wins(self) -> None:
        from stronghold.security.auth_composite import CompositeAuthProvider

        p1 = StaticKeyAuthProvider(api_key="key-1")
        p2 = StaticKeyAuthProvider(api_key="key-2")
        composite = CompositeAuthProvider([p1, p2])

        ctx = await composite.authenticate("Bearer key-1")
        assert ctx == SYSTEM_AUTH  # p1 succeeds

    @pytest.mark.asyncio
    async def test_falls_back_to_second(self) -> None:
        from stronghold.security.auth_composite import CompositeAuthProvider

        p1 = StaticKeyAuthProvider(api_key="key-1")
        p2 = StaticKeyAuthProvider(api_key="key-2")
        composite = CompositeAuthProvider([p1, p2])

        ctx = await composite.authenticate("Bearer key-2")
        assert ctx == SYSTEM_AUTH  # p1 fails, p2 succeeds

    @pytest.mark.asyncio
    async def test_all_fail_raises(self) -> None:
        from stronghold.security.auth_composite import CompositeAuthProvider

        p1 = StaticKeyAuthProvider(api_key="key-1")
        p2 = StaticKeyAuthProvider(api_key="key-2")
        composite = CompositeAuthProvider([p1, p2])

        with pytest.raises(ValueError, match="Authentication failed"):
            await composite.authenticate("Bearer wrong-key")
