"""API routes: auth — BFF (Backend-for-Frontend) authentication.

Implements server-side token exchange pattern recommended by's
OAuth 2.0 for Browser-Based Apps specification. Tokens never touch
JavaScript — exchange happens server-to-server, and JWT is
stored in an HttpOnly cookie.

Endpoints:
  POST /auth/token    — Exchange authorization code for session cookie
  POST /auth/login    — Demo login with user/org/team context
  POST /auth/logout   — Clear session cookie
  GET  /auth/session  — Return current user info from cookie
  GET  /auth/config   — Return non-sensitive OIDC config for frontend
  POST /auth/validate-api-key — Validate API key before login (NEW)

CSRF protection:
  State-changing endpoints (POST) require X-Stronghold-Request header.
  Custom headers trigger a CORS preflight, so cross-origin forms cannot
  submit them. Combined with SameSite=Lax cookies, this provides
  defense-in-depth against CSRF.
"""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from typing import Any

import httpx
import jwt as pyjwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, HTMLResponse, Response
from pydantic import BaseModel

logger = logging.getLogger("stronghold.auth.bff")

router = APIRouter(prefix="/auth", tags=["auth"])

# CSRF header required on all POST endpoints
_CSRF_HEADER = "x-stronghold-request"

# In-memory rate limiting for API key validation (5 failed attempts per minute per IP)
_api_key_rate_limits: dict[str, list[float]] = defaultdict(list)


def _check_api_key_rate_limit(ip_address: str) -> bool:
    """Check if IP has exceeded rate limit for API key validation.

    Allows 5 failed attempts per minute per IP address.
    Returns True if allowed, False if rate limit exceeded.
    Only counts failed attempts (recorded by caller after validation fails).
    """
    current_time = time.time()
    minute_ago = current_time - 60

    # Remove entries older than 1 minute
    _api_key_rate_limits[ip_address] = [
        timestamp for timestamp in _api_key_rate_limits[ip_address] if timestamp > minute_ago
    ]

    # Check if under limit (5 attempts per minute)
    if len(_api_key_rate_limits[ip_address]) < 5:
        return True

    logger.warning(
        "API key rate limit exceeded for IP=%s: %d attempts in last minute",
        ip_address,
        len(_api_key_rate_limits[ip_address]),
    )
    return False


def _record_api_key_failure(ip_address: str) -> None:
    """Record a failed API key validation attempt for rate limiting."""
    current_time = time.time()
    _api_key_rate_limits[ip_address].append(current_time)
