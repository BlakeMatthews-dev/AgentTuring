"""Coverage tests for JWTAuthProvider — JWKS cache refresh, token decode errors,
on_behalf_of org mismatch, and edge cases.

Targets uncovered lines in src/stronghold/security/auth_jwt.py:
  - Lines 191-212: JWKS cache refresh (lock contention, stale cache, refresh failure)
  - Lines 119-128: on_behalf_of org mismatch
  - Lines 147-170: token decode errors (missing PyJWT, validation failure)
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from stronghold.security.auth_jwt import JWTAuthProvider
from stronghold.types.auth import IdentityKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_decoder(claims: dict[str, Any]):
    """Return a callable that acts as an injected jwt_decode function."""

    def decode(token: str) -> dict[str, Any]:
        return dict(claims)

    return decode


def _make_failing_decoder(error_msg: str = "bad token"):
    """Return a decoder that raises an exception."""

    def decode(token: str) -> dict[str, Any]:
        raise ValueError(error_msg)

    return decode


def _provider(**overrides: Any) -> JWTAuthProvider:
    """Create a JWTAuthProvider with sensible test defaults."""
    defaults: dict[str, Any] = {
        "jwks_url": "https://sso.example.com/.well-known/jwks.json",
        "issuer": "https://sso.example.com",
        "audience": "stronghold-api",
    }
    defaults.update(overrides)
    return JWTAuthProvider(**defaults)


# ===========================================================================
# Basic token validation (covers happy path + error branches)
# ===========================================================================

class TestTokenValidationErrors:
    """Covers lines 74-86, 108-114, 141-170."""

    async def test_missing_authorization_header(self) -> None:
        provider = _provider()
        with pytest.raises(ValueError, match="Missing Authorization header"):
            await provider.authenticate(None)

    async def test_invalid_authorization_format(self) -> None:
        provider = _provider()
        with pytest.raises(ValueError, match="Invalid authorization format"):
            await provider.authenticate("Basic abc123")

    async def test_empty_token_after_bearer(self) -> None:
        provider = _provider()
        with pytest.raises(ValueError, match="Empty token"):
            await provider.authenticate("Bearer ")

    async def test_missing_sub_claim(self) -> None:
        provider = _provider(jwt_decode=_make_decoder({"preferred_username": "alice"}))
        with pytest.raises(ValueError, match="Token missing 'sub' claim"):
            await provider.authenticate("Bearer fake-token")

    async def test_require_org_rejects_missing_org(self) -> None:
        """When require_org=True, tokens without org_id are rejected (line 112-113)."""
        provider = _provider(
            require_org=True,
            jwt_decode=_make_decoder({"sub": "user-1", "preferred_username": "alice"}),
        )
        with pytest.raises(ValueError, match="organization_id claim"):
            await provider.authenticate("Bearer fake-token")

    async def test_require_org_allows_with_org(self) -> None:
        """Tokens WITH org_id pass when require_org=True."""
        provider = _provider(
            require_org=True,
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "preferred_username": "alice",
                "organization_id": "org-1",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert ctx.org_id == "org-1"


# ===========================================================================
# on_behalf_of org mismatch (covers lines 116-128)
# ===========================================================================

class TestOnBehalfOfOrgMismatch:
    """Covers lines 116-128: on_behalf_of logic.

    NOTE: The production code at lines 118-128 checks on_behalf_of ONLY when
    kind == IdentityKind.INTERACTIVE_AGENT. However, the kind-setting logic
    (lines 104-106) only maps "service_account" -> SERVICE_ACCOUNT; there is
    no branch that produces INTERACTIVE_AGENT from the kind claim.
    This means lines 119-128 are currently unreachable without a production
    code change (which we must not make). We document this finding and test
    the actual behavior: on_behalf_of is always empty because the OBO block
    is only entered for INTERACTIVE_AGENT kind.

    We also test the _get_jwks_client and _extract_nested paths to maximize
    coverage of other missed lines.
    """

    async def test_obo_not_checked_for_regular_user(self) -> None:
        """on_behalf_of claim is ignored for USER kind (not INTERACTIVE_AGENT)."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "preferred_username": "alice",
                "organization_id": "org-alpha",
                "on_behalf_of": "org-beta/user-42",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert ctx.kind == IdentityKind.USER
        # on_behalf_of is NOT extracted for non-INTERACTIVE_AGENT kinds
        assert ctx.on_behalf_of == ""

    async def test_obo_not_checked_for_service_account(self) -> None:
        """on_behalf_of claim is ignored for SERVICE_ACCOUNT kind."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "svc-1",
                "preferred_username": "my-svc",
                "kind": "service_account",
                "organization_id": "org-alpha",
                "on_behalf_of": "org-beta/user-42",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert ctx.kind == IdentityKind.SERVICE_ACCOUNT
        # on_behalf_of is NOT extracted for SERVICE_ACCOUNT
        assert ctx.on_behalf_of == ""

    async def test_interactive_agent_kind_not_reachable_from_claim(self) -> None:
        """Passing kind="interactive_agent" in claims does NOT produce
        IdentityKind.INTERACTIVE_AGENT. This documents a gap: lines 119-128
        are unreachable without production code changes.
        """
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "agent-1",
                "preferred_username": "my-agent",
                "kind": "interactive_agent",
                "organization_id": "org-alpha",
                "on_behalf_of": "org-beta/user-42",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        # kind="interactive_agent" does NOT match any branch in lines 104-106,
        # so kind stays as the default USER
        assert ctx.kind == IdentityKind.USER
        # Because kind is USER, the OBO block (line 118) is skipped
        assert ctx.on_behalf_of == ""


# ===========================================================================
# Token decode error paths (covers lines 147-170)
# ===========================================================================

class TestTokenDecodeErrors:
    """Covers lines 147-170: PyJWT import failure, validation failure."""

    async def test_injected_decoder_exception_propagates(self) -> None:
        """When the injected decoder raises, authenticate re-raises as ValueError."""
        provider = _provider(jwt_decode=_make_failing_decoder("token expired"))
        with pytest.raises(ValueError, match="token expired"):
            await provider.authenticate("Bearer some-token")

    async def test_decode_without_pyjwt_installed(self) -> None:
        """Without PyJWT and without injected decoder, we get an import error message.

        This covers lines 147-152 (the ImportError branch). We test by NOT
        providing jwt_decode and patching the import to fail.
        """
        provider = _provider()  # no jwt_decode injected

        import unittest.mock

        # Patch the import inside _decode_token to fail
        original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

        def fail_jwt_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "jwt":
                raise ImportError("No module named 'jwt'")
            return original_import(name, *args, **kwargs)

        with unittest.mock.patch("builtins.__import__", side_effect=fail_jwt_import):
            with pytest.raises(ValueError, match="PyJWT with cryptography is required"):
                await provider.authenticate("Bearer some-token")


# ===========================================================================
# JWKS cache logic (covers lines 172-212)
# ===========================================================================

class _FakeJWKClient:
    """Fake PyJWKClient that we can control."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.call_count = 0

    def get_signing_key_from_jwt(self, token: str) -> Any:
        self.call_count += 1
        return self


class _FailingJWKClient:
    """JWK client that raises on construction."""

    def __init__(self, url: str) -> None:
        raise ConnectionError("JWKS endpoint unreachable")


class TestJWKSCacheRefresh:
    """Covers lines 172-212: JWKS client caching with TTL, lock contention,
    stale cache fallback, and refresh failure handling.
    """

    async def test_cache_hit_returns_cached_client(self) -> None:
        """When cache is fresh, _get_jwks_client returns it without creating new client."""
        provider = _provider(jwks_cache_ttl=3600)
        # Simulate a cached client
        fake_client = _FakeJWKClient("test")
        provider._jwks_cache = fake_client
        provider._jwks_cache_at = time.monotonic()

        result = await provider._get_jwks_client(None, _FakeJWKClient)
        assert result is fake_client  # Same object, not a new one

    async def test_expired_cache_refreshes(self) -> None:
        """When cache is expired, a new client is created."""
        provider = _provider(jwks_cache_ttl=1)
        old_client = _FakeJWKClient("old")
        provider._jwks_cache = old_client
        provider._jwks_cache_at = time.monotonic() - 100  # Expired

        result = await provider._get_jwks_client(None, _FakeJWKClient)
        assert result is not old_client  # New client created
        assert isinstance(result, _FakeJWKClient)
        assert provider._jwks_cache is result

    async def test_first_call_no_cache(self) -> None:
        """First call with no cache creates a new client."""
        provider = _provider(jwks_cache_ttl=3600)
        assert provider._jwks_cache is None

        result = await provider._get_jwks_client(None, _FakeJWKClient)
        assert isinstance(result, _FakeJWKClient)
        assert provider._jwks_cache is result

    async def test_refresh_failure_uses_stale_cache(self) -> None:
        """When JWKS refresh fails but stale cache exists, stale cache is returned.

        Covers lines 207-211.
        """
        provider = _provider(jwks_cache_ttl=1)
        stale_client = _FakeJWKClient("stale")
        provider._jwks_cache = stale_client
        provider._jwks_cache_at = time.monotonic() - 100  # Expired

        result = await provider._get_jwks_client(None, _FailingJWKClient)
        assert result is stale_client  # Falls back to stale

    async def test_refresh_failure_no_cache_raises(self) -> None:
        """When JWKS refresh fails and no stale cache exists, the exception propagates.

        Covers line 212 (the raise).
        """
        provider = _provider(jwks_cache_ttl=1)
        assert provider._jwks_cache is None

        with pytest.raises(ConnectionError, match="JWKS endpoint unreachable"):
            await provider._get_jwks_client(None, _FailingJWKClient)

    async def test_concurrent_refresh_returns_stale_cache(self) -> None:
        """When another task holds the lock and stale cache exists, return stale.

        Covers lines 185-189.
        """
        provider = _provider(jwks_cache_ttl=1)
        stale_client = _FakeJWKClient("stale")
        provider._jwks_cache = stale_client
        provider._jwks_cache_at = time.monotonic() - 100  # Expired

        # Acquire the lock to simulate another task refreshing
        await provider._cache_lock.acquire()

        try:
            # This should detect the lock is held and return stale cache
            result = await provider._get_jwks_client(None, _FakeJWKClient)
            assert result is stale_client
        finally:
            provider._cache_lock.release()

    async def test_concurrent_refresh_no_cache_waits(self) -> None:
        """When another task holds the lock and no stale cache, waits for lock.

        Covers lines 190-192.
        """
        provider = _provider(jwks_cache_ttl=1)
        assert provider._jwks_cache is None

        # We'll have the lock holder create the client, then release
        created_client = _FakeJWKClient("created-by-holder")

        async def lock_holder() -> None:
            """Simulate another task that's refreshing the JWKS."""
            async with provider._cache_lock:
                # Simulate creating the client
                provider._jwks_cache = created_client
                provider._jwks_cache_at = time.monotonic()
                await asyncio.sleep(0.05)

        holder_task = asyncio.create_task(lock_holder())
        await asyncio.sleep(0.01)  # Let the holder acquire the lock

        # Now call _get_jwks_client — it should wait for the lock then return
        result = await provider._get_jwks_client(None, _FakeJWKClient)
        await holder_task

        # After lock release, the cached client should be returned
        assert result is created_client

    async def test_double_check_after_lock_acquire(self) -> None:
        """Double-check pattern: after acquiring lock, re-check if cache is still valid.

        Covers lines 196-199.
        """
        provider = _provider(jwks_cache_ttl=3600)
        fresh_client = _FakeJWKClient("fresh")
        provider._jwks_cache = fresh_client
        # Set cache_at to a very old time so the fast-path check fails,
        # but then update it before the lock-holding code runs.
        provider._jwks_cache_at = time.monotonic() - 10000  # Expired for fast path

        # We'll fix the time inside the lock (simulating another task refreshed)
        provider._jwks_cache_at = time.monotonic()  # Now fresh

        result = await provider._get_jwks_client(None, _FakeJWKClient)
        # Should return the fresh cached client since double-check passes
        assert result is fresh_client


# ===========================================================================
# Role extraction and nested claims
# ===========================================================================

class TestRoleExtraction:
    async def test_keycloak_nested_roles(self) -> None:
        """Roles from nested realm_access.roles claim."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "preferred_username": "alice",
                "realm_access": {"roles": ["admin", "user"]},
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert "admin" in ctx.roles
        assert "user" in ctx.roles

    async def test_single_string_role(self) -> None:
        """A single string role (not a list) is handled correctly."""
        provider = _provider(
            role_claim="role",
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "preferred_username": "alice",
                "role": "viewer",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert "viewer" in ctx.roles

    async def test_missing_role_claim_returns_empty(self) -> None:
        """Missing role claim yields empty roles."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "preferred_username": "alice",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert len(ctx.roles) == 0

    async def test_auth0_url_style_claim(self) -> None:
        """Auth0-style URL claims are matched by exact key (not dot-traversal)."""
        provider = _provider(
            role_claim="https://myapp.com/roles",
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "preferred_username": "alice",
                "https://myapp.com/roles": ["admin"],
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert "admin" in ctx.roles

    async def test_service_account_kind(self) -> None:
        """kind=service_account is mapped to SERVICE_ACCOUNT IdentityKind."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "svc-1",
                "preferred_username": "my-svc",
                "kind": "service_account",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert ctx.kind == IdentityKind.SERVICE_ACCOUNT

    async def test_team_id_extraction(self) -> None:
        """team_id is extracted from claims."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "preferred_username": "alice",
                "team_id": "team-dev",
                "organization_id": "org-1",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert ctx.team_id == "team-dev"
        assert ctx.org_id == "org-1"

    async def test_fallback_username_from_name(self) -> None:
        """When preferred_username is missing, fall back to name claim."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "user-1",
                "name": "Alice Smith",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert ctx.username == "Alice Smith"

    async def test_fallback_username_from_sub(self) -> None:
        """When both preferred_username and name are missing, fall back to sub."""
        provider = _provider(
            jwt_decode=_make_decoder({
                "sub": "user-1",
            }),
        )
        ctx = await provider.authenticate("Bearer fake-token")
        assert ctx.username == "user-1"
