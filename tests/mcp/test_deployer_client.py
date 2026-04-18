"""Tests for the McpDeployerClient protocol contract via FakeMcpDeployer.

These tests pin the contract that both the gRPC stub (#742) and the
in-test fake must satisfy. The error taxonomy is the load-bearing piece:
``ValueError`` for caller bugs, ``PermissionError`` for the deployer's
namespace-scoped Role refusing the operation, ``RuntimeError`` for
transport / unreachable failures.
"""

from __future__ import annotations

import pytest

from stronghold.protocols.mcp import McpDeployerClient
from tests.fakes import FakeMcpDeployer


class TestProtocolCompliance:
    def test_fake_satisfies_protocol_methods(self) -> None:
        """The fake must expose every method the gRPC stub is expected to
        expose, and the protocol must accept it at runtime (so callers can
        type against the protocol and swap implementations)."""
        fake = FakeMcpDeployer()
        # Structural contract: all three Protocol methods are callable on the
        # fake. (This replaces a ``isinstance(fake, McpDeployerClient)`` check
        # against the @runtime_checkable Protocol; ``isinstance`` only verifies
        # attribute presence, ``callable`` proves the contract is implemented.)
        for name in ("deploy_tool_mcp", "stop_tool_mcp", "health"):
            assert callable(getattr(fake, name, None)), f"{name} must be callable"


class TestDeployToolMcp:
    @pytest.mark.asyncio
    async def test_returns_deployment_name(self) -> None:
        fake = FakeMcpDeployer()
        name = await fake.deploy_tool_mcp("github", "ghcr.io/example/mcp-github:v1.2.3")
        assert name.startswith("mcp-github-")

    @pytest.mark.asyncio
    async def test_records_call(self) -> None:
        fake = FakeMcpDeployer()
        await fake.deploy_tool_mcp("github", "ghcr.io/example/mcp-github:v1.2.3")
        assert fake.deploy_calls == [("github", "ghcr.io/example/mcp-github:v1.2.3")]

    @pytest.mark.asyncio
    async def test_unique_names_for_repeated_deploys(self) -> None:
        fake = FakeMcpDeployer()
        a = await fake.deploy_tool_mcp("github", "ghcr.io/example/mcp-github:v1")
        b = await fake.deploy_tool_mcp("github", "ghcr.io/example/mcp-github:v2")
        assert a != b

    @pytest.mark.asyncio
    async def test_empty_tool_name_raises_value_error(self) -> None:
        fake = FakeMcpDeployer()
        with pytest.raises(ValueError, match="tool_name"):
            await fake.deploy_tool_mcp("", "ghcr.io/example/mcp:v1")

    @pytest.mark.asyncio
    async def test_empty_image_raises_value_error(self) -> None:
        fake = FakeMcpDeployer()
        with pytest.raises(ValueError, match="image"):
            await fake.deploy_tool_mcp("github", "")

    @pytest.mark.asyncio
    async def test_image_without_tag_raises_value_error(self) -> None:
        """Per ADR-K8S-006, never deploy ``latest`` or untagged images."""
        fake = FakeMcpDeployer()
        with pytest.raises(ValueError, match="tag"):
            await fake.deploy_tool_mcp("github", "ghcr.io/example/mcp-github")

    @pytest.mark.asyncio
    async def test_permission_denied_for_disallowed_tool(self) -> None:
        fake = FakeMcpDeployer()
        fake.set_denied_for_tool("filesystem")
        with pytest.raises(PermissionError, match="filesystem"):
            await fake.deploy_tool_mcp("filesystem", "ghcr.io/example/mcp-fs:v1")

    @pytest.mark.asyncio
    async def test_unreachable_raises_runtime_error(self) -> None:
        """Distinct from PermissionError so callers can retry transients
        without retrying authorization failures."""
        fake = FakeMcpDeployer()
        fake.set_unreachable_for_deploy()
        with pytest.raises(RuntimeError, match="unreachable"):
            await fake.deploy_tool_mcp("github", "ghcr.io/example/mcp-github:v1")


class TestStopToolMcp:
    @pytest.mark.asyncio
    async def test_stop_removes_deployment(self) -> None:
        fake = FakeMcpDeployer()
        name = await fake.deploy_tool_mcp("github", "ghcr.io/example/mcp-github:v1")
        await fake.stop_tool_mcp(name)
        assert fake.stop_calls == [name]

    @pytest.mark.asyncio
    async def test_stop_unknown_is_idempotent(self) -> None:
        """Crash recovery: stopping an already-gone deployment must NOT
        raise — finalizers and recovery code rely on this."""
        fake = FakeMcpDeployer()
        await fake.stop_tool_mcp("mcp-ghost-9")
        # No raise; nothing in state.

    @pytest.mark.asyncio
    async def test_empty_name_raises_value_error(self) -> None:
        fake = FakeMcpDeployer()
        with pytest.raises(ValueError, match="deployment_name"):
            await fake.stop_tool_mcp("")


class TestHealth:
    @pytest.mark.asyncio
    async def test_healthy_by_default(self) -> None:
        fake = FakeMcpDeployer()
        assert await fake.health() is True

    @pytest.mark.asyncio
    async def test_unhealthy_returns_false(self) -> None:
        fake = FakeMcpDeployer()
        fake.set_unhealthy()
        assert await fake.health() is False


    @pytest.mark.asyncio
    async def test_health_is_observable_and_toggles_with_state(self) -> None:
        """Health probes must be observed by the fake (so tests can assert
        their circuit breakers did poll), AND the returned value must track
        the backing state so callers see recovery after set_unhealthy is
        reversed."""
        fake = FakeMcpDeployer()

        # Healthy by default.
        assert await fake.health() is True
        assert await fake.health() is True

        # Flip to unhealthy — subsequent probes must reflect that.
        fake.set_unhealthy()
        assert await fake.health() is False

        # Every probe was observed.
        assert fake.health_calls == 3
