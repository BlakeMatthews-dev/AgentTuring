"""Task management endpoints.

For async/long-running requests:
- POST /v1/stronghold/tasks — submit a task
- GET /v1/stronghold/tasks/{id} — check status
- GET /v1/stronghold/tasks — list tasks

All endpoints require authentication and are org-scoped.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/stronghold/tasks")


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header on cookie-authenticated mutations.

    CSRF only applies when auth is via cookies (browser session).
    Bearer token auth and unauthenticated requests are not CSRF-vulnerable.
    """
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.headers.get("authorization"):
        return  # Bearer token — not CSRF-vulnerable
    # Only enforce CSRF when a session cookie is present (browser auth)
    if not request.cookies:
        return  # No cookies = not a browser session, auth will reject
    if not request.headers.get("x-stronghold-request"):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


async def _authenticate(request: Request) -> tuple[Any, Any]:
    """Authenticate and return (auth, container). CSRF checked after auth."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    _check_csrf(request)
    return auth, container


@router.post("")
async def submit_task(request: Request) -> JSONResponse:
    """Submit a task for async processing by a worker."""
    auth, container = await _authenticate(request)

    body: dict[str, Any] = await request.json()
    goal = body.get("goal", "")
    intent = body.get("intent", "")
    model = body.get("model", "auto")

    if not goal:
        raise HTTPException(status_code=400, detail="'goal' is required")

    # Warden scan
    warden_verdict = await container.warden.scan(goal, "user_input")
    if not warden_verdict.clean:
        raise HTTPException(
            status_code=400,
            detail=f"Blocked: {', '.join(warden_verdict.flags)}",
        )

    # Submit to queue with org context
    task_id = await container.task_queue.submit(
        {
            "messages": [{"role": "user", "content": goal}],
            "intent": intent,
            "model": model,
            "agent": intent or "auto",
            "user_id": auth.user_id,
            "org_id": auth.org_id,
        }
    )

    return JSONResponse(
        status_code=202,
        content={"task_id": task_id, "status": "pending"},
    )


@router.get("/{task_id}")
async def get_task(task_id: str, request: Request) -> JSONResponse:
    """Get task status and result (org-scoped)."""
    auth, container = await _authenticate(request)
    task = await container.task_queue.get(task_id)

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    # Org isolation: reject if task doesn't belong to caller's org
    task_org = task.get("payload", {}).get("org_id", "")
    if auth.org_id and task_org and task_org != auth.org_id:
        raise HTTPException(status_code=404, detail="Task not found")

    return JSONResponse(
        content={
            "task_id": task["id"],
            "status": task["status"],
            "result": task.get("result"),
            "error": task.get("error"),
        }
    )


@router.get("")
async def list_tasks(
    request: Request,
    status: str | None = None,
    limit: int = 50,
) -> JSONResponse:
    """List tasks, filtered by status and scoped to caller's org."""
    limit = min(max(limit, 1), 500)
    auth, container = await _authenticate(request)
    tasks = await container.task_queue.list_tasks(status=status, limit=limit)

    # Org isolation: strict filter to caller's org (no unscoped leakage)
    if auth.org_id:
        tasks = [t for t in tasks if t.get("payload", {}).get("org_id", "") == auth.org_id]

    return JSONResponse(content={"tasks": tasks})
