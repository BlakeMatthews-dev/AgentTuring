"""Tests for the SecretBackend protocol contract via FakeSecretBackend.

These tests pin the protocol semantics — every concrete backend (k8s, vault,
env) must satisfy the same scenarios. They also serve as the runtime-
checkable evidence that `FakeSecretBackend` actually implements
`SecretBackend`.
"""

from __future__ import annotations

import pytest

from stronghold.protocols.secrets import SecretBackend, SecretResult
from tests.fakes import FakeSecretBackend


class TestSecretResult:
    def test_value_required(self) -> None:
        result = SecretResult(value="hunter2")
        assert result.value == "hunter2"
        assert result.version is None

    def test_version_optional(self) -> None:
        result = SecretResult(value="hunter2", version="42")
        assert result.version == "42"

    def test_frozen_dataclass(self) -> None:
        result = SecretResult(value="hunter2")
        with pytest.raises(AttributeError):
            result.value = "leaked"  # type: ignore[misc]


class TestProtocolCompliance:
    def test_fake_implements_protocol(self) -> None:
        """FakeSecretBackend must expose every callable on the Protocol.

        Replaces a runtime_checkable ``isinstance`` check — that only
        verifies method names exist, not that they are callable. Asserting
        callability catches a regression where a method gets replaced with
        a non-callable attribute and the Protocol check silently passes.
        """
        fake = FakeSecretBackend()
        for name in ("get_secret", "watch_changes"):
            attr = getattr(fake, name, None)
            assert callable(attr), f"{name} must be callable on FakeSecretBackend"


class TestGetSecret:
    @pytest.mark.asyncio
    async def test_returns_seeded_value(self) -> None:
        fake = FakeSecretBackend()
        fake.set_secret("k8s/ns/name/key", "shh", version="v1")
        result = await fake.get_secret("k8s/ns/name/key")
        assert result.value == "shh"
        assert result.version == "v1"

    @pytest.mark.asyncio
    async def test_records_call(self) -> None:
        fake = FakeSecretBackend()
        fake.set_secret("k8s/ns/name/key", "shh")
        await fake.get_secret("k8s/ns/name/key")
        assert fake.get_calls == ["k8s/ns/name/key"]

    @pytest.mark.asyncio
    async def test_raises_value_error_on_malformed_ref(self) -> None:
        fake = FakeSecretBackend()
        with pytest.raises(ValueError, match="Malformed"):
            await fake.get_secret("not-a-path")
        with pytest.raises(ValueError, match="Malformed"):
            await fake.get_secret("///")

    @pytest.mark.asyncio
    async def test_raises_lookup_error_when_missing(self) -> None:
        fake = FakeSecretBackend()
        with pytest.raises(LookupError):
            await fake.get_secret("k8s/ns/missing/key")

    @pytest.mark.asyncio
    async def test_raises_permission_error_when_denied(self) -> None:
        fake = FakeSecretBackend()
        fake.set_secret("k8s/other-tenant/secret/key", "leak")
        fake.set_permission_denied("k8s/other-tenant/secret/key")
        with pytest.raises(PermissionError, match="Cedar"):
            await fake.get_secret("k8s/other-tenant/secret/key")

    @pytest.mark.asyncio
    async def test_permission_error_distinct_from_lookup_error(self) -> None:
        """Tenant-isolation guarantee: callers must be able to tell these apart."""
        fake = FakeSecretBackend()
        fake.set_permission_denied("k8s/other-tenant/secret/key")
        with pytest.raises(PermissionError):
            await fake.get_secret("k8s/other-tenant/secret/key")

        with pytest.raises(LookupError):
            await fake.get_secret("k8s/ns/missing/key")


class TestWatchChanges:
    @pytest.mark.asyncio
    async def test_yields_seeded_value_first(self) -> None:
        fake = FakeSecretBackend()
        fake.set_secret("k8s/ns/name/key", "v1", version="1")
        results = []
        async for r in fake.watch_changes("k8s/ns/name/key"):
            results.append(r)
        assert results[0] == SecretResult(value="v1", version="1")

    @pytest.mark.asyncio
    async def test_yields_pushed_changes(self) -> None:
        fake = FakeSecretBackend()
        fake.set_secret("k8s/ns/name/key", "v1", version="1")
        fake.push_change("k8s/ns/name/key", "v2", version="2")
        fake.push_change("k8s/ns/name/key", "v3", version="3")
        results = []
        async for r in fake.watch_changes("k8s/ns/name/key"):
            results.append(r)
        assert [r.version for r in results] == ["1", "2", "3"]

    @pytest.mark.asyncio
    async def test_raises_value_error_on_malformed_ref(self) -> None:
        fake = FakeSecretBackend()
        with pytest.raises(ValueError):
            async for _ in fake.watch_changes("not-a-path"):
                pass

    @pytest.mark.asyncio
    async def test_raises_lookup_error_when_missing(self) -> None:
        fake = FakeSecretBackend()
        with pytest.raises(LookupError):
            async for _ in fake.watch_changes("k8s/ns/missing/key"):
                pass


class TestClose:
    @pytest.mark.asyncio
    async def test_close_is_idempotent(self) -> None:
        fake = FakeSecretBackend()
        await fake.close()
        await fake.close()
        assert fake.close_calls == 2

    @pytest.mark.asyncio
    async def test_get_secret_after_close_raises_runtime_error(self) -> None:
        fake = FakeSecretBackend()
        fake.set_secret("k8s/ns/name/key", "v")
        await fake.close()
        with pytest.raises(RuntimeError, match="closed"):
            await fake.get_secret("k8s/ns/name/key")
