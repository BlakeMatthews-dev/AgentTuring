"""API route: traces — observability data."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/v1/stronghold/traces")
async def list_traces(request: Request) -> JSONResponse:
    """List recent traces. Delegates to Phoenix if configured."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    # Traces are stored in Phoenix — return a pointer
    phoenix_url = container.config.phoenix_endpoint or "http://phoenix:6006"
    return JSONResponse(
        content={
            "traces": "stored_in_phoenix",
            "phoenix_url": phoenix_url,
            "note": "Visit Phoenix UI for full trace exploration",
        }
    )
