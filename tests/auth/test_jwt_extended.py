"""Extended tests for JWTAuthProvider -- covers uncovered paths.

_extract_nested: dot notation, Auth0-style URLs, non-dict intermediate, empty path.
_extract_roles: single string role, non-list/non-string.
require_org: missing org raises ValueError.
IdentityKind.SERVICE_ACCOUNT from kind claim.
Token edge cases: empty, no Bearer prefix.
JWKS cache paths.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from stronghold.security.auth_jwt import JWTAuthProvider
from stronghold.types.auth import IdentityKind


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _provider_with_claims(
    claims: dict[str, Any],
    *,
    role_claim: str = "realm_access.roles",
    org_claim: str = "organization_id",
    team_claim: str = "team_id",
    kind_claim: str = "kind",
    require_org: bool = False,
) -> JWTAuthProvider:
    """Create a JWTAuthProvider with an injected decoder returning fixed claims."""
    return JWTAuthProvider(
        jwks_url="https://example.com/.well-known/jwks.json",
        issuer="https://example.com",
        audience="stronghold-api",
        role_claim=role_claim,
        org_claim=org_claim,
        team_claim=team_claim,
        kind_claim=kind_claim,
        require_org=require_org,
        jwt_decode=lambda token: claims,
    )


# ---------------------------------------------------------------------------
# Tests: _extract_nested
# ---------------------------------------------------------------------------


class TestExtractNested:
    async def test_dot_notation_traversal(self) -> None:
        """Dot notation like 'realm_access.roles' traverses nested dicts."""
        provider = _provider_with_claims(
            {"sub": "u1", "realm_access": {"roles": ["admin"]}},
            role_claim="realm_access.roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert "admin" in ctx.roles

    async def test_auth0_style_url_key(self) -> None:
        """Auth0-style URL claim names (exact key match) are handled."""
        provider = _provider_with_claims(
            {"sub": "u1", "https://myapp.com/roles": ["editor", "viewer"]},
            role_claim="https://myapp.com/roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset({"editor", "viewer"})

    async def test_non_dict_intermediate_returns_empty(self) -> None:
        """When an intermediate value is not a dict, extraction returns None (empty roles)."""
        provider = _provider_with_claims(
            {"sub": "u1", "realm_access": "not_a_dict"},
            role_claim="realm_access.roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()

    async def test_empty_path_returns_empty(self) -> None:
        """Empty path string returns None (empty roles)."""
        provider = _provider_with_claims(
            {"sub": "u1", "roles": ["admin"]},
            role_claim="",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()

    async def test_org_claim_with_dot_notation(self) -> None:
        """Org claim can use dot notation for nested structures."""
        provider = _provider_with_claims(
            {"sub": "u1", "company": {"org_id": "org-42"}},
            org_claim="company.org_id",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == "org-42"

    async def test_team_claim_with_dot_notation(self) -> None:
        """Team claim can use dot notation for nested structures."""
        provider = _provider_with_claims(
            {"sub": "u1", "company": {"team": "team-alpha"}},
            team_claim="company.team",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.team_id == "team-alpha"


# ---------------------------------------------------------------------------
# Tests: _extract_roles
# ---------------------------------------------------------------------------


class TestExtractRoles:
    async def test_single_string_role(self) -> None:
        """A single string role value is wrapped into a list."""
        provider = _provider_with_claims(
            {"sub": "u1", "role": "admin"},
            role_claim="role",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset({"admin"})

    async def test_non_list_non_string_returns_empty(self) -> None:
        """Non-list, non-string role value (e.g., int) returns empty set."""
        provider = _provider_with_claims(
            {"sub": "u1", "role": 42},
            role_claim="role",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()

    async def test_none_role_returns_empty(self) -> None:
        """None role value returns empty set."""
        provider = _provider_with_claims(
            {"sub": "u1", "role": None},
            role_claim="role",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()

    async def test_bool_role_returns_empty(self) -> None:
        """Boolean role value is not a list or string, returns empty."""
        provider = _provider_with_claims(
            {"sub": "u1", "role": True},
            role_claim="role",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()

    async def test_list_of_mixed_types(self) -> None:
        """List roles are all converted to strings."""
        provider = _provider_with_claims(
            {"sub": "u1", "roles": ["admin", 42, True]},
            role_claim="roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert "admin" in ctx.roles
        assert "42" in ctx.roles


# ---------------------------------------------------------------------------
# Tests: require_org mode
# ---------------------------------------------------------------------------


class TestRequireOrg:
    async def test_require_org_missing_raises(self) -> None:
        """require_org=True with no org claim in token raises ValueError."""
        provider = _provider_with_claims(
            {"sub": "u1", "preferred_username": "test"},
            require_org=True,
        )
        with pytest.raises(ValueError, match="missing organization_id"):
            await provider.authenticate("Bearer valid-token")

    async def test_require_org_present_passes(self) -> None:
        """require_org=True with org present in token passes."""
        provider = _provider_with_claims(
            {"sub": "u1", "organization_id": "org-1"},
            require_org=True,
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == "org-1"

    async def test_require_org_empty_string_raises(self) -> None:
        """require_org=True with empty string org_id raises ValueError."""
        provider = _provider_with_claims(
            {"sub": "u1", "organization_id": ""},
            require_org=True,
        )
        with pytest.raises(ValueError, match="missing organization_id"):
            await provider.authenticate("Bearer valid-token")


# ---------------------------------------------------------------------------
# Tests: IdentityKind
# ---------------------------------------------------------------------------


class TestIdentityKindExtraction:
    async def test_service_account_detected(self) -> None:
        """kind='service_account' in token sets IdentityKind.SERVICE_ACCOUNT."""
        provider = _provider_with_claims(
            {"sub": "sa-1", "kind": "service_account"},
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.SERVICE_ACCOUNT
        assert ctx.is_service_account

    async def test_default_is_user(self) -> None:
        """No kind claim defaults to IdentityKind.USER."""
        provider = _provider_with_claims({"sub": "u1"})
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.USER

    async def test_unknown_kind_defaults_to_user(self) -> None:
        """Unknown kind value defaults to IdentityKind.USER."""
        provider = _provider_with_claims(
            {"sub": "u1", "kind": "robot"},
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.USER

    async def test_kind_via_nested_claim(self) -> None:
        """Kind claim can be nested using dot notation."""
        provider = _provider_with_claims(
            {"sub": "u1", "identity": {"kind": "service_account"}},
            kind_claim="identity.kind",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.SERVICE_ACCOUNT


# ---------------------------------------------------------------------------
# Tests: Token edge cases
# ---------------------------------------------------------------------------


class TestTokenEdgeCases:
    async def test_empty_authorization_raises(self) -> None:
        """Empty string authorization raises ValueError."""
        provider = _provider_with_claims({"sub": "u1"})
        with pytest.raises(ValueError, match="Missing Authorization"):
            await provider.authenticate("")

    async def test_none_authorization_raises(self) -> None:
        """None authorization raises ValueError."""
        provider = _provider_with_claims({"sub": "u1"})
        with pytest.raises(ValueError, match="Missing Authorization"):
            await provider.authenticate(None)

    async def test_bearer_with_spaces_only(self) -> None:
        """'Bearer   ' (only spaces after Bearer) raises empty token error."""
        provider = _provider_with_claims({"sub": "u1"})
        with pytest.raises(ValueError, match="Empty token"):
            await provider.authenticate("Bearer    ")

    async def test_username_fallback_to_name(self) -> None:
        """If preferred_username is missing, falls back to 'name' claim."""
        provider = _provider_with_claims(
            {"sub": "u1", "name": "Blake Smith"},
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.username == "Blake Smith"

    async def test_username_fallback_to_sub(self) -> None:
        """If both preferred_username and name are missing, falls back to sub."""
        provider = _provider_with_claims({"sub": "user-42"})
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.username == "user-42"


# ---------------------------------------------------------------------------
# Tests: JWKS cache
# ---------------------------------------------------------------------------


class TestJWKSCache:
    async def test_cache_hit_fast_path(self) -> None:
        """When cache is fresh, _get_jwks_client returns cached client without lock."""
        # We can test this by calling _get_jwks_client twice and checking it
        # returns the same object (proving the cache path works).
        provider = JWTAuthProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            issuer="https://example.com",
            audience="stronghold-api",
            jwks_cache_ttl=3600,
            jwt_decode=lambda t: {"sub": "u1"},
        )
        # Manually seed the cache
        sentinel_object = object()
        provider._jwks_cache = sentinel_object
        import time

        provider._jwks_cache_at = time.monotonic()

        # Mock JWKClient class and pyjwt -- we just need to verify cache hit
        result = await provider._get_jwks_client(None, None)
        assert result is sentinel_object

    async def test_stale_cache_used_when_lock_held(self) -> None:
        """When lock is held by another task, stale cache is returned."""
        provider = JWTAuthProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            issuer="https://example.com",
            audience="stronghold-api",
            jwks_cache_ttl=1,  # Very short TTL so cache is expired
            jwt_decode=lambda t: {"sub": "u1"},
        )
        # Seed a stale cache
        stale_object = object()
        provider._jwks_cache = stale_object
        provider._jwks_cache_at = 0.0  # Very old -> expired

        # Acquire lock to simulate another task refreshing
        async with provider._cache_lock:
            # In a concurrent task, try to get the client while lock is held
            result = await asyncio.wait_for(
                provider._get_jwks_client(None, None),
                timeout=1.0,
            )
            # Should return stale cache since lock is held
            assert result is stale_object
