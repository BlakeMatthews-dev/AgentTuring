"""Orchestrator API — dispatch work to any agent, track execution.

POST /v1/stronghold/orchestrator/dispatch  — submit work to an agent
GET  /v1/stronghold/orchestrator/queue     — list all work items
GET  /v1/stronghold/orchestrator/status    — engine status summary
GET  /v1/stronghold/orchestrator/{id}      — get work item details
POST /v1/stronghold/orchestrator/{id}/cancel — cancel queued work
POST /v1/stronghold/orchestrator/github-issue — assign a GitHub issue to an agent
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/stronghold/orchestrator", tags=["orchestrator"])


def _engine(request: Request) -> Any:
    engine = getattr(request.app.state, "orchestrator", None)
    if engine is None:
        raise HTTPException(503, "Orchestrator not initialized")
    return engine


@router.post("/dispatch")
async def dispatch_work(request: Request) -> JSONResponse:
    """Dispatch work to any agent.

    Body:
        agent_name: str — which agent handles this (mason, auditor, ranger, etc.)
        messages: list[dict] — the conversation messages
        trigger: str — what caused this dispatch (api, webhook, cron, reactor)
        priority_tier: str — P0-P5 priority
        intent_hint: str — optional intent hint for the classifier
        metadata: dict — arbitrary metadata (issue_number, pr_url, etc.)
    """
    engine = _engine(request)
    body = await request.json()

    agent_name = body.get("agent_name", "")
    if not agent_name:
        raise HTTPException(400, "agent_name required")

    messages = body.get("messages", [])
    if not messages:
        raise HTTPException(400, "messages required")

    # Verify agent exists
    container = request.app.state.container
    if agent_name not in container.agents:
        available = list(container.agents.keys())
        raise HTTPException(
            404,
            f"Agent '{agent_name}' not found. Available: {available}",
        )

    work_id = body.get("id", str(uuid.uuid4())[:12])
    item = engine.dispatch(
        work_id=work_id,
        agent_name=agent_name,
        messages=messages,
        trigger=body.get("trigger", "api"),
        priority_tier=body.get("priority_tier", "P2"),
        intent_hint=body.get("intent_hint", ""),
        metadata=body.get("metadata", {}),
    )
    return JSONResponse(item.to_dict(), status_code=202)


@router.post("/github-issue")
async def dispatch_github_issue(request: Request) -> JSONResponse:
    """Shortcut: assign a GitHub issue to an agent (default: mason).

    Body:
        issue_number: int
        title: str
        owner: str — repo owner
        repo: str — repo name
        agent_name: str — default "mason"
        priority_tier: str — default "P5" (builder tier)
    """
    engine = _engine(request)
    body = await request.json()

    issue_number = body.get("issue_number", 0)
    if not issue_number:
        raise HTTPException(400, "issue_number required")

    title = body.get("title", f"Issue #{issue_number}")
    owner = body.get("owner", "Agent-StrongHold")
    repo = body.get("repo", "stronghold")
    agent_name = body.get("agent_name", "mason")

    work_id = f"gh-{issue_number}"
    content = (
        f"Implement GitHub issue #{issue_number}: {title}\n\n"
        f"Repository: {owner}/{repo}\n"
        f"Read the issue at: https://github.com/{owner}/{repo}/issues/{issue_number}\n\n"
        f"Follow your SOUL.md pipeline. Create a focused PR when done."
    )

    item = engine.dispatch(
        work_id=work_id,
        agent_name=agent_name,
        messages=[{"role": "user", "content": content}],
        trigger=body.get("trigger", "api"),
        priority_tier=body.get("priority_tier", "P5"),
        intent_hint="code_gen",
        metadata={
            "issue_number": issue_number,
            "title": title,
            "owner": owner,
            "repo": repo,
        },
    )
    return JSONResponse(item.to_dict(), status_code=202)


@router.get("/queue")
async def list_queue(request: Request) -> JSONResponse:
    """List all work items, optionally filtered by status."""
    engine = _engine(request)
    status_filter = request.query_params.get("status")
    if status_filter:
        from stronghold.orchestrator.engine import WorkStatus  # noqa: PLC0415

        try:
            ws = WorkStatus(status_filter)
        except ValueError as exc:
            raise HTTPException(400, f"Invalid status: {status_filter}") from exc
        items = engine.list_items(status=ws)
    else:
        items = engine.list_items()
    return JSONResponse({"items": items, "count": len(items)})


@router.get("/status")
async def engine_status(request: Request) -> JSONResponse:
    """Get orchestrator engine status summary."""
    engine = _engine(request)
    return JSONResponse(engine.status())


@router.get("/{work_id}")
async def get_work_item(work_id: str, request: Request) -> JSONResponse:
    """Get details of a specific work item."""
    engine = _engine(request)
    item = engine.get(work_id)
    if item is None:
        raise HTTPException(404, f"Work item not found: {work_id}")
    result = item.to_dict()
    result["log"] = item.log
    result["result"] = item.result
    return JSONResponse(result)


@router.post("/{work_id}/cancel")
async def cancel_work(work_id: str, request: Request) -> JSONResponse:
    """Cancel a queued work item."""
    engine = _engine(request)
    cancelled = engine.cancel(work_id)
    if not cancelled:
        raise HTTPException(400, "Can only cancel queued items")
    return JSONResponse({"cancelled": True, "work_id": work_id})
