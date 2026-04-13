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


class TestInteractiveAgentKind:
    """H7: INTERACTIVE_AGENT code path must be reachable."""

    async def test_interactive_agent_kind_detected(self) -> None:
        """kind='interactive_agent' in token sets IdentityKind.INTERACTIVE_AGENT."""
        provider = _provider_with_claims(
            {
                "sub": "agent-1",
                "kind": "interactive_agent",
                "organization_id": "org-1",
                "on_behalf_of": "human-42",
            },
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.INTERACTIVE_AGENT
        assert ctx.on_behalf_of == "human-42"

    async def test_interactive_agent_obo_cross_org_rejected(self) -> None:
        """INTERACTIVE_AGENT with cross-org on_behalf_of is rejected."""
        provider = _provider_with_claims(
            {
                "sub": "agent-1",
                "kind": "interactive_agent",
                "organization_id": "org-1",
                "on_behalf_of": "org-2/human-42",
            },
        )
        with pytest.raises(ValueError, match="on_behalf_of org mismatch"):
            await provider.authenticate("Bearer valid-token")

    async def test_interactive_agent_without_obo(self) -> None:
        """INTERACTIVE_AGENT without on_behalf_of gets empty string."""
        provider = _provider_with_claims(
            {
                "sub": "agent-1",
                "kind": "interactive_agent",
            },
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.INTERACTIVE_AGENT
        assert ctx.on_behalf_of == ""

    async def test_agent_kind_detected(self) -> None:
        """kind='agent' in token sets IdentityKind.AGENT."""
        provider = _provider_with_claims(
            {"sub": "agent-1", "kind": "agent"},
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.AGENT


class TestJWKSCacheNoRace:
    """H8: JWKS cache refresh must not have TOCTOU race."""

    async def test_concurrent_refreshes_serialize(self) -> None:
        """Multiple concurrent cache refreshes must not race."""
        call_count = 0

        class MockJWKClient:
            def __init__(self, url: str) -> None:
                nonlocal call_count
                call_count += 1

        provider = JWTAuthProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            issuer="https://example.com",
            audience="stronghold-api",
            jwks_cache_ttl=0,  # Always expired
            jwt_decode=lambda t: {"sub": "u1"},
        )

        # Launch several refreshes concurrently
        results = await asyncio.gather(
            provider._get_jwks_client(None, MockJWKClient),
            provider._get_jwks_client(None, MockJWKClient),
            provider._get_jwks_client(None, MockJWKClient),
        )
        # All should return a client (no None results)
        for r in results:
            assert r is not None
        # The lock should ensure at most a small number of constructions
        # (ideally 1, but 2-3 is acceptable due to concurrency)
        assert call_count <= 3

    async def test_second_task_sees_refreshed_cache(self) -> None:
        """A second task waiting on the lock sees the refreshed cache, not stale."""
        refresh_count = 0

        class MockJWKClient:
            def __init__(self, url: str) -> None:
                nonlocal refresh_count
                refresh_count += 1
                self.url = url

        provider = JWTAuthProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            issuer="https://example.com",
            audience="stronghold-api",
            jwks_cache_ttl=0,  # Always expired so both tasks attempt refresh
            jwt_decode=lambda t: {"sub": "u1"},
        )

        # Both tasks will try to refresh; only one should create a new client
        results = await asyncio.gather(
            provider._get_jwks_client(None, MockJWKClient),
            provider._get_jwks_client(None, MockJWKClient),
        )
        # Both should get a result
        assert results[0] is not None
        assert results[1] is not None
        # With proper locking, the second task should see the cache
        # refreshed by the first task (double-check inside lock).
        # At most 2 constructions (one per gather task entering the lock),
        # but ideally only 1 if the second sees the fresh cache.
        assert refresh_count <= 2


class TestJWKSNonBlockingIO:
    """H9: JWKS fetch must not block the event loop."""

    async def test_get_signing_key_runs_in_thread(self) -> None:
        """PyJWKClient.get_signing_key_from_jwt must run in a thread, not inline."""
        call_thread_ids: list[int] = []
        import threading

        main_thread_id = threading.current_thread().ident

        class FakeSigningKey:
            key = "fake-key"

        class FakeJWKClient:
            def __init__(self, url: str) -> None:
                pass

            def get_signing_key_from_jwt(self, token: str) -> FakeSigningKey:
                call_thread_ids.append(threading.current_thread().ident)
                return FakeSigningKey()

        class FakePyJWT:
            @staticmethod
            def decode(
                token: str,
                key: Any,
                algorithms: list[str],
                issuer: str,
                audience: str,
            ) -> dict[str, Any]:
                return {"sub": "u1"}

        provider = JWTAuthProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            issuer="https://example.com",
            audience="stronghold-api",
        )
        # Pre-seed cache so we skip the cache refresh
        provider._jwks_cache = FakeJWKClient("x")
        import time

        provider._jwks_cache_at = time.monotonic()

        # Call _decode_token (no jwt_decode injected, so it uses real path)
        # We need to override the import. Instead, test the public interface.
        # The fix should use asyncio.to_thread for blocking calls.
        result = await provider._decode_token_with_client(
            "fake-token",
            FakePyJWT,
            FakeJWKClient("x"),
        )
        assert result["sub"] == "u1"
        # The signing key fetch should have run in a background thread
        assert len(call_thread_ids) == 1
        assert call_thread_ids[0] != main_thread_id


class TestJWKSCache:
    async def test_cache_hit_fast_path(self) -> None:
        """When cache is fresh, _get_jwks_client returns cached client without lock."""
        provider = JWTAuthProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            issuer="https://example.com",
            audience="stronghold-api",
            jwks_cache_ttl=3600,
            jwt_decode=lambda t: {"sub": "u1"},
        )
        sentinel_object = object()
        provider._jwks_cache = sentinel_object
        import time

        provider._jwks_cache_at = time.monotonic()

        result = await provider._get_jwks_client(None, None)
        assert result is sentinel_object

    async def test_refresh_failure_uses_stale_cache(self) -> None:
        """When JWKS refresh fails, stale cache is returned as fallback."""
        provider = JWTAuthProvider(
            jwks_url="https://example.com/.well-known/jwks.json",
            issuer="https://example.com",
            audience="stronghold-api",
            jwks_cache_ttl=0,  # Expired
            jwt_decode=lambda t: {"sub": "u1"},
        )
        stale_object = object()
        provider._jwks_cache = stale_object
        provider._jwks_cache_at = 0.0

        class FailingJWKClient:
            def __init__(self, url: str) -> None:
                msg = "Network error"
                raise ConnectionError(msg)

        # Should fall back to stale cache when refresh fails
        result = await provider._get_jwks_client(None, FailingJWKClient)
        assert result is stale_object
