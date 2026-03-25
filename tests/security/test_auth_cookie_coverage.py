"""Tests for stronghold/security/auth_cookie.py -- CookieAuthProvider.

Covers: cookie-based authentication, session validation, cookie parsing,
missing headers, empty cookies, malformed cookies, multiple cookies,
and delegation to JWTAuthProvider.

Uses the real CookieAuthProvider with an injectable JWT decoder (JWTAuthProvider
supports jwt_decode injection for testing without PyJWT/JWKS).
"""

from __future__ import annotations

import pytest

from stronghold.security.auth_cookie import CookieAuthProvider
from stronghold.security.auth_jwt import JWTAuthProvider
from stronghold.types.auth import AuthContext, IdentityKind


def _make_jwt_provider(claims: dict | None = None) -> JWTAuthProvider:
    """Create a JWTAuthProvider with an injectable decoder for testing.

    The jwt_decode callable simulates JWT validation: it returns the
    given claims dict for any token. This avoids needing real RS256 keys.
    """
    default_claims = {
        "sub": "user-123",
        "preferred_username": "testuser",
        "realm_access": {"roles": ["admin", "user"]},
        "organization_id": "org-test",
        "team_id": "team-alpha",
    }
    effective_claims = claims if claims is not None else default_claims

    def fake_decode(token: str) -> dict:
        return effective_claims

    return JWTAuthProvider(
        jwks_url="https://sso.example.com/certs",
        issuer="https://sso.example.com",
        audience="stronghold-api",
        jwt_decode=fake_decode,
    )


def _make_cookie_provider(
    claims: dict | None = None,
    cookie_name: str = "stronghold_session",
) -> CookieAuthProvider:
    """Create a CookieAuthProvider backed by a fake JWTAuthProvider."""
    jwt_provider = _make_jwt_provider(claims)
    return CookieAuthProvider(jwt_provider=jwt_provider, cookie_name=cookie_name)


class TestCookieAuthBasic:
    async def test_valid_cookie_authenticates(self) -> None:
        """A valid session cookie should delegate to JWTAuthProvider and return AuthContext."""
        provider = _make_cookie_provider()
        ctx = await provider.authenticate(
            authorization=None,
            headers={"cookie": "stronghold_session=eyJhbGciOiJSUzI1NiJ9.fake.token"},
        )
        assert isinstance(ctx, AuthContext)
        assert ctx.user_id == "user-123"
        assert ctx.username == "testuser"
        assert ctx.org_id == "org-test"
        assert ctx.auth_method == "jwt"

    async def test_valid_cookie_extracts_roles(self) -> None:
        provider = _make_cookie_provider()
        ctx = await provider.authenticate(
            authorization=None,
            headers={"cookie": "stronghold_session=valid-token-here"},
        )
        assert "admin" in ctx.roles
        assert "user" in ctx.roles

    async def test_valid_cookie_extracts_team(self) -> None:
        provider = _make_cookie_provider()
        ctx = await provider.authenticate(
            authorization=None,
            headers={"cookie": "stronghold_session=valid-token-here"},
        )
        assert ctx.team_id == "team-alpha"


class TestCookieAuthMissingInput:
    async def test_no_headers_raises_valueerror(self) -> None:
        """No headers dict at all should raise ValueError."""
        provider = _make_cookie_provider()
        with pytest.raises(ValueError, match="No headers"):
            await provider.authenticate(authorization=None, headers=None)

    async def test_empty_headers_raises_valueerror(self) -> None:
        """Empty headers dict (no cookie header) should raise ValueError."""
        provider = _make_cookie_provider()
        with pytest.raises(ValueError, match="No headers"):
            await provider.authenticate(authorization=None, headers={})

    async def test_no_cookie_header_raises_valueerror(self) -> None:
        """Headers present but no 'cookie' key should raise ValueError."""
        provider = _make_cookie_provider()
        with pytest.raises(ValueError, match="No cookie header"):
            await provider.authenticate(
                authorization=None,
                headers={"content-type": "application/json"},
            )

    async def test_empty_cookie_header_raises_valueerror(self) -> None:
        """Empty cookie header string should raise ValueError."""
        provider = _make_cookie_provider()
        with pytest.raises(ValueError, match="No cookie header"):
            await provider.authenticate(
                authorization=None,
                headers={"cookie": ""},
            )


class TestCookieAuthWrongCookie:
    async def test_wrong_cookie_name_raises_valueerror(self) -> None:
        """Cookie exists but with the wrong name should raise ValueError."""
        provider = _make_cookie_provider()
        with pytest.raises(ValueError, match="not found"):
            await provider.authenticate(
                authorization=None,
                headers={"cookie": "other_session=some-value"},
            )

    async def test_custom_cookie_name(self) -> None:
        """Provider configured with a custom cookie name should find it."""
        provider = _make_cookie_provider(cookie_name="my_session")
        ctx = await provider.authenticate(
            authorization=None,
            headers={"cookie": "my_session=valid-token"},
        )
        assert ctx.user_id == "user-123"

    async def test_custom_cookie_name_not_found(self) -> None:
        """Custom cookie name not in the cookie header raises ValueError."""
        provider = _make_cookie_provider(cookie_name="my_session")
        with pytest.raises(ValueError, match="not found"):
            await provider.authenticate(
                authorization=None,
                headers={"cookie": "stronghold_session=valid-token"},
            )


class TestCookieAuthMultipleCookies:
    async def test_multiple_cookies_finds_correct_one(self) -> None:
        """When multiple cookies are present, extract the correct one."""
        provider = _make_cookie_provider()
        ctx = await provider.authenticate(
            authorization=None,
            headers={
                "cookie": "other=abc; stronghold_session=my-jwt-token; tracking=xyz"
            },
        )
        assert ctx.user_id == "user-123"

    async def test_multiple_cookies_missing_target(self) -> None:
        """Multiple cookies but target cookie missing raises ValueError."""
        provider = _make_cookie_provider()
        with pytest.raises(ValueError, match="not found"):
            await provider.authenticate(
                authorization=None,
                headers={"cookie": "other=abc; tracking=xyz"},
            )


class TestCookieAuthJWTValidation:
    async def test_jwt_validation_failure_propagates(self) -> None:
        """If the JWT inside the cookie is invalid, the error propagates."""

        def failing_decode(token: str) -> dict:
            msg = "Token expired"
            raise ValueError(msg)

        jwt_provider = JWTAuthProvider(
            jwks_url="https://sso.example.com/certs",
            issuer="https://sso.example.com",
            audience="stronghold-api",
            jwt_decode=failing_decode,
        )
        provider = CookieAuthProvider(jwt_provider=jwt_provider)

        with pytest.raises(ValueError, match="Token expired"):
            await provider.authenticate(
                authorization=None,
                headers={"cookie": "stronghold_session=expired-token"},
            )

    async def test_missing_sub_claim_raises(self) -> None:
        """Token without 'sub' claim should fail during JWT validation."""
        provider = _make_cookie_provider(claims={"preferred_username": "nobody"})
        with pytest.raises(ValueError, match="sub"):
            await provider.authenticate(
                authorization=None,
                headers={"cookie": "stronghold_session=no-sub-token"},
            )


class TestCookieAuthEdgeCases:
    async def test_authorization_header_ignored(self) -> None:
        """The authorization parameter is ignored; cookie is used instead."""
        provider = _make_cookie_provider()
        ctx = await provider.authenticate(
            authorization="Bearer some-api-key",
            headers={"cookie": "stronghold_session=jwt-from-cookie"},
        )
        # Should use the cookie token, not the Bearer token
        assert ctx.user_id == "user-123"

    async def test_cookie_with_quoted_value(self) -> None:
        """SimpleCookie should handle quoted cookie values correctly."""
        provider = _make_cookie_provider()
        ctx = await provider.authenticate(
            authorization=None,
            headers={"cookie": 'stronghold_session="my-jwt-token"'},
        )
        assert ctx.user_id == "user-123"

    async def test_service_account_kind(self) -> None:
        """Token with kind=service_account should set the correct identity kind."""
        provider = _make_cookie_provider(
            claims={
                "sub": "svc-bot",
                "preferred_username": "automation-bot",
                "realm_access": {"roles": ["user"]},
                "kind": "service_account",
            }
        )
        ctx = await provider.authenticate(
            authorization=None,
            headers={"cookie": "stronghold_session=svc-token"},
        )
        assert ctx.kind == IdentityKind.SERVICE_ACCOUNT
        assert ctx.user_id == "svc-bot"

    async def test_org_and_team_extraction(self) -> None:
        """Full org/team/user extraction from JWT claims via cookie."""
        provider = _make_cookie_provider(
            claims={
                "sub": "user-42",
                "preferred_username": "alice",
                "realm_access": {"roles": ["user"]},
                "organization_id": "acme-corp",
                "team_id": "engineering",
            }
        )
        ctx = await provider.authenticate(
            authorization=None,
            headers={"cookie": "stronghold_session=alice-token"},
        )
        assert ctx.user_id == "user-42"
        assert ctx.org_id == "acme-corp"
        assert ctx.team_id == "engineering"
