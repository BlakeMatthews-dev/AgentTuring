"""Tests for the VaultClient protocol and FakeVaultClient (ADR-K8S-018)."""

from __future__ import annotations

import pytest

from stronghold.protocols.vault import VaultClient, VaultSecret
from tests.fakes import FakeVaultClient


class TestFakeVaultClientProtocol:
    def test_satisfies_protocol(self) -> None:
        assert isinstance(FakeVaultClient(), VaultClient)


class TestPutAndGet:
    async def test_put_then_get(self) -> None:
        vault = FakeVaultClient()
        result = await vault.put_user_secret("acme", "alice", "github", "pat", "ghp_test")
        assert isinstance(result, VaultSecret)
        assert result.service == "github"
        assert result.key == "pat"
        assert result.version == 1

        got = await vault.get_user_secret("acme", "alice", "github", "pat")
        assert got.value == "ghp_test"

    async def test_put_stores_value(self) -> None:
        vault = FakeVaultClient()
        await vault.put_user_secret("acme", "alice", "github", "pat", "ghp_abc123")
        got = await vault.get_user_secret("acme", "alice", "github", "pat")
        assert got.value == "ghp_abc123"

    async def test_put_increments_version(self) -> None:
        vault = FakeVaultClient()
        r1 = await vault.put_user_secret("acme", "alice", "github", "pat", "v1")
        r2 = await vault.put_user_secret("acme", "alice", "github", "pat", "v2")
        assert r1.version == 1
        assert r2.version == 2

    async def test_get_nonexistent_raises_lookup(self) -> None:
        vault = FakeVaultClient()
        with pytest.raises(LookupError):
            await vault.get_user_secret("acme", "alice", "github", "pat")


class TestDelete:
    async def test_delete_removes_secret(self) -> None:
        vault = FakeVaultClient()
        await vault.put_user_secret("acme", "alice", "github", "pat", "ghp_abc")
        await vault.delete_user_secret("acme", "alice", "github", "pat")
        with pytest.raises(LookupError):
            await vault.get_user_secret("acme", "alice", "github", "pat")

    async def test_delete_nonexistent_is_idempotent(self) -> None:
        vault = FakeVaultClient()
        await vault.delete_user_secret("acme", "alice", "github", "pat")


class TestListServices:
    async def test_empty_user(self) -> None:
        vault = FakeVaultClient()
        assert await vault.list_user_services("acme", "alice") == []

    async def test_lists_unique_services(self) -> None:
        vault = FakeVaultClient()
        await vault.put_user_secret("acme", "alice", "github", "pat", "g1")
        await vault.put_user_secret("acme", "alice", "github", "token", "g2")
        await vault.put_user_secret("acme", "alice", "jira", "api_key", "j1")
        services = await vault.list_user_services("acme", "alice")
        assert services == ["github", "jira"]

    async def test_other_user_not_visible(self) -> None:
        vault = FakeVaultClient()
        await vault.put_user_secret("acme", "alice", "github", "pat", "g1")
        assert await vault.list_user_services("acme", "bob") == []


class TestRevokeUser:
    async def test_revoke_deletes_all(self) -> None:
        vault = FakeVaultClient()
        await vault.put_user_secret("acme", "alice", "github", "pat", "g1")
        await vault.put_user_secret("acme", "alice", "jira", "key", "j1")
        count = await vault.revoke_user("acme", "alice")
        assert count == 2
        assert await vault.list_user_services("acme", "alice") == []

    async def test_revoke_empty_returns_zero(self) -> None:
        vault = FakeVaultClient()
        assert await vault.revoke_user("acme", "alice") == 0

    async def test_revoke_does_not_affect_other_users(self) -> None:
        vault = FakeVaultClient()
        await vault.put_user_secret("acme", "alice", "github", "pat", "a")
        await vault.put_user_secret("acme", "bob", "github", "pat", "b")
        await vault.revoke_user("acme", "alice")
        got = await vault.get_user_secret("acme", "bob", "github", "pat")
        assert got.value == "b"


class TestTenantIsolation:
    async def test_different_orgs_isolated(self) -> None:
        vault = FakeVaultClient()
        await vault.put_user_secret("acme", "alice", "github", "pat", "acme_token")
        await vault.put_user_secret("evil", "alice", "github", "pat", "evil_token")
        acme = await vault.get_user_secret("acme", "alice", "github", "pat")
        evil = await vault.get_user_secret("evil", "alice", "github", "pat")
        assert acme.value == "acme_token"
        assert evil.value == "evil_token"
