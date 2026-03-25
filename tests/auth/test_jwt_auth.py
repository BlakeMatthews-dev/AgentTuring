"""Tests for JWT authentication provider."""

import pytest

from stronghold.security.auth_jwt import JWTAuthProvider
from stronghold.types.auth import AuthContext, IdentityKind


def _make_provider(
    claims: dict | None = None,
    *,
    role_claim: str = "realm_access.roles",
    org_claim: str = "organization_id",
    team_claim: str = "team_id",
) -> JWTAuthProvider:
    """Create a JWTAuthProvider with an injected decoder for testing."""
    expected_claims = claims or {
        "sub": "user-123",
        "preferred_username": "blake",
        "realm_access": {"roles": ["admin", "user"]},
        "organization_id": "org-emerald",
        "team_id": "team-core",
    }

    def mock_decode(token: str) -> dict:
        if token == "expired":
            msg = "Token expired"
            raise ValueError(msg)
        if token == "bad":
            msg = "Invalid signature"
            raise ValueError(msg)
        return expected_claims

    return JWTAuthProvider(
        jwks_url="https://sso.example.com/certs",
        issuer="https://sso.example.com",
        audience="stronghold-api",
        role_claim=role_claim,
        org_claim=org_claim,
        team_claim=team_claim,
        jwt_decode=mock_decode,
    )


class TestJWTBasicAuth:
    """Basic JWT authentication flow."""

    @pytest.mark.asyncio
    async def test_valid_token(self) -> None:
        provider = _make_provider()
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.user_id == "user-123"
        assert ctx.username == "blake"
        assert ctx.auth_method == "jwt"

    @pytest.mark.asyncio
    async def test_roles_extracted(self) -> None:
        provider = _make_provider()
        ctx = await provider.authenticate("Bearer valid-token")
        assert "admin" in ctx.roles
        assert "user" in ctx.roles

    @pytest.mark.asyncio
    async def test_org_id_extracted(self) -> None:
        provider = _make_provider()
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == "org-emerald"

    @pytest.mark.asyncio
    async def test_team_id_extracted(self) -> None:
        provider = _make_provider()
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.team_id == "team-core"

    @pytest.mark.asyncio
    async def test_tenant_id_backward_compat(self) -> None:
        """tenant_id property returns org_id for backward compatibility."""
        provider = _make_provider()
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.tenant_id == ctx.org_id


class TestJWTErrorHandling:
    """JWT error cases."""

    @pytest.mark.asyncio
    async def test_missing_auth_header(self) -> None:
        provider = _make_provider()
        with pytest.raises(ValueError, match="Missing Authorization"):
            await provider.authenticate(None)

    @pytest.mark.asyncio
    async def test_invalid_format(self) -> None:
        provider = _make_provider()
        with pytest.raises(ValueError, match="Invalid authorization"):
            await provider.authenticate("Basic dXNlcjpwYXNz")

    @pytest.mark.asyncio
    async def test_empty_token(self) -> None:
        provider = _make_provider()
        with pytest.raises(ValueError, match="Empty token"):
            await provider.authenticate("Bearer ")

    @pytest.mark.asyncio
    async def test_expired_token(self) -> None:
        provider = _make_provider()
        with pytest.raises(ValueError, match="Token expired"):
            await provider.authenticate("Bearer expired")

    @pytest.mark.asyncio
    async def test_invalid_signature(self) -> None:
        provider = _make_provider()
        with pytest.raises(ValueError, match="Invalid signature"):
            await provider.authenticate("Bearer bad")


class TestJWTMissingSub:
    """Token missing required claims."""

    @pytest.mark.asyncio
    async def test_missing_sub_raises(self) -> None:
        provider = _make_provider({"preferred_username": "test"})
        with pytest.raises(ValueError, match="missing 'sub'"):
            await provider.authenticate("Bearer valid-token")


class TestJWTRoleClaims:
    """Different IdP role claim formats."""

    @pytest.mark.asyncio
    async def test_keycloak_roles(self) -> None:
        provider = _make_provider(
            {"sub": "u1", "realm_access": {"roles": ["admin", "operator"]}},
            role_claim="realm_access.roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset({"admin", "operator"})

    @pytest.mark.asyncio
    async def test_entra_id_roles(self) -> None:
        provider = _make_provider(
            {"sub": "u2", "roles": ["GlobalAdmin", "Reader"]},
            role_claim="roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset({"GlobalAdmin", "Reader"})

    @pytest.mark.asyncio
    async def test_auth0_roles(self) -> None:
        provider = _make_provider(
            {"sub": "u3", "https://myapp.com/roles": ["editor"]},
            role_claim="https://myapp.com/roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset({"editor"})

    @pytest.mark.asyncio
    async def test_no_roles_defaults_empty(self) -> None:
        provider = _make_provider({"sub": "u4"}, role_claim="realm_access.roles")
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()

    @pytest.mark.asyncio
    async def test_single_string_role(self) -> None:
        provider = _make_provider(
            {"sub": "u5", "role": "admin"},
            role_claim="role",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset({"admin"})


class TestJWTOrgEnforcement:
    """Multi-tenant mode rejects tokens without organization_id."""

    @pytest.mark.asyncio
    async def test_require_org_rejects_missing(self) -> None:
        provider = JWTAuthProvider(
            jwks_url="https://sso.example.com/certs",
            issuer="https://sso.example.com",
            audience="stronghold-api",
            require_org=True,
            jwt_decode=lambda t: {"sub": "u1", "preferred_username": "test"},
        )
        with pytest.raises(ValueError, match="missing organization_id"):
            await provider.authenticate("Bearer valid-token")

    @pytest.mark.asyncio
    async def test_require_org_passes_when_present(self) -> None:
        provider = JWTAuthProvider(
            jwks_url="https://sso.example.com/certs",
            issuer="https://sso.example.com",
            audience="stronghold-api",
            require_org=True,
            jwt_decode=lambda t: {
                "sub": "u1",
                "organization_id": "org-1",
                "team_id": "team-a",
            },
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == "org-1"
        assert ctx.team_id == "team-a"

    @pytest.mark.asyncio
    async def test_optional_org_allows_missing(self) -> None:
        provider = _make_provider({"sub": "u1"})
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == ""


class TestJWTRoleEdgeCases:
    """Edge cases in role claim extraction."""

    @pytest.mark.asyncio
    async def test_role_claim_returns_none(self) -> None:
        provider = _make_provider(
            {"sub": "u1", "roles": None},
            role_claim="roles",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()

    @pytest.mark.asyncio
    async def test_role_claim_returns_int(self) -> None:
        provider = _make_provider(
            {"sub": "u1", "role": 42},
            role_claim="role",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()


class TestJWTOrgTeamExtraction:
    """Organization + Team ID extraction from different claim formats."""

    @pytest.mark.asyncio
    async def test_no_org_returns_empty(self) -> None:
        provider = _make_provider({"sub": "u1"})
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == ""
        assert ctx.team_id == ""

    @pytest.mark.asyncio
    async def test_nested_org_claim(self) -> None:
        provider = _make_provider(
            {"sub": "u1", "org": {"id": "org-42"}},
            org_claim="org.id",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == "org-42"

    @pytest.mark.asyncio
    async def test_litellm_style_claims(self) -> None:
        """LiteLLM uses organization_id + team_id at top level."""
        provider = _make_provider(
            {
                "sub": "u1",
                "organization_id": "org-litellm",
                "team_id": "team-alpha",
            }
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.org_id == "org-litellm"
        assert ctx.team_id == "team-alpha"


class TestJWTIdentityKind:
    """Identity kind extraction — user vs service_account vs agent."""

    @pytest.mark.asyncio
    async def test_default_is_user(self) -> None:
        provider = _make_provider({"sub": "u1"})
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.USER

    @pytest.mark.asyncio
    async def test_service_account_kind(self) -> None:
        provider = _make_provider({"sub": "sa-1", "kind": "service_account"})
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.SERVICE_ACCOUNT
        assert ctx.is_service_account

    @pytest.mark.asyncio
    async def test_unknown_kind_defaults_to_user(self) -> None:
        provider = _make_provider({"sub": "u1", "kind": "unknown_thing"})
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.kind == IdentityKind.USER


class TestNestedClaimExtraction:
    """Test the dot-notation claim path resolver."""

    @pytest.mark.asyncio
    async def test_deeply_nested(self) -> None:
        provider = _make_provider(
            {"sub": "u1", "a": {"b": {"c": ["deep"]}}},
            role_claim="a.b.c",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert "deep" in ctx.roles

    @pytest.mark.asyncio
    async def test_missing_intermediate_key(self) -> None:
        provider = _make_provider(
            {"sub": "u1", "a": {"x": "nope"}},
            role_claim="a.b.c",
        )
        ctx = await provider.authenticate("Bearer valid-token")
        assert ctx.roles == frozenset()


class TestAuthContextModel:
    """Test the AuthContext identity model."""

    def test_scope_key(self) -> None:
        ctx = AuthContext(user_id="u1", org_id="org-1", team_id="team-a")
        assert ctx.scope_key == "org-1/team-a/u1"

    def test_scope_key_minimal(self) -> None:
        ctx = AuthContext(user_id="u1")
        assert ctx.scope_key == "u1"

    def test_same_org(self) -> None:
        a = AuthContext(user_id="u1", org_id="org-1", team_id="team-a")
        b = AuthContext(user_id="u2", org_id="org-1", team_id="team-b")
        assert a.same_org(b)

    def test_different_org(self) -> None:
        a = AuthContext(user_id="u1", org_id="org-1")
        b = AuthContext(user_id="u2", org_id="org-2")
        assert not a.same_org(b)

    def test_same_team(self) -> None:
        a = AuthContext(user_id="u1", org_id="org-1", team_id="team-a")
        b = AuthContext(user_id="u2", org_id="org-1", team_id="team-a")
        assert a.same_team(b)

    def test_different_team_same_org(self) -> None:
        a = AuthContext(user_id="u1", org_id="org-1", team_id="team-a")
        b = AuthContext(user_id="u2", org_id="org-1", team_id="team-b")
        assert not a.same_team(b)

    def test_on_behalf_of(self) -> None:
        ctx = AuthContext(
            user_id="agent-1",
            kind=IdentityKind.INTERACTIVE_AGENT,
            on_behalf_of="human-user-42",
        )
        assert ctx.on_behalf_of == "human-user-42"
        assert ctx.kind == IdentityKind.INTERACTIVE_AGENT
