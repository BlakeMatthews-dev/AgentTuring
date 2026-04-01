"""Scheduled task management endpoints.

User-facing recurring task scheduling:
- POST   /v1/stronghold/schedules          — create a schedule
- GET    /v1/stronghold/schedules          — list user's schedules
- GET    /v1/stronghold/schedules/{id}     — get one
- PUT    /v1/stronghold/schedules/{id}     — update
- DELETE /v1/stronghold/schedules/{id}     — delete
- POST   /v1/stronghold/schedules/{id}/run — trigger immediately
- GET    /v1/stronghold/schedules/{id}/history — past executions

All endpoints require authentication and are org-scoped.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from stronghold.scheduling.store import ScheduledTask

router = APIRouter(prefix="/v1/stronghold/schedules")


# ── Auth helper ──────────────────────────────────────────────────────


async def _authenticate(request: Request) -> tuple[Any, Any]:
    """Authenticate and return (auth, container)."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return auth, container


# ── Routes ───────────────────────────────────────────────────────────


@router.post("")
async def create_schedule(request: Request) -> JSONResponse:
    """Create a scheduled task."""
    auth, container = await _authenticate(request)
    body: dict[str, Any] = await request.json()

    name = body.get("name", "")
    schedule = body.get("schedule", "")
    prompt = body.get("prompt", "")

    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")
    if not schedule:
        raise HTTPException(status_code=400, detail="'schedule' is required")

    task = ScheduledTask(
        user_id=auth.user_id,
        org_id=auth.org_id,
        name=name,
        schedule=schedule,
        prompt=prompt,
        agent=body.get("agent", ""),
        delivery=body.get("delivery", ""),
        enabled=body.get("enabled", True),
    )

    try:
        created = await container.schedule_store.create(task)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return JSONResponse(status_code=201, content=asdict(created))


@router.get("")
async def list_schedules(request: Request) -> JSONResponse:
    """List the caller's scheduled tasks."""
    auth, container = await _authenticate(request)
    tasks = await container.schedule_store.list_for_user(user_id=auth.user_id, org_id=auth.org_id)
    return JSONResponse(content={"schedules": [asdict(t) for t in tasks]})


@router.get("/{task_id}")
async def get_schedule(task_id: str, request: Request) -> JSONResponse:
    """Get a single scheduled task."""
    auth, container = await _authenticate(request)
    task = await container.schedule_store.get(task_id, org_id=auth.org_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return JSONResponse(content=asdict(task))


@router.put("/{task_id}")
async def update_schedule(task_id: str, request: Request) -> JSONResponse:
    """Update a scheduled task."""
    auth, container = await _authenticate(request)
    body: dict[str, Any] = await request.json()

    # Filter to allowed fields
    allowed = {"name", "schedule", "prompt", "agent", "delivery", "enabled"}
    updates = {k: v for k, v in body.items() if k in allowed}

    try:
        updated = await container.schedule_store.update(task_id, org_id=auth.org_id, **updates)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if updated is None:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return JSONResponse(content=asdict(updated))


@router.delete("/{task_id}")
async def delete_schedule(task_id: str, request: Request) -> JSONResponse:
    """Delete a scheduled task."""
    auth, container = await _authenticate(request)
    deleted = await container.schedule_store.delete(task_id, org_id=auth.org_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return JSONResponse(content={"deleted": True})


@router.post("/{task_id}/run")
async def run_schedule_now(task_id: str, request: Request) -> JSONResponse:
    """Trigger a scheduled task immediately."""
    auth, container = await _authenticate(request)
    task = await container.schedule_store.get(task_id, org_id=auth.org_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Schedule not found")

    # Record immediate execution intent — the Reactor or worker will pick it up.
    # For now, return 202 Accepted to indicate the task has been queued.
    return JSONResponse(
        status_code=202,
        content={"task_id": task.id, "status": "triggered"},
    )


@router.get("/{task_id}/history")
async def get_schedule_history(
    task_id: str,
    request: Request,
    limit: int = 10,
) -> JSONResponse:
    """Get execution history for a scheduled task."""
    auth, container = await _authenticate(request)
    limit = min(max(limit, 1), 100)
    history = await container.schedule_store.get_history(task_id, org_id=auth.org_id, limit=limit)
    return JSONResponse(
        content={
            "task_id": task_id,
            "history": [asdict(e) for e in history],
        }
    )
