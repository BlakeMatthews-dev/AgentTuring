"""Chat completions endpoint.

The API route is THIN. It authenticates, validates, and delegates to the Conduit.
Nothing here calls LiteLLM directly. Only agents touch LLM.

Gate handles sanitization + Warden scan + sufficiency check.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.types.errors import QuotaExhaustedError

logger = logging.getLogger("stronghold.api.chat")

router = APIRouter()


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    """OpenAI-compatible chat completions via the agent pipeline."""
    container = request.app.state.container

    # 1. Auth (pass headers for OpenWebUI user extraction)
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    messages: list[dict[str, Any]] = body.get("messages", [])
    raw_session_id: str | None = body.get("session_id")
    execution_mode: str = body.get("execution_mode", "best_effort")
    intent_hint: str = body.get("intent_hint", "") or body.get("intent", "")

    # Validate and scope session_id to caller's org
    from stronghold.sessions.store import validate_and_build_session_id  # noqa: PLC0415

    try:
        session_id = validate_and_build_session_id(
            raw_session_id,
            org_id=auth_ctx.org_id,
            team_id=auth_ctx.team_id,
            user_id=auth_ctx.user_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # 2. Gate: sanitize + Warden scan + sufficiency check
    user_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                user_text = content
            elif isinstance(content, list):
                user_text = " ".join(
                    p.get("text", "")
                    for p in content
                    if isinstance(p, dict) and p.get("type") == "text"
                )
            break

    gate_result = await container.gate.process_input(
        user_text,
        execution_mode=execution_mode,
        auth=auth_ctx,
    )

    if gate_result.blocked:
        # Determine HTTP status: 403 for lockout/disabled, 400 for violations
        status = 403 if gate_result.account_disabled or gate_result.locked_until else 400
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "message": gate_result.block_reason,
                    "type": "security_violation",
                    "code": "BLOCKED_BY_GATE",
                    "strike": {
                        "number": gate_result.strike_number,
                        "max": 3,
                        "scrutiny_level": gate_result.scrutiny_level,
                        "locked_until": gate_result.locked_until,
                        "account_disabled": gate_result.account_disabled,
                    },
                    "flags": list(gate_result.warden_verdict.flags),
                    "appeal_endpoint": "/v1/stronghold/appeals",
                }
            },
        )

    if gate_result.clarifying_questions:
        return JSONResponse(
            content={
                "id": "stronghold-clarify",
                "object": "chat.completion",
                "model": "gate",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": gate_result.clarifying_questions[0].question,
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {},
                "_gate": {
                    "execution_mode": execution_mode,
                    "questions": [q.question for q in gate_result.clarifying_questions],
                },
            }
        )

    # 3. Route through the Conduit — this is where agents, LLM, memory all happen
    try:
        result = await container.route_request(
            messages,
            auth=auth_ctx,
            session_id=session_id,
            intent_hint=intent_hint,
        )
    except QuotaExhaustedError as e:
        raise HTTPException(status_code=429, detail=e.detail) from e
    except Exception as e:
        logger.exception("Agent pipeline error: %s", e)
        raise HTTPException(status_code=502, detail="Agent pipeline error") from e

    return JSONResponse(content=result)
