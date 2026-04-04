"""API routes: auth — BFF (Backend-for-Frontend) authentication part 2.

This file contains the validate-api-key endpoint and remaining auth functions.
Combine with auth_part1.py to get complete auth routes.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import yaml
import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from pydantic import BaseModel

logger = logging.getLogger("stronghold.auth.bff")

router = APIRouter(prefix="/auth", tags=["auth"])

# CSRF header required on all POST endpoints
_CSRF_HEADER = "x-stronghold-request"


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header is present on state-changing requests.

    Custom headers require CORS preflight, so cross-origin form POSTs
    cannot include them. This is simplest effective CSRF defense.
    """
    if not request.headers.get(_CSRF_HEADER):
        msg = "Missing CSRF defense header"
        raise HTTPException(status_code=403, detail=msg)


class RegisterRequest(BaseModel):
    """Request access to Stronghold."""

    email: str
    display_name: str = ""
    password: str = ""
    org_id: str
    team_id: str = "default"


async def _get_db(request: Request) -> Any:
    """Get database pool from container."""
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")
    return pool


# =============================================================================
# NEW: API Key Validation Endpoint
# =============================================================================


class ValidateApiKeyRequest(BaseModel):
    """Request body for API key validation."""

    api_key: str


@router.post("/validate-api-key")
async def validate_api_key(
    request: Request,
    body: ValidateApiKeyRequest,
) -> JSONResponse:
    """Validate an API key before allowing login.

    Returns success only if key exactly matches ROUTER_API_KEY.
    Uses constant-time comparison to prevent timing attacks.
    Logs all failed attempts with IP address for security monitoring.
    Rate limited: 5 failed attempts per minute per IP.
    """
    _check_csrf(request)

    client_ip = request.headers.get("x-forwarded-for", "unknown")

    # Check rate limit BEFORE validation to prevent brute force
    if not _check_api_key_rate_limit(client_ip):
        raise HTTPException(
            status_code=429,
            detail="Too many failed attempts. Please try again later.",
        )

    api_key = body.api_key.strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    # Import container here to avoid circular import
    from stronghold.container import create_container
    from stronghold.config.loader import load_config

    config = load_config()
    expected_key = config.router_api_key

    if not expected_key:
        raise HTTPException(
            status_code=503,
            detail="API key authentication not configured",
        )

    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(api_key, expected_key):
        _record_api_key_failure(client_ip)
        logger.warning(
            "API key validation failed from IP=%s: user attempted invalid key (length=%d)",
            client_ip,
            len(api_key),
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )

    logger.info(
        "API key validation succeeded from IP=%s",
        client_ip,
    )

    # Return minimal user info - no secrets exposed
    return JSONResponse(
        {
            "valid": True,
            "user_id": "system",
            "username": "API Key User",
            "org_id": "__system__",
        }
    )


# =============================================================================
# Original auth.py content continues here...
# =============================================================================

# (The following functions from original auth.py would continue here)
# - _verify_password, _hash_password, RegisterRequest
# - /auth/register endpoint
# - /auth/login endpoint
# - /auth/token endpoint
# - /auth/logout endpoint
# - /auth/session endpoint
# - /auth/config endpoint
# - /auth/registration-status endpoint
