"""Tests for static API key authentication."""

import pytest

from stronghold.security.auth_static import StaticKeyAuthProvider
from stronghold.types.auth import SYSTEM_AUTH


class TestStaticKeyAuth:
    @pytest.mark.asyncio
    async def test_correct_key_returns_system_auth(self) -> None:
        provider = StaticKeyAuthProvider(api_key="sk-test")
        ctx = await provider.authenticate("Bearer sk-test")
        assert ctx.user_id == SYSTEM_AUTH.user_id
        assert ctx.auth_method == "api_key"

    @pytest.mark.asyncio
    async def test_wrong_key_raises(self) -> None:
        provider = StaticKeyAuthProvider(api_key="sk-test")
        with pytest.raises(ValueError, match="Invalid"):
            await provider.authenticate("Bearer wrong-key")

    @pytest.mark.asyncio
    async def test_missing_header_raises(self) -> None:
        provider = StaticKeyAuthProvider(api_key="sk-test")
        with pytest.raises(ValueError, match="Missing"):
            await provider.authenticate(None)

    @pytest.mark.asyncio
    async def test_no_bearer_prefix_raises(self) -> None:
        provider = StaticKeyAuthProvider(api_key="sk-test")
        with pytest.raises(ValueError, match="Invalid"):
            await provider.authenticate("sk-test")
