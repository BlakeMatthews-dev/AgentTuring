"""Gate endpoint: sanitize + improve + clarify.

For persistent/supervised mode, uses LLM to rewrite the request
and generate clarifying questions. For best_effort, just sanitizes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/stronghold")


@router.post("/gate")
async def process_gate(request: Request) -> JSONResponse:
    """Process input through the Gate.

    Body:
    {
        "content": "the user's raw input",
        "mode": "best_effort" | "persistent" | "supervised"
    }

    Returns:
    {
        "sanitized": "cleaned input",
        "improved": "LLM-rewritten version (persistent/supervised only)",
        "questions": [{"question": "...", "options": ["a","b","c","d"]}],
        "blocked": false
    }
    """
    container = request.app.state.container

    # Auth
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")
    mode = body.get("mode", "best_effort")

    # Run through Gate (sanitize + Warden + strike tracking)
    gate_result = await container.gate.process_input(
        content,
        execution_mode=mode,
        auth=auth_ctx,
    )
    sanitized = gate_result.sanitized_text

    if gate_result.blocked:
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

    # 3. For best_effort: return sanitized only
    if mode == "best_effort":
        return JSONResponse(
            content={
                "sanitized": sanitized,
                "improved": None,
                "questions": [],
                "blocked": False,
            }
        )

    # 4. For persistent/supervised: try LLM improvement
    improved = sanitized
    questions: list[dict[str, Any]] = []

    try:
        improve_prompt = (
            "You are a request improvement assistant. "
            "The user submitted the following request. "
            "Rewrite it to be clearer, more specific, and more actionable. "
            "Then generate 1-3 clarifying questions that would help "
            "produce a better result. Format each question with "
            "options a, b, c, d.\n\n"
            f"User request: {sanitized}\n\n"
            "Respond in this exact JSON format:\n"
            '{"improved": "the rewritten request", '
            '"questions": [{"question": "...", '
            '"options": ["a) ...", "b) ...", "c) ...", "d) ..."]}]}'
        )

        result = await container.llm.complete(
            [{"role": "user", "content": improve_prompt}],
            "mistral/mistral-large-latest",
            temperature=0.3,
            max_tokens=500,
        )
        llm_content = result.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Try to parse JSON from LLM response
        import json

        # Find JSON in the response and clean control characters
        json_start = llm_content.find("{")
        json_end = llm_content.rfind("}") + 1
        if json_start >= 0 and json_end > json_start:
            json_str = llm_content[json_start:json_end]
            # Clean control characters that LLMs sometimes embed
            json_str = json_str.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
            parsed = json.loads(json_str)
            improved_candidate = parsed.get("improved", sanitized)
            questions = parsed.get("questions", [])

            # Re-scan LLM output through Warden (LLM output is untrusted)
            rescan_verdict = await container.warden.scan(improved_candidate, "user_input")
            if rescan_verdict.clean:
                improved = improved_candidate
            else:
                import logging as _log  # noqa: PLC0415

                _log.getLogger("stronghold.gate").warning(
                    "Gate LLM output blocked by Warden rescan: %s",
                    rescan_verdict.flags,
                )
                # Fall back to original sanitized input
    except Exception as exc:  # noqa: BLE001
        # LLM unavailable or parse failed — return sanitized as improved
        import logging

        logging.getLogger("stronghold.gate").warning("Gate LLM improvement failed: %s", exc)

    return JSONResponse(
        content={
            "sanitized": sanitized,
            "improved": improved,
            "questions": questions,
            "blocked": False,
        }
    )
