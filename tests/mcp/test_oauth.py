"""Tests for MCP OAuth 2.1 — PKCE + DCR (ADR-K8S-024, issue #964).

Tests the full OAuth flow: discovery, registration, authorization,
token exchange with PKCE, refresh, and revocation.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.mcp.oauth.endpoints import router, set_oauth_store
from stronghold.mcp.oauth.store import InMemoryOAuthStore, OAuthStore, _hash_token
from stronghold.mcp.oauth.types import TokenClaims


def _make_app(store: OAuthStore | None = None) -> tuple[TestClient, OAuthStore]:
    app = FastAPI()
    app.include_router(router)
    s = store or InMemoryOAuthStore()
    set_oauth_store(s)
    return TestClient(app), s


def _pkce_pair() -> tuple[str, str]:
    """Generate a PKCE code_verifier and code_challenge (S256)."""
    verifier = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


class TestDiscovery:
    def test_returns_metadata(self) -> None:
        client, _ = _make_app()
        resp = client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        data = resp.json()
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data
        assert "S256" in data["code_challenge_methods_supported"]

    def test_grants_include_authorization_code(self) -> None:
        client, _ = _make_app()
        data = client.get("/.well-known/oauth-authorization-server").json()
        assert "authorization_code" in data["grant_types_supported"]
        assert "refresh_token" in data["grant_types_supported"]


class TestRegistration:
    def test_register_returns_credentials(self) -> None:
        client, _ = _make_app()
        resp = client.post("/oauth/register", json={
            "client_name": "Claude Desktop",
            "redirect_uris": ["http://localhost:8080/callback"],
        })
        assert resp.status_code == 201
        data = resp.json()
        assert data["client_id"].startswith("mcp_")
        assert len(data["client_secret"]) > 20
        assert data["client_name"] == "Claude Desktop"

    def test_register_requires_redirect_uris(self) -> None:
        client, _ = _make_app()
        resp = client.post("/oauth/register", json={"client_name": "bad"})
        assert resp.status_code == 400


class TestAuthorization:
    def _register(self, client: TestClient) -> dict[str, Any]:
        resp = client.post("/oauth/register", json={
            "client_name": "test",
            "redirect_uris": ["http://localhost/cb"],
        })
        return resp.json()

    def test_issues_auth_code(self) -> None:
        client, _ = _make_app()
        creds = self._register(client)
        _, challenge = _pkce_pair()
        resp = client.get("/oauth/authorize", params={
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "scope": "tools",
            "state": "xyz",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "code" in data
        assert data["state"] == "xyz"

    def test_rejects_unknown_client(self) -> None:
        client, _ = _make_app()
        _, challenge = _pkce_pair()
        resp = client.get("/oauth/authorize", params={
            "client_id": "unknown",
            "redirect_uri": "http://localhost/cb",
            "code_challenge": challenge,
        })
        assert resp.status_code == 400

    def test_rejects_unregistered_redirect(self) -> None:
        client, _ = _make_app()
        creds = self._register(client)
        _, challenge = _pkce_pair()
        resp = client.get("/oauth/authorize", params={
            "client_id": creds["client_id"],
            "redirect_uri": "http://evil.com/steal",
            "code_challenge": challenge,
        })
        assert resp.status_code == 400

    def test_rejects_missing_pkce(self) -> None:
        client, _ = _make_app()
        creds = self._register(client)
        resp = client.get("/oauth/authorize", params={
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        })
        assert resp.status_code == 400


class TestTokenExchange:
    def _full_auth_flow(self, client: TestClient) -> tuple[dict, str, str]:
        """Register + authorize, return (creds, code, verifier)."""
        creds = client.post("/oauth/register", json={
            "client_name": "test",
            "redirect_uris": ["http://localhost/cb"],
        }).json()
        verifier, challenge = _pkce_pair()
        auth_resp = client.get("/oauth/authorize", params={
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }).json()
        return creds, auth_resp["code"], verifier

    def test_exchange_returns_tokens(self) -> None:
        client, _ = _make_app()
        creds, code, verifier = self._full_auth_flow(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] == 900

    def test_wrong_verifier_fails(self) -> None:
        client, _ = _make_app()
        creds, code, _ = self._full_auth_flow(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": "wrong-verifier",
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        })
        assert resp.status_code == 400
        assert "PKCE" in resp.json()["detail"]

    def test_code_replay_fails(self) -> None:
        client, _ = _make_app()
        creds, code, verifier = self._full_auth_flow(client)
        # First exchange succeeds
        client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        })
        # Replay fails
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        })
        assert resp.status_code == 400

    def test_missing_verifier_rejected(self) -> None:
        client, _ = _make_app()
        creds, code, _ = self._full_auth_flow(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        })
        assert resp.status_code == 400


class TestRefresh:
    def _get_tokens(self, client: TestClient) -> tuple[dict, dict]:
        creds = client.post("/oauth/register", json={
            "client_name": "test",
            "redirect_uris": ["http://localhost/cb"],
        }).json()
        verifier, challenge = _pkce_pair()
        code = client.get("/oauth/authorize", params={
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
            "code_challenge": challenge,
        }).json()["code"]
        tokens = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        }).json()
        return creds, tokens

    def test_refresh_returns_new_tokens(self) -> None:
        client, _ = _make_app()
        creds, tokens = self._get_tokens(client)
        resp = client.post("/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": creds["client_id"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] != tokens["access_token"]
        assert data["refresh_token"] != tokens["refresh_token"]

    def test_old_refresh_token_revoked(self) -> None:
        client, store = _make_app()
        creds, tokens = self._get_tokens(client)
        # Use refresh token
        client.post("/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": creds["client_id"],
        })
        # Old refresh token should be revoked
        resp = client.post("/oauth/token", data={
            "grant_type": "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id": creds["client_id"],
        })
        assert resp.status_code == 400


class TestRevocation:
    def test_revoke_access_token(self) -> None:
        client, store = _make_app()
        # Get tokens through full flow
        creds = client.post("/oauth/register", json={
            "client_name": "test",
            "redirect_uris": ["http://localhost/cb"],
        }).json()
        verifier, challenge = _pkce_pair()
        code = client.get("/oauth/authorize", params={
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
            "code_challenge": challenge,
        }).json()["code"]
        tokens = client.post("/oauth/token", data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": verifier,
            "client_id": creds["client_id"],
            "redirect_uri": "http://localhost/cb",
        }).json()

        # Revoke
        resp = client.post("/oauth/revoke", data={"token": tokens["access_token"]})
        assert resp.status_code == 200


class TestStoreProtocol:
    def test_in_memory_satisfies_protocol(self) -> None:
        assert isinstance(InMemoryOAuthStore(), OAuthStore)


class TestTokenValidation:
    async def test_validate_returns_claims(self) -> None:
        from stronghold.mcp.oauth.store import issue_access_token

        store = InMemoryOAuthStore()
        value, token = issue_access_token("c1", "u1", "t1", "tools")
        await store.store_token(token)
        claims = await store.validate_token(value)
        assert claims is not None
        assert claims.user_id == "u1"
        assert claims.tenant_id == "t1"

    async def test_validate_revoked_returns_none(self) -> None:
        from stronghold.mcp.oauth.store import issue_access_token

        store = InMemoryOAuthStore()
        value, token = issue_access_token("c1", "u1", "t1", "tools")
        await store.store_token(token)
        await store.revoke_token(value)
        assert await store.validate_token(value) is None
