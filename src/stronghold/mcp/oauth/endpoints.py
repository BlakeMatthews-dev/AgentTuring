"""OAuth 2.1 endpoints for MCP authentication (ADR-K8S-024).

Implements the MCP 2025-03-26 authorization framework:
- Discovery: /.well-known/oauth-authorization-server
- Dynamic Client Registration: POST /oauth/register
- Authorization: GET /oauth/authorize (consent redirect)
- Token: POST /oauth/token (code exchange + refresh)
- Revocation: POST /oauth/revoke
"""

from __future__ import annotations

import base64
import hashlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.mcp.oauth.store import (
    InMemoryOAuthStore,
    OAuthStore,
    generate_auth_code,
    generate_client_credentials,
    issue_access_token,
    issue_refresh_token,
)
from stronghold.mcp.oauth.types import AuthorizationCode, OAuthClient

logger = logging.getLogger("stronghold.mcp.oauth")

router = APIRouter()

# Module-level store — replaced by DI in production
_store: OAuthStore = InMemoryOAuthStore()


def set_oauth_store(store: OAuthStore) -> None:
    global _store
    _store = store


def get_oauth_store() -> OAuthStore:
    return _store


# ── Discovery ────────────────────────────────────────────────────────


@router.get("/.well-known/oauth-authorization-server")
async def oauth_discovery(request: Request) -> JSONResponse:
    """RFC 8414 authorization server metadata."""
    base = str(request.base_url).rstrip("/")
    return JSONResponse(
        {
            "issuer": base,
            "authorization_endpoint": f"{base}/oauth/authorize",
            "token_endpoint": f"{base}/oauth/token",
            "registration_endpoint": f"{base}/oauth/register",
            "revocation_endpoint": f"{base}/oauth/revoke",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["tools", "prompts", "resources"],
            "service_documentation": f"{base}/docs",
        }
    )


# ── Dynamic Client Registration (RFC 7591) ───────────────────────────


@router.post("/oauth/register")
async def register_client(request: Request) -> JSONResponse:
    """Register a new MCP client dynamically."""
    body = await request.json()
    client_name = body.get("client_name", "")
    redirect_uris = body.get("redirect_uris", [])

    if not redirect_uris:
        raise HTTPException(400, "redirect_uris required")

    client_id, client_secret = generate_client_credentials()
    secret_hash = hashlib.sha256(client_secret.encode()).hexdigest()

    client = OAuthClient(
        client_id=client_id,
        client_secret_hash=secret_hash,
        client_name=client_name,
        redirect_uris=redirect_uris,
        grant_types=body.get("grant_types", ["authorization_code", "refresh_token"]),
        response_types=body.get("response_types", ["code"]),
        token_endpoint_auth_method=body.get("token_endpoint_auth_method", "client_secret_post"),
        scope=body.get("scope", "tools prompts resources"),
    )
    await _store.register_client(client)

    logger.info(
        "Registered MCP client (name=%s, redirect_uris=%d)",
        client_name,
        len(redirect_uris),
    )
    return JSONResponse(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "client_name": client_name,
            "redirect_uris": redirect_uris,
            "grant_types": client.grant_types,
            "response_types": client.response_types,
            "token_endpoint_auth_method": client.token_endpoint_auth_method,
            "scope": client.scope,
        },
        status_code=201,
    )


# ── Authorization (consent) ──────────────────────────────────────────


@router.get("/oauth/authorize")
async def authorize(request: Request) -> JSONResponse:
    """Authorization endpoint — issue an auth code after consent.

    In production, this redirects to a consent UI. For now, it auto-approves
    and returns the code directly (suitable for testing and CLI clients).
    """
    params = dict(request.query_params)
    client_id = params.get("client_id", "")
    redirect_uri = params.get("redirect_uri", "")
    code_challenge = params.get("code_challenge", "")
    code_challenge_method = params.get("code_challenge_method", "S256")
    scope = params.get("scope", "tools prompts resources")
    state = params.get("state", "")

    if code_challenge_method != "S256":
        raise HTTPException(400, "Only S256 code_challenge_method is supported")

    if not code_challenge:
        raise HTTPException(400, "PKCE code_challenge required (OAuth 2.1)")

    client = await _store.get_client(client_id)
    if client is None:
        raise HTTPException(400, "Unknown client_id")

    if redirect_uri not in client.redirect_uris:
        raise HTTPException(400, "redirect_uri not registered for this client")

    # Auto-approve for now (production: redirect to consent UI)
    # The user_id/tenant_id would come from the session in production
    user_id = params.get("user_id", "demo-user")
    tenant_id = params.get("tenant_id", "demo-tenant")

    code = generate_auth_code()
    auth_code = AuthorizationCode(
        code=code,
        client_id=client_id,
        user_id=user_id,
        tenant_id=tenant_id,
        redirect_uri=redirect_uri,
        scope=scope,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    await _store.store_auth_code(auth_code)

    logger.info("Issued auth code for client=%s user=%s", client_id, user_id)
    return JSONResponse(
        {
            "code": code,
            "state": state,
            "redirect_uri": redirect_uri,
        }
    )


# ── Token exchange ───────────────────────────────────────────────────


def _verify_pkce(code_verifier: str, code_challenge: str) -> bool:
    """Verify S256 PKCE challenge."""
    digest = hashlib.sha256(code_verifier.encode()).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return computed == code_challenge


@router.post("/oauth/token")
async def token_exchange(request: Request) -> JSONResponse:
    """Exchange auth code for tokens, or refresh an access token."""
    form = await request.form()
    grant_type = form.get("grant_type", "")

    if grant_type == "authorization_code":
        return await _handle_code_exchange(form)
    elif grant_type == "refresh_token":
        return await _handle_refresh(form)
    else:
        raise HTTPException(400, f"Unsupported grant_type: {grant_type}")


async def _handle_code_exchange(form: Any) -> JSONResponse:
    code = str(form.get("code", ""))
    code_verifier = str(form.get("code_verifier", ""))
    client_id = str(form.get("client_id", ""))
    redirect_uri = str(form.get("redirect_uri", ""))

    if not code_verifier:
        raise HTTPException(400, "code_verifier required (PKCE)")

    auth_code = await _store.consume_auth_code(code)
    if auth_code is None:
        raise HTTPException(400, "Invalid or expired authorization code")

    if auth_code.client_id != client_id:
        raise HTTPException(400, "client_id mismatch")

    if auth_code.redirect_uri != redirect_uri:
        raise HTTPException(400, "redirect_uri mismatch")

    if not _verify_pkce(code_verifier, auth_code.code_challenge):
        raise HTTPException(400, "PKCE verification failed")

    # Issue tokens
    access_value, access_token = issue_access_token(
        client_id=auth_code.client_id,
        user_id=auth_code.user_id,
        tenant_id=auth_code.tenant_id,
        scope=auth_code.scope,
    )
    refresh_value, refresh_token = issue_refresh_token(
        client_id=auth_code.client_id,
        user_id=auth_code.user_id,
        tenant_id=auth_code.tenant_id,
        scope=auth_code.scope,
    )
    await _store.store_token(access_token)
    await _store.store_token(refresh_token)

    logger.info(
        "OAuth issuance complete client=%s user=%s",
        auth_code.client_id,
        auth_code.user_id,
    )
    return JSONResponse(
        {
            "access_token": access_value,
            "token_type": "Bearer",
            "expires_in": 900,  # 15 minutes
            "refresh_token": refresh_value,
            "scope": auth_code.scope,
        }
    )


async def _handle_refresh(form: Any) -> JSONResponse:
    refresh_token_value = str(form.get("refresh_token", ""))
    client_id = str(form.get("client_id", ""))

    claims = await _store.validate_token(refresh_token_value)
    if claims is None or claims.token_type != "refresh":
        raise HTTPException(400, "Invalid or expired refresh token")

    if claims.client_id != client_id:
        raise HTTPException(400, "client_id mismatch")

    # Rotate: revoke old refresh token, issue new pair
    await _store.revoke_token(refresh_token_value)

    access_value, access_token = issue_access_token(
        client_id=claims.client_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        scope=claims.scope,
    )
    new_refresh_value, new_refresh_token = issue_refresh_token(
        client_id=claims.client_id,
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        scope=claims.scope,
    )
    await _store.store_token(access_token)
    await _store.store_token(new_refresh_token)

    return JSONResponse(
        {
            "access_token": access_value,
            "token_type": "Bearer",
            "expires_in": 900,
            "refresh_token": new_refresh_value,
            "scope": claims.scope,
        }
    )


# ── Token revocation (RFC 7009) ──────────────────────────────────────


@router.post("/oauth/revoke")
async def revoke_token(request: Request) -> JSONResponse:
    """Revoke an access or refresh token."""
    form = await request.form()
    token = str(form.get("token", ""))

    if not token:
        raise HTTPException(400, "token required")

    await _store.revoke_token(token)
    return JSONResponse({"revoked": True})
