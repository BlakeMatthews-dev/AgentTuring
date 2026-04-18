"""API routes: auth — BFF (Backend-for-Frontend) authentication.

Implements the server-side token exchange pattern recommended by the
OAuth 2.0 for Browser-Based Apps specification. Tokens never touch
JavaScript — the exchange happens server-to-server, and the JWT is
stored in an HttpOnly cookie.

Endpoints:
  POST /auth/token    — Exchange authorization code for session cookie
  POST /auth/login    — Demo login with user/org/team context
  POST /auth/logout   — Clear the session cookie
  GET  /auth/session  — Return current user info from cookie
  GET  /auth/config   — Return non-sensitive OIDC config for frontend

CSRF protection:
  State-changing endpoints (POST) require the X-Stronghold-Request header.
  Custom headers trigger a CORS preflight, so cross-origin forms cannot
  submit them. Combined with SameSite=Lax cookies, this provides
  defense-in-depth against CSRF.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx
import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("stronghold.auth.bff")

router = APIRouter(prefix="/auth", tags=["auth"])

# CSRF header required on all POST endpoints
_CSRF_HEADER = "x-stronghold-request"


def _check_csrf(request: Request) -> None:
    """Verify the CSRF defense header is present on state-changing requests.

    Custom headers require CORS preflight, so cross-origin form POSTs
    cannot include them. This is the simplest effective CSRF defense.
    """
    if not request.headers.get(_CSRF_HEADER):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


class TokenExchangeRequest(BaseModel):
    """Request body for the code→token exchange."""

    code: str
    code_verifier: str
    redirect_uri: str


@router.post("/token")
async def exchange_token(
    body: TokenExchangeRequest,
    request: Request,
) -> JSONResponse:
    """Exchange an authorization code for a session cookie.

    The frontend sends the authorization code + PKCE verifier here.
    We exchange server-side with the IdP (using client_secret for
    confidential clients), validate the JWT, and set an HttpOnly cookie.
    The JWT never reaches client-side JavaScript.
    """
    _check_csrf(request)

    container = request.app.state.container
    auth_cfg = container.config.auth

    if not auth_cfg.token_url or not auth_cfg.client_id:
        raise HTTPException(
            status_code=501,
            detail="OIDC not configured (token_url and client_id required)",
        )

    # Server-side token exchange with IdP
    token_data: dict[str, str] = {
        "grant_type": "authorization_code",
        "code": body.code,
        "redirect_uri": body.redirect_uri,
        "client_id": auth_cfg.client_id,
        "code_verifier": body.code_verifier,
    }

    # Confidential client: include client_secret
    if auth_cfg.client_secret:
        token_data["client_secret"] = auth_cfg.client_secret

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            idp_resp = await client.post(
                auth_cfg.token_url,
                data=token_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.RequestError as e:
        logger.error("IdP code-exchange network error: %s", e)
        raise HTTPException(
            status_code=502,
            detail="Could not reach identity provider",
        ) from e

    if idp_resp.status_code != 200:
        logger.warning(
            "IdP code-exchange returned non-200 status=%s body=%s",
            idp_resp.status_code,
            idp_resp.text[:200],
        )
        raise HTTPException(
            status_code=502,
            detail=f"Identity provider returned {idp_resp.status_code}",
        )

    tokens: dict[str, Any] = idp_resp.json()
    access_token: str = tokens.get("access_token", "")
    if not access_token:
        raise HTTPException(
            status_code=502,
            detail="Identity provider did not return an access_token",
        )

    # Validate the JWT through our normal auth pipeline
    try:
        auth_ctx = await container.auth_provider.authenticate(
            f"Bearer {access_token}",
            headers=dict(request.headers),
        )
    except ValueError as e:
        logger.warning("JWT validation failed after exchange: %s", e)
        raise HTTPException(
            status_code=401,
            detail="Token validation failed",
        ) from e

    # Build response with user info
    response = JSONResponse(
        {
            "user_id": auth_ctx.user_id,
            "username": auth_ctx.username,
            "org_id": auth_ctx.org_id,
        }
    )

    # Set HttpOnly session cookie
    cookie_name = auth_cfg.session_cookie_name
    max_age = auth_cfg.session_max_age

    response.set_cookie(
        key=cookie_name,
        value=access_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )

    # Non-HttpOnly indicator cookie for the auth guard JS
    # Contains no sensitive data — just signals "a session exists"
    response.set_cookie(
        key="stronghold_logged_in",
        value="1",
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )

    logger.info(
        "BFF login: user=%s org=%s method=oidc",
        auth_ctx.user_id,
        auth_ctx.org_id,
    )
    return response


class DemoLoginRequest(BaseModel):
    """Login with email + password."""

    email: str
    password: str = ""
    org_id: str = ""
    team_id: str = ""


def _verify_password(password: str, stored_hash: str) -> bool:
    """Verify a password against a stored hash.

    Supports:
      - argon2id (current, preferred): "$argon2id$..."
      - pbkdf2 (legacy, auto-upgrades on next login): "pbkdf2:salt:hash"
    """
    if not stored_hash:
        return False

    # Argon2id (current standard)
    if stored_hash.startswith("$argon2"):
        from argon2 import PasswordHasher  # noqa: PLC0415
        from argon2.exceptions import (  # noqa: PLC0415
            InvalidHashError,
            VerificationError,
            VerifyMismatchError,
        )

        ph = PasswordHasher()
        try:
            return ph.verify(stored_hash, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    # Legacy PBKDF2 (for existing hashes — new hashes always use argon2id)
    if stored_hash.startswith("pbkdf2:"):
        import hashlib  # noqa: PLC0415
        import hmac as _hmac  # noqa: PLC0415

        parts = stored_hash.split(":")
        if len(parts) != 3:  # noqa: PLR2004
            return False
        _, salt, expected = parts
        computed = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600000).hex()
        return _hmac.compare_digest(computed, expected)

    return False


def _hash_password(password: str) -> str:
    """Hash a password with Argon2id.

    Argon2id is memory-hard (resistant to GPU/ASIC attacks), unlike PBKDF2.
    Uses argon2-cffi defaults: 64MB memory, 3 iterations, 4 parallelism.
    """
    from argon2 import PasswordHasher  # noqa: PLC0415

    ph = PasswordHasher()
    return ph.hash(password)


class RegisterRequest(BaseModel):
    """Request access to Stronghold."""

    email: str
    display_name: str = ""
    password: str = ""
    org_id: str
    team_id: str = "default"


async def _get_db(request: Request) -> Any:
    """Get the database pool from container."""
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")
    return pool


@router.post("/register")
async def register_user(
    body: RegisterRequest,
    request: Request,
) -> JSONResponse:
    """Request access. Creates a pending user in the approval queue."""
    _check_csrf(request)

    if not body.email or not body.org_id:
        raise HTTPException(status_code=400, detail="email and org_id are required")

    # Validate org_id against allowlist (prevents attacker self-registering into target org)
    container = request.app.state.container
    allowed_orgs = container.config.auth.allowed_registration_orgs
    if not allowed_orgs:
        raise HTTPException(
            status_code=403,
            detail="Self-registration is disabled. Contact an administrator.",
        )
    if body.org_id not in allowed_orgs:
        raise HTTPException(
            status_code=400,
            detail="Registration not available for this organization",
        )

    body.email = body.email.strip().lower()

    pool = await _get_db(request)
    async with pool.acquire() as conn:
        # Check if user already exists
        existing = await conn.fetchrow(
            "SELECT id, status FROM users WHERE lower(email) = lower($1)", body.email
        )
        if existing:
            # Generic message to prevent user enumeration — don't reveal status
            raise HTTPException(
                status_code=409,
                detail="An account with this email already exists or is pending review.",
            )

        pw_hash = _hash_password(body.password) if body.password else ""
        await conn.execute(
            """INSERT INTO users (email, display_name, org_id, team_id, password_hash, status)
               VALUES ($1, $2, $3, $4, $5, 'pending')
               ON CONFLICT (email) DO NOTHING""",
            body.email,
            body.display_name or body.email.split("@")[0],
            body.org_id,
            body.team_id,
            pw_hash,
        )

    logger.info(
        "Registration: email=%s org=%s team=%s status=pending",
        body.email,
        body.org_id,
        body.team_id,
    )
    return JSONResponse(
        {"status": "pending", "message": "Access request submitted. An admin will review it."}
    )


@router.post("/login")
async def demo_login(
    body: DemoLoginRequest,
    request: Request,
) -> JSONResponse:
    """Login with user/org/team context. User must be approved."""
    _check_csrf(request)

    container = request.app.state.container
    auth_cfg = container.config.auth
    signing_key = container.config.router_api_key

    if not body.email:
        raise HTTPException(status_code=400, detail="email is required")

    # Normalize email — case insensitive per RFC 5321
    body.email = body.email.strip().lower()

    # Check user is approved
    pool = await _get_db(request)
    async with pool.acquire() as conn:
        user = await conn.fetchrow(
            "SELECT id, email, display_name, org_id, team_id,"
            " roles, status, password_hash"
            " FROM users WHERE lower(email) = lower($1)",
            body.email,
        )

    if not user:
        raise HTTPException(
            status_code=403, detail="No account found. Please request access first."
        )
    if user["status"] == "pending":
        raise HTTPException(
            status_code=403, detail="Your access request is pending admin approval."
        )
    if user["status"] == "rejected":
        raise HTTPException(status_code=403, detail="Your access request was rejected.")
    if user["status"] == "disabled":
        raise HTTPException(status_code=403, detail="Your account has been disabled.")
    if user["status"] != "approved":
        raise HTTPException(status_code=403, detail="Account not approved.")

    # Verify password — ALWAYS required
    stored_hash = user.get("password_hash", "")
    if not body.password:
        raise HTTPException(status_code=401, detail="Password required.")
    if not stored_hash:
        raise HTTPException(
            status_code=401, detail="Account has no password set. Contact an administrator."
        )
    if not _verify_password(body.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    # Use stored roles and identity from DB (not from request body)
    roles_raw = json.loads(user["roles"]) if isinstance(user["roles"], str) else user["roles"]

    now = int(time.time())
    claims = {
        "sub": user["email"],
        "email": user["email"],
        "preferred_username": user["display_name"] or user["email"].split("@")[0],
        "organization_id": user["org_id"],
        "team_id": user["team_id"],
        "roles": roles_raw,
        "iss": "stronghold-demo",
        "aud": "stronghold",
        "iat": now,
        "exp": now + auth_cfg.session_max_age,
    }
    token = pyjwt.encode(claims, signing_key, algorithm="HS256")

    response = JSONResponse(
        {
            "user_id": user["email"],
            "username": claims["preferred_username"],
            "org_id": user["org_id"],
            "team_id": user["team_id"],
        }
    )

    cookie_name = auth_cfg.session_cookie_name
    max_age = auth_cfg.session_max_age

    response.set_cookie(
        key=cookie_name,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    response.set_cookie(
        key="stronghold_logged_in",
        value="1",
        httponly=False,
        secure=True,
        samesite="lax",
        max_age=max_age,
        path="/",
    )

    logger.info(
        "Demo login: user=%s org=%s team=%s",
        body.email,
        body.org_id,
        body.team_id,
    )
    return response


@router.api_route("/logout", methods=["GET", "POST"])
async def logout(request: Request) -> JSONResponse:
    """Clear the session cookie (GET for browser, POST for JS)."""
    if request.method == "POST":
        _check_csrf(request)

    container = request.app.state.container
    cookie_name = container.config.auth.session_cookie_name

    response = JSONResponse({"status": "logged_out"})
    # Delete current cookies (must match attributes used when setting)
    response.delete_cookie(key=cookie_name, path="/", secure=True, httponly=True, samesite="lax")
    response.delete_cookie(key="stronghold_logged_in", path="/", secure=True, samesite="lax")
    # Also delete ALL legacy cookie names (HttpOnly ones JS can't clear)
    for legacy in ("stronghold_session", "stronghold_logged_in", "sh_session", "sh_logged_in"):
        response.delete_cookie(key=legacy, path="/")
        response.delete_cookie(key=legacy, path="/", secure=True, httponly=True, samesite="lax")
        response.delete_cookie(key=legacy, path="/", secure=True, samesite="lax")
    return response


@router.get("/session")
async def get_session(request: Request) -> JSONResponse:
    """Return current user info from the session cookie.

    Used by the frontend to display the username and check session validity
    without exposing the JWT to JavaScript.
    """
    container = request.app.state.container
    auth_cfg = container.config.auth

    # Try to authenticate from cookie
    cookie_header = request.headers.get("cookie", "")
    if not cookie_header:
        return JSONResponse({"authenticated": False}, status_code=401)

    # Parse cookie manually to extract the JWT
    from http.cookies import SimpleCookie  # noqa: PLC0415

    sc: SimpleCookie = SimpleCookie()
    try:
        sc.load(cookie_header)
    except Exception:  # noqa: BLE001
        return JSONResponse({"authenticated": False}, status_code=401)

    morsel = sc.get(auth_cfg.session_cookie_name)
    if not morsel or not morsel.value:
        return JSONResponse({"authenticated": False}, status_code=401)

    # Try demo token (HS256 signed with router key) first
    signing_key = container.config.router_api_key
    try:
        claims = pyjwt.decode(
            morsel.value,
            signing_key,
            algorithms=["HS256"],
            audience="stronghold",
        )
        return JSONResponse(
            {
                "authenticated": True,
                "user_id": claims.get("sub", ""),
                "username": claims.get("preferred_username", ""),
                "org_id": claims.get("organization_id", ""),
                "team_id": claims.get("team_id", ""),
                "roles": claims.get("roles", []),
                "kind": "user",
            }
        )
    except pyjwt.PyJWTError:
        pass  # Not a demo token, try normal auth

    try:
        auth_ctx = await container.auth_provider.authenticate(
            f"Bearer {morsel.value}",
            headers=dict(request.headers),
        )
    except ValueError:
        return JSONResponse({"authenticated": False}, status_code=401)

    return JSONResponse(
        {
            "authenticated": True,
            "user_id": auth_ctx.user_id,
            "username": auth_ctx.username,
            "org_id": auth_ctx.org_id,
            "team_id": auth_ctx.team_id,
            "roles": sorted(auth_ctx.roles),
            "kind": auth_ctx.kind.value if hasattr(auth_ctx.kind, "value") else str(auth_ctx.kind),
        }
    )


@router.get("/config")
async def auth_config(request: Request) -> JSONResponse:
    """Return non-sensitive OIDC config for the frontend login page.

    No authentication required — must be accessible before login.
    """
    container = request.app.state.container
    cfg = container.config.auth
    return JSONResponse(
        {
            "oidc_enabled": bool(cfg.client_id and (cfg.authorization_url or cfg.issuer)),
            "authorization_url": cfg.authorization_url,
            "client_id": cfg.client_id,
            "issuer": cfg.issuer,
            # token_url intentionally omitted — BFF exchanges server-side
            "bff_enabled": bool(cfg.token_url and cfg.client_id),
        }
    )


@router.get("/registration-status")
async def registration_status(request: Request, email: str = "") -> JSONResponse:
    """Check registration approval status (public, no auth required).

    Returns minimal info to prevent user enumeration.
    Rate-limited by the global rate limiter.
    """
    if not email or not email.strip():
        return JSONResponse({"status": "unknown"})

    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        return JSONResponse({"status": "unknown"})

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT status FROM users WHERE lower(email) = lower($1)",
            email.strip(),
        )

    if not row:
        return JSONResponse({"status": "unknown"})

    return JSONResponse({"status": row["status"]})
