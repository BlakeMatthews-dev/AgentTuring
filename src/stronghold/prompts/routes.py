"""Prompt management API routes.

CRUD for the prompt library:
- List all prompts
- Get prompt by name (with label)
- Create/update prompt (new version)
- Get version history
- Promote label (move production/staging pointer)

All endpoints require authentication. Write operations require admin role.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/v1/stronghold/prompts")


async def _require_auth(request: Request) -> Any:
    """Authenticate and return auth context."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        return await container.auth_provider.authenticate(auth_header)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


async def _require_admin(request: Request) -> Any:
    """Authenticate and require admin role."""
    auth = await _require_auth(request)
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


@router.get("")
async def list_prompts(request: Request) -> JSONResponse:
    """List all prompts with their current labels."""
    await _require_auth(request)
    container = request.app.state.container
    pm = container.prompt_manager

    all_prompts: list[dict[str, Any]] = []
    for name in sorted(pm._versions.keys()):
        labels = pm._labels.get(name, {})
        versions = pm._versions.get(name, {})
        latest_version = max(versions.keys()) if versions else 0
        content, config = versions.get(latest_version, ("", {}))

        all_prompts.append(
            {
                "name": name,
                "versions": len(versions),
                "labels": labels,
                "latest_version": latest_version,
                "content_preview": content[:100] + "..." if len(content) > 100 else content,
            }
        )

    return JSONResponse(content={"prompts": all_prompts})


@router.get("/{name:path}/versions")
async def get_versions(name: str, request: Request) -> JSONResponse:
    """Get version history for a prompt."""
    await _require_auth(request)
    container = request.app.state.container
    pm = container.prompt_manager

    versions = pm._versions.get(name)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    labels = pm._labels.get(name, {})
    version_labels: dict[int, list[str]] = {}
    for label, ver in labels.items():
        version_labels.setdefault(ver, []).append(label)

    version_list = []
    for ver in sorted(versions.keys()):
        content, config = versions[ver]
        version_list.append(
            {
                "version": ver,
                "labels": version_labels.get(ver, []),
                "content_preview": content[:100] + "..." if len(content) > 100 else content,
                "config": config,
            }
        )

    return JSONResponse(content={"name": name, "versions": version_list})


@router.get("/{name:path}")
async def get_prompt(
    name: str,
    request: Request,
    label: str = "production",
) -> JSONResponse:
    """Get a prompt by name and label."""
    await _require_auth(request)
    container = request.app.state.container
    pm = container.prompt_manager

    content, config = await pm.get_with_config(name, label=label)
    if not content:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    labels = pm._labels.get(name, {})
    current_label_version = labels.get(label)

    return JSONResponse(
        content={
            "name": name,
            "content": content,
            "config": config,
            "label": label,
            "version": current_label_version,
        }
    )


@router.put("/{name:path}")
async def upsert_prompt(name: str, request: Request) -> JSONResponse:
    """Create a new version of a prompt. Requires admin role.

    C5 fix: Prompts are org-scoped via the prompt manager. Non-system admins
    can only modify prompts within their own org namespace.
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    pm = container.prompt_manager
    body: dict[str, Any] = await request.json()

    content = body.get("content", "")
    config = body.get("config", {})
    label = body.get("label", "")

    if not content:
        raise HTTPException(status_code=400, detail="'content' is required")

    await pm.upsert(name, content, config=config, label=label, org_id=auth.org_id)

    scoped_name = pm._scoped_name(name, auth.org_id)
    versions = pm._versions.get(scoped_name, {})
    latest = max(versions.keys()) if versions else 0

    return JSONResponse(
        content={
            "name": name,
            "version": latest,
            "label": label or "latest",
            "status": "created",
        }
    )


@router.post("/{name:path}/promote")
async def promote_label(name: str, request: Request) -> JSONResponse:
    """Promote a label from one version to another. Requires admin role.

    Body: {"from_label": "staging", "to_label": "production"}
    """
    await _require_admin(request)
    container = request.app.state.container
    pm = container.prompt_manager
    body: dict[str, Any] = await request.json()

    from_label = body.get("from_label", "")
    to_label = body.get("to_label", "")

    if not from_label or not to_label:
        raise HTTPException(status_code=400, detail="from_label and to_label required")

    labels = pm._labels.get(name)
    if not labels:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    from_version = labels.get(from_label)
    if from_version is None:
        raise HTTPException(status_code=404, detail=f"Label '{from_label}' not found")

    labels[to_label] = from_version

    return JSONResponse(
        content={
            "name": name,
            "promoted": f"{from_label}(v{from_version}) → {to_label}",
            "version": from_version,
        }
    )


# ── Diff + Approval Workflow ──────────────────────────────────────

# In-memory approval store (per-process, cleared on restart)
_approvals: dict[str, list[Any]] = {}


@router.get("/{name:path}/diff")
async def get_diff(
    name: str,
    request: Request,
    from_version: int = 1,
    to_version: int = 2,
) -> JSONResponse:
    """Get unified diff between two versions of a prompt."""
    await _require_auth(request)
    container = request.app.state.container
    pm = container.prompt_manager

    versions = pm._versions.get(name)
    if not versions:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' not found")

    old_content = versions.get(from_version, ("", {}))[0]
    new_content = versions.get(to_version, ("", {}))[0]

    if not old_content and not new_content:
        raise HTTPException(
            status_code=404,
            detail=f"Version {from_version} or {to_version} not found",
        )

    from stronghold.prompts.diff import compute_diff  # noqa: PLC0415

    diff_lines = compute_diff(
        old_content,
        new_content,
        old_label=f"v{from_version}",
        new_label=f"v{to_version}",
    )

    return JSONResponse(
        content={
            "name": name,
            "from_version": from_version,
            "to_version": to_version,
            "diff": [
                {
                    "op": d.op,
                    "content": d.content,
                    "old_lineno": d.old_lineno,
                    "new_lineno": d.new_lineno,
                }
                for d in diff_lines
            ],
        }
    )


@router.post("/{name:path}/request-approval")
async def request_approval(name: str, request: Request) -> JSONResponse:
    """Request approval to promote a prompt version. Any authenticated user.

    Body: {"version": 2, "notes": "Updated for new compliance rules"}
    """
    auth = await _require_auth(request)
    container = request.app.state.container
    pm = container.prompt_manager
    body: dict[str, Any] = await request.json()

    version = body.get("version", 0)
    notes = body.get("notes", "")

    versions = pm._versions.get(name)
    if not versions or version not in versions:
        raise HTTPException(status_code=404, detail=f"Prompt '{name}' v{version} not found")

    from stronghold.types.prompt import ApprovalRequest  # noqa: PLC0415

    approval = ApprovalRequest(
        prompt_name=name,
        version=version,
        requested_by=auth.user_id,
        notes=notes,
    )

    _approvals.setdefault(name, []).append(approval)

    return JSONResponse(
        content={
            "prompt_name": name,
            "version": version,
            "status": "pending",
            "requested_by": auth.user_id,
        }
    )


@router.post("/{name:path}/approve")
async def approve_prompt(name: str, request: Request) -> JSONResponse:
    """Approve a pending prompt version. Admin only.

    Body: {"version": 2}
    Promotes the approved version to production label.
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    pm = container.prompt_manager
    body: dict[str, Any] = await request.json()

    version = body.get("version", 0)

    # Find pending approval
    approvals = _approvals.get(name, [])
    pending = next(
        (a for a in approvals if a.version == version and a.status == "pending"),
        None,
    )
    if not pending:
        raise HTTPException(status_code=404, detail="No pending approval for this version")

    # Promote to production
    from datetime import UTC, datetime  # noqa: PLC0415

    pending.status = "approved"
    pending.reviewed_by = auth.user_id
    pending.reviewed_at = datetime.now(UTC)

    labels = pm._labels.get(name, {})
    labels["production"] = version
    pm._labels[name] = labels

    return JSONResponse(
        content={
            "prompt_name": name,
            "version": version,
            "status": "approved",
            "promoted_to": "production",
            "reviewed_by": auth.user_id,
        }
    )


@router.post("/{name:path}/reject")
async def reject_prompt(name: str, request: Request) -> JSONResponse:
    """Reject a pending prompt version. Admin only.

    Body: {"version": 2, "reason": "Does not meet compliance requirements"}
    """
    auth = await _require_admin(request)
    body: dict[str, Any] = await request.json()

    version = body.get("version", 0)
    reason = body.get("reason", "")

    approvals = _approvals.get(name, [])
    pending = next(
        (a for a in approvals if a.version == version and a.status == "pending"),
        None,
    )
    if not pending:
        raise HTTPException(status_code=404, detail="No pending approval for this version")

    from datetime import UTC, datetime  # noqa: PLC0415

    pending.status = "rejected"
    pending.reviewed_by = auth.user_id
    pending.review_notes = reason
    pending.reviewed_at = datetime.now(UTC)

    return JSONResponse(
        content={
            "prompt_name": name,
            "version": version,
            "status": "rejected",
            "reason": reason,
            "reviewed_by": auth.user_id,
        }
    )
