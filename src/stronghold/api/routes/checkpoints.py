"""API routes: admin read-only access to SessionCheckpoint store (S1.3).

Write path is intentionally programmatic only (via CheckpointStore protocol).
S2.7 may add admin POST for manual/operator-created checkpoints.

All endpoints:
- Require the `admin` role (same gate as admin/learnings).
- Scope every query by the caller's org_id — no cross-tenant visibility.
- Return 404 rather than 403 on cross-org id lookups (existence hiding).
- Skip CSRF for GET requests (safe by HTTP semantics).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.checkpoints")

router = APIRouter()


async def _require_admin(request: Request) -> Any:
    """Authenticate and require admin role (no CSRF needed for GET)."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


def _serialize(cp: Any) -> dict[str, Any]:
    """Dataclass → JSON-friendly dict. Enums become their .value, datetime → iso."""
    d = asdict(cp)
    # scope is a StrEnum; asdict keeps the enum instance in some Python versions.
    scope = d.get("scope")
    if scope is not None and hasattr(scope, "value"):
        d["scope"] = scope.value
    created_at = d.get("created_at")
    if created_at is not None and hasattr(created_at, "isoformat"):
        d["created_at"] = created_at.isoformat()
    return d


@router.get("/v1/stronghold/admin/checkpoints")
async def list_checkpoints(request: Request, limit: int = 20) -> JSONResponse:
    """List recent checkpoints (org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    store = getattr(container, "checkpoint_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="CheckpointStore not configured")
    items = await store.list_recent(org_id=auth.org_id, limit=limit)
    return JSONResponse({"items": [_serialize(cp) for cp in items]})


@router.get("/v1/stronghold/admin/checkpoints/{checkpoint_id}")
async def get_checkpoint(request: Request, checkpoint_id: str) -> JSONResponse:
    """Fetch a single checkpoint. Cross-org access returns 404."""
    auth = await _require_admin(request)
    container = request.app.state.container
    store = getattr(container, "checkpoint_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="CheckpointStore not configured")
    cp = await store.load(checkpoint_id, org_id=auth.org_id)
    if cp is None:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return JSONResponse(_serialize(cp))
