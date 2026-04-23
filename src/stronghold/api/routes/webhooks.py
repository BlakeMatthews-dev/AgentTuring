"""Webhook endpoints for n8n and external workflow tools.

Accepts POST requests with secret in the Authorization: Bearer header
and org identity in the X-Webhook-Org header. Timestamp replay protection
via X-Webhook-Timestamp (must be within 5 minutes) plus nonce-based
deduplication via X-Webhook-Nonce.
"""

from __future__ import annotations

import hmac
import logging
import threading
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.types.errors import QuotaExhaustedError

logger = logging.getLogger("stronghold.api.webhooks")

router = APIRouter(prefix="/v1/webhooks")

_MAX_TIMESTAMP_AGE_SECONDS = 300  # 5 minutes

# Valid execution modes for the /gate endpoint
_VALID_GATE_MODES = frozenset({"best_effort", "persistent", "supervised"})

# --- Nonce tracking (C8: replay prevention) ---
_nonce_lock = threading.Lock()
_seen_nonces: dict[str, float] = {}  # nonce -> expiry timestamp
_NONCE_TTL_SECONDS = _MAX_TIMESTAMP_AGE_SECONDS  # same 5-minute window


def _prune_expired_nonces() -> None:
    """Remove expired nonces. Caller must hold _nonce_lock."""
    now = time.monotonic()
    expired = [k for k, v in _seen_nonces.items() if v <= now]
    for k in expired:
        del _seen_nonces[k]


def _check_and_record_nonce(nonce: str) -> bool:
    """Return True if nonce is fresh (not seen before). Records it with TTL."""
    with _nonce_lock:
        _prune_expired_nonces()
        if nonce in _seen_nonces:
            return False
        _seen_nonces[nonce] = time.monotonic() + _NONCE_TTL_SECONDS
        return True


def _validate_webhook_auth(request: Request, config_secret: str) -> str:
    """Validate webhook secret from Authorization header + timestamp + nonce.

    Returns the org_id from the X-Webhook-Org header.
    """
    if not config_secret:
        msg = "Webhook endpoint not configured (no STRONGHOLD_WEBHOOK_SECRET)"
        raise HTTPException(status_code=503, detail=msg)

    # --- Bearer token ---
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization: Bearer header")

    token = auth_header[len("Bearer ") :]
    if not token or not hmac.compare_digest(token, config_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    # --- Timestamp replay protection ---
    ts_header = request.headers.get("X-Webhook-Timestamp", "")
    if not ts_header:
        raise HTTPException(status_code=400, detail="Missing X-Webhook-Timestamp header")

    try:
        ts = float(ts_header)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=400, detail="X-Webhook-Timestamp must be a numeric epoch"
        ) from None

    age = abs(time.time() - ts)
    if age > _MAX_TIMESTAMP_AGE_SECONDS:
        raise HTTPException(
            status_code=401,
            detail=f"Webhook timestamp too old ({int(age)}s > {_MAX_TIMESTAMP_AGE_SECONDS}s)",
        )

    # --- Nonce deduplication (C8) ---
    nonce = request.headers.get("X-Webhook-Nonce", "").strip()
    if not nonce:
        # Fall back to timestamp as nonce -- still prevents replaying the
        # exact same timestamp within the TTL window.  Callers SHOULD send
        # a unique X-Webhook-Nonce for stronger deduplication.
        nonce = f"ts:{ts_header}"
        logger.info(
            "No X-Webhook-Nonce header; falling back to timestamp-derived nonce. "
            "Callers should send X-Webhook-Nonce for full replay protection."
        )

    if not _check_and_record_nonce(nonce):
        raise HTTPException(status_code=409, detail="Duplicate nonce (possible replay)")

    # --- Org identity (C7) ---
    org_id = request.headers.get("X-Webhook-Org", "").strip()
    if not org_id:
        raise HTTPException(status_code=400, detail="Missing X-Webhook-Org header")

    # If the config specifies an expected org, verify the header matches
    _raw_org = getattr(request.app.state.container.config, "webhook_org_id", "")
    expected_org: str = _raw_org if isinstance(_raw_org, str) else ""
    if expected_org:
        if org_id != expected_org:
            logger.warning(
                "Webhook org mismatch: header=<redacted> expected=<redacted> (rejecting)"
            )
            raise HTTPException(
                status_code=403,
                detail="X-Webhook-Org does not match configured webhook_org_id",
            )
    else:
        # No pinned org configured -- log for audit visibility
        logger.warning(
            "No webhook_org_id configured; accepting X-Webhook-Org=<redacted> at face value. "
            "Set STRONGHOLD_WEBHOOK_ORG_ID to pin the expected org."
        )

    return org_id


def _build_webhook_auth(org_id: str) -> Any:
    """Build an AuthContext for a webhook caller (SERVICE_ACCOUNT kind)."""
    from stronghold.types.auth import AuthContext, IdentityKind  # noqa: PLC0415

    return AuthContext(
        user_id="webhook",
        username="webhook",
        org_id=org_id,
        roles=frozenset({"user"}),
        kind=IdentityKind.SERVICE_ACCOUNT,
        auth_method="webhook",
    )


@router.post("/chat")
async def webhook_chat(request: Request) -> JSONResponse:
    """Process a chat message via webhook (n8n-compatible).

    Headers:
        Authorization: Bearer {webhook_secret}
        X-Webhook-Timestamp: <unix epoch seconds>
        X-Webhook-Org: <org_id>
        X-Webhook-Nonce: <unique request id>

    Body: {
        "message": "What's the weather?",
        "session_id": "n8n-workflow-123",  # optional
        "intent": "search"                # optional hint
    }
    """
    container = request.app.state.container
    org_id = _validate_webhook_auth(request, container.config.webhook_secret)
    auth = _build_webhook_auth(org_id)

    # Rate limiting (if available on container)
    if hasattr(container, "rate_limiter") and container.rate_limiter is not None:
        rate_key = f"webhook:{org_id}"
        allowed, _headers = await container.rate_limiter.check(rate_key)
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        await container.rate_limiter.record(rate_key)

    body: dict[str, Any] = await request.json()

    message = body.get("message", "")
    if not message:
        raise HTTPException(status_code=400, detail="'message' is required")

    session_id = body.get("session_id")
    intent = body.get("intent", "")

    # Gate: sanitize + Warden scan + strike tracking (C6 — same as main chat endpoint)
    gate_result = await container.gate.process_input(
        message,
        execution_mode="best_effort",
        auth=auth,
    )

    if gate_result.blocked:
        status = 403 if gate_result.account_disabled or gate_result.locked_until else 400
        return JSONResponse(
            status_code=status,
            content={
                "error": gate_result.block_reason,
                "flags": list(gate_result.warden_verdict.flags),
                "strike": gate_result.strike_number,
            },
        )

    # Route through pipeline with proper webhook auth context
    messages = [{"role": "user", "content": message}]
    try:
        result = await container.route_request(
            messages,
            auth=auth,
            session_id=session_id,
            intent_hint=intent,
        )
    except QuotaExhaustedError as e:
        raise HTTPException(status_code=429, detail=e.detail) from e

    # Extract response content
    choices = result.get("choices", [])
    content = choices[0].get("message", {}).get("content", "") if choices else ""
    routing = result.get("_routing", {})

    return JSONResponse(
        content={
            "response": content,
            "agent": routing.get("agent", ""),
            "intent": routing.get("intent", {}).get("task_type", ""),
            "model": routing.get("model", ""),
        }
    )


@router.post("/gate")
async def webhook_gate(request: Request) -> JSONResponse:
    """Run content through Gate security scan (n8n-compatible).

    Headers:
        Authorization: Bearer {webhook_secret}
        X-Webhook-Timestamp: <unix epoch seconds>
        X-Webhook-Org: <org_id>
        X-Webhook-Nonce: <unique request id>

    Body: {
        "content": "Text to scan",
        "mode": "best_effort"     # optional: best_effort | persistent | supervised
    }
    """
    container = request.app.state.container
    org_id = _validate_webhook_auth(request, container.config.webhook_secret)
    auth = _build_webhook_auth(org_id)

    # Rate limiting (if available on container)
    if hasattr(container, "rate_limiter") and container.rate_limiter is not None:
        rate_key = f"webhook:{org_id}"
        allowed, _headers = await container.rate_limiter.check(rate_key)
        if not allowed:
            raise HTTPException(status_code=429, detail="Rate limit exceeded")
        await container.rate_limiter.record(rate_key)

    body: dict[str, Any] = await request.json()

    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="'content' is required")

    mode = body.get("mode", "best_effort")

    # Validate mode against known execution modes
    if mode not in _VALID_GATE_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode {mode!r}; must be one of: {', '.join(sorted(_VALID_GATE_MODES))}",
        )

    gate_result = await container.gate.process_input(content, execution_mode=mode, auth=auth)

    return JSONResponse(
        content={
            "sanitized": gate_result.sanitized_text,
            "blocked": gate_result.blocked,
            "block_reason": gate_result.block_reason,
            "flags": list(gate_result.warden_verdict.flags),
            "safe": gate_result.warden_verdict.clean and not gate_result.blocked,
        }
    )
