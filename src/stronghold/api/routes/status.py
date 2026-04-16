"""Status and health endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from stronghold import __version__

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Health check — no auth required (load balancer probe).

    Checks database and LLM connectivity. Returns 200 even if degraded
    (so load balancers don't kill the container), but body indicates issues.
    """
    result: dict[str, Any] = {
        "status": "ok",
        "service": "stronghold",
        "version": __version__,
    }

    # Database check
    container = getattr(request.app.state, "container", None)
    if container and getattr(container, "db_pool", None):
        try:
            async with container.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            result["db"] = "connected"
        except Exception:  # noqa: BLE001
            result["db"] = "error"
            result["status"] = "degraded"
    else:
        result["db"] = "in_memory"

    # LLM proxy check (only for real LiteLLMClient with a base_url)
    llm_url = getattr(getattr(container, "llm", None), "_base_url", None) if container else None
    if llm_url:
        import httpx  # noqa: PLC0415

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{llm_url}/health")
                result["llm"] = "reachable" if resp.status_code < 500 else "unhealthy"
        except Exception:  # noqa: BLE001
            result["llm"] = "unreachable"
            result["status"] = "degraded"

    return result


@router.get("/status/reactor")
async def reactor_status(request: Request) -> dict[str, Any]:
    """Reactor loop status — triggers, events, stats. Requires auth."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    status = container.reactor.get_status()
    return {
        "running": status.running,
        "tick_count": status.tick_count,
        "active_tasks": status.active_tasks,
        "events_processed": status.events_processed,
        "triggers_fired": status.triggers_fired,
        "tasks_completed": status.tasks_completed,
        "tasks_failed": status.tasks_failed,
        "triggers": status.triggers,
        "recent_events": status.recent_events,
    }


@router.get("/version")
async def version() -> dict[str, Any]:
    """Version endpoint — returns current Stronghold version and Python version."""
    import sys  # noqa: PLC0415

    return {
        "version": __version__,
        "python_version": sys.version,
        "service": "stronghold",
    }


@router.get("/v1/stronghold/version")
async def version_v1() -> dict[str, Any]:
    """Version endpoint — returns current Stronghold version and Python version."""
    import sys  # noqa: PLC0415

    return {
        "version": __version__,
        "python_version": sys.version,
        "service": "stronghold",
    }


@router.get("/metrics")
async def prometheus_metrics(request: Request) -> Any:
    """Prometheus metrics — builders queue depth for KEDA scaling.

    Exposes the mason_queue status as Prometheus gauge metrics.
    No auth required (scraped by Prometheus / KEDA metrics adapter).
    """
    from fastapi.responses import PlainTextResponse  # noqa: PLC0415

    lines: list[str] = []

    # Builders queue metrics
    container = getattr(request.app.state, "container", None)
    queue = getattr(container, "mason_queue", None) if container else None
    if queue is not None:
        status = queue.status()
        queued = status.get("queued", 0)
        in_progress = status.get("in_progress", 0)
        completed = status.get("completed", 0)
        failed = status.get("failed", 0)
        total = status.get("total", 0)

        lines.append("# HELP builders_queue_depth Number of issues in each state")
        lines.append("# TYPE builders_queue_depth gauge")
        lines.append(f'builders_queue_depth{{state="queued"}} {queued}')
        lines.append(f'builders_queue_depth{{state="in_progress"}} {in_progress}')
        lines.append(f'builders_queue_depth{{state="completed"}} {completed}')
        lines.append(f'builders_queue_depth{{state="failed"}} {failed}')

        lines.append("# HELP builders_queue_total Total issues tracked")
        lines.append("# TYPE builders_queue_total gauge")
        lines.append(f"builders_queue_total {total}")

        lines.append("# HELP builders_queue_actionable Issues queued or in progress")
        lines.append("# TYPE builders_queue_actionable gauge")
        lines.append(f"builders_queue_actionable {queued + in_progress}")
    else:
        lines.append("# HELP builders_queue_actionable Issues queued or in progress")
        lines.append("# TYPE builders_queue_actionable gauge")
        lines.append("builders_queue_actionable 0")

    # Orchestrator metrics
    orchestrator = getattr(request.app.state, "orchestrator", None)
    if orchestrator is not None:
        orch_status = orchestrator.status()
        lines.append("# HELP orchestrator_active_workers Active agent workers")
        lines.append("# TYPE orchestrator_active_workers gauge")
        lines.append(f"orchestrator_active_workers {orch_status.get('active', 0)}")

    lines.append("")
    return PlainTextResponse("\n".join(lines), media_type="text/plain; version=0.0.4")
