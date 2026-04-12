"""Tests for the AgentPodDiscovery protocol contract via FakeAgentPodDiscovery.

These tests pin the contract every concrete discovery implementation must
satisfy, including the tenant-isolation invariants and the
generation-skew rules that protect against out-of-order spawner callbacks.
"""

from __future__ import annotations

import pytest

from stronghold.protocols.agent_pod import AgentPodDiscovery, AgentPodInfo
from tests.fakes import FakeAgentPodDiscovery


class TestAgentPodInfo:
    def test_fields(self) -> None:
        info = AgentPodInfo(ip="10.0.0.1", generation=3, pod_name="mason-abc")
        assert info.ip == "10.0.0.1"
        assert info.generation == 3
        assert info.pod_name == "mason-abc"

    def test_frozen(self) -> None:
        info = AgentPodInfo(ip="10.0.0.1", generation=1, pod_name="mason-abc")
        with pytest.raises(AttributeError):
            info.ip = "10.0.0.2"  # type: ignore[misc]


class TestProtocolCompliance:
    def test_fake_implements_protocol(self) -> None:
        fake = FakeAgentPodDiscovery()
        assert isinstance(fake, AgentPodDiscovery)


class TestGetUserPod:
    @pytest.mark.asyncio
    async def test_returns_none_when_unregistered(self) -> None:
        fake = FakeAgentPodDiscovery()
        result = await fake.get_user_pod("acme", "alice", "mason")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_registered_pod(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        result = await fake.get_user_pod("acme", "alice", "mason")
        assert result == AgentPodInfo(ip="10.0.0.1", generation=1, pod_name="mason-1")

    @pytest.mark.asyncio
    async def test_records_calls(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.get_user_pod("acme", "alice", "mason")
        assert fake.get_calls == [("acme", "alice", "mason")]

    @pytest.mark.asyncio
    async def test_isolation_per_tenant(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        # Same user_id + agent_type, different tenant — must not leak.
        result = await fake.get_user_pod("globex", "alice", "mason")
        assert result is None

    @pytest.mark.asyncio
    async def test_isolation_per_user(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        result = await fake.get_user_pod("acme", "bob", "mason")
        assert result is None

    @pytest.mark.asyncio
    async def test_isolation_per_agent_type(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        result = await fake.get_user_pod("acme", "alice", "davinci")
        assert result is None

    @pytest.mark.asyncio
    async def test_permission_error_for_denied_tenant(self) -> None:
        fake = FakeAgentPodDiscovery()
        fake.set_permission_denied_for_tenant("globex")
        with pytest.raises(PermissionError, match="globex"):
            await fake.get_user_pod("globex", "alice", "mason")


class TestRegisterPod:
    @pytest.mark.asyncio
    async def test_register_persists(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        result = await fake.get_user_pod("acme", "alice", "mason")
        assert result is not None
        assert result.generation == 1

    @pytest.mark.asyncio
    async def test_register_records_calls(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        assert fake.register_calls == [("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)]

    @pytest.mark.asyncio
    async def test_higher_generation_replaces_existing(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        await fake.register_pod("acme", "alice", "mason", "mason-2", "10.0.0.2", 2)
        result = await fake.get_user_pod("acme", "alice", "mason")
        assert result is not None
        assert result.generation == 2
        assert result.ip == "10.0.0.2"
        assert result.pod_name == "mason-2"

    @pytest.mark.asyncio
    async def test_lower_generation_is_ignored(self) -> None:
        """Out-of-order spawner callbacks must not roll back the live mapping."""
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-2", "10.0.0.2", 2)
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        result = await fake.get_user_pod("acme", "alice", "mason")
        assert result is not None
        assert result.generation == 2  # Did not regress.

    @pytest.mark.asyncio
    async def test_permission_error_for_denied_tenant(self) -> None:
        fake = FakeAgentPodDiscovery()
        fake.set_permission_denied_for_tenant("globex")
        with pytest.raises(PermissionError):
            await fake.register_pod("globex", "alice", "mason", "p", "10.0.0.1", 1)


class TestUnregisterPod:
    @pytest.mark.asyncio
    async def test_unregister_removes_entry(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        await fake.unregister_pod("acme", "alice", "mason", "mason-1")
        result = await fake.get_user_pod("acme", "alice", "mason")
        assert result is None

    @pytest.mark.asyncio
    async def test_unregister_does_not_evict_replacement_pod(self) -> None:
        """The delete-then-respawn race: deletion of the OLD pod_name must
        not wipe the entry held by a NEW pod_name registered for the same
        identity in between."""
        fake = FakeAgentPodDiscovery()
        await fake.register_pod("acme", "alice", "mason", "mason-1", "10.0.0.1", 1)
        await fake.register_pod("acme", "alice", "mason", "mason-2", "10.0.0.2", 2)
        # Late-arriving DELETE event for the old pod.
        await fake.unregister_pod("acme", "alice", "mason", "mason-1")
        result = await fake.get_user_pod("acme", "alice", "mason")
        assert result is not None
        assert result.pod_name == "mason-2"

    @pytest.mark.asyncio
    async def test_unregister_unknown_is_noop(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.unregister_pod("acme", "alice", "mason", "mason-ghost")
        # No raise; nothing in state.
        assert await fake.get_user_pod("acme", "alice", "mason") is None

    @pytest.mark.asyncio
    async def test_permission_error_for_denied_tenant(self) -> None:
        fake = FakeAgentPodDiscovery()
        fake.set_permission_denied_for_tenant("globex")
        with pytest.raises(PermissionError):
            await fake.unregister_pod("globex", "alice", "mason", "p")


class TestClose:
    @pytest.mark.asyncio
    async def test_close_idempotent(self) -> None:
        fake = FakeAgentPodDiscovery()
        await fake.close()
        await fake.close()
        assert fake.close_calls == 2
