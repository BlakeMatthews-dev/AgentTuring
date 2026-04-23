"""Streaming structured request endpoint.

Sends SSE progress events as the agent works.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from stronghold.types.errors import QuotaExhaustedError

router = APIRouter(prefix="/v1/stronghold")


@router.post("/request/stream")
async def structured_request_stream(request: Request) -> StreamingResponse:
    """Handle a structured request with SSE progress updates."""
    container = request.app.state.container

    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    goal = body.get("goal", "")
    intent_hint = body.get("intent_hint", "") or body.get("intent", "")
    expected_output = body.get("expected_output", "")
    details = body.get("details", "")
    repo = body.get("repo", "")
    session_id: str | None = body.get("session_id")

    if not goal:
        raise HTTPException(status_code=400, detail="'goal' is required")

    # Build prompt
    prompt_parts = [f"Goal: {goal}"]
    if expected_output:
        prompt_parts.append(f"Expected output: {expected_output}")
    if details:
        prompt_parts.append(f"Details: {details}")
    if repo:
        prompt_parts.append(f"GitHub repository: {repo}")
    user_content = "\n".join(prompt_parts)

    # Warden scan
    warden_verdict = await container.warden.scan(user_content, "user_input")
    if not warden_verdict.clean:

        async def blocked_stream() -> Any:
            yield _sse({"type": "error", "message": f"Blocked: {', '.join(warden_verdict.flags)}"})

        return StreamingResponse(blocked_stream(), media_type="text/event-stream")

    messages: list[dict[str, str]] = [{"role": "user", "content": user_content}]

    # Status queue for progress updates
    status_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

    async def status_cb(msg: str) -> None:
        """Push status updates into the SSE queue."""
        await status_queue.put({"type": "status", "message": msg})

    async def run_agent() -> dict[str, Any]:
        """Run the agent pipeline, posting status updates to the queue."""
        await status_queue.put({"type": "status", "message": "Classifying intent..."})
        try:
            result = await container.route_request(
                messages,
                auth=auth_ctx,
                session_id=session_id,
                intent_hint=intent_hint,
                status_callback=status_cb,
            )
        except QuotaExhaustedError as e:
            await status_queue.put({"type": "error", "message": f"Quota exhausted: {e.detail}"})
            return {
                "choices": [
                    {
                        "message": {
                            "content": f"Request rejected: {e.detail}",
                        }
                    }
                ],
                "_routing": {"error": "quota_exhausted"},
            }
        # Flatten for SSE: JS expects content + _routing at top level
        content = ""
        if result.get("choices"):
            content = result["choices"][0].get("message", {}).get("content", "")
        await status_queue.put(
            {
                "type": "done",
                "content": content,
                "_routing": result.get("_routing", {}),
                "model": result.get("model", ""),
            }
        )
        final: dict[str, Any] = result
        return final

    async def stream_events() -> Any:
        """Yield SSE events: status updates then final result."""
        # Start the agent in background
        task = asyncio.create_task(run_agent())

        # Send initial status
        yield _sse({"type": "status", "message": "Starting..."})

        # Poll for updates
        while not task.done():
            try:
                update = await asyncio.wait_for(status_queue.get(), timeout=1.0)
                yield _sse(update)
                if update.get("type") == "done":
                    return
            except TimeoutError:
                yield _sse({"type": "heartbeat"})

        # Get the result if task completed without posting to queue
        try:
            result = task.result()
            content = ""
            if result.get("choices"):
                content = result["choices"][0].get("message", {}).get("content", "")
            yield _sse(
                {
                    "type": "done",
                    "content": content,
                    "_routing": result.get("_routing", {}),
                    "model": result.get("model", ""),
                }
            )
        except Exception:
            yield _sse({"type": "error", "message": "An error occurred processing the request"})

    return StreamingResponse(stream_events(), media_type="text/event-stream")


def _sse(data: dict[str, Any]) -> str:
    """Format a dict as an SSE event."""
    return f"data: {json.dumps(data)}\n\n"
