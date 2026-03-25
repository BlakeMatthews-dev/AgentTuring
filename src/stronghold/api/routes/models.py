"""Model listing endpoint.

Returns models from both Stronghold config AND LiteLLM proxy.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger("stronghold.api.models")

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request) -> dict[str, Any]:
    """List available models. Merges Stronghold config + LiteLLM fleet."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    config = container.config
    models_cfg = config.models
    groups_cfg = config.model_groups

    data: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Stronghold-configured model groups
    for group_id, group_cfg in groups_cfg.items():
        data.append(
            {
                "id": group_id,
                "object": "model",
                "created": 0,
                "owned_by": "stronghold",
                "description": group_cfg.get("description", ""),
            }
        )
        seen.add(group_id)

    # Stronghold-configured individual models
    for model_id, model_cfg in models_cfg.items():
        provider = model_cfg.get("provider", "")
        prov = config.providers.get(provider, {})
        if prov.get("status") != "active":
            continue
        data.append(
            {
                "id": model_id,
                "object": "model",
                "created": 0,
                "owned_by": provider,
            }
        )
        seen.add(model_id)

    # Fetch additional models from LiteLLM proxy
    litellm_url = config.litellm_url
    litellm_key = config.litellm_key
    if litellm_url:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{litellm_url}/v1/models",
                    headers={"Authorization": f"Bearer {litellm_key}"},
                )
                if resp.status_code == 200:  # noqa: PLR2004
                    litellm_data = resp.json()
                    for m in litellm_data.get("data", []):
                        mid = m.get("id", "")
                        if mid and mid not in seen:
                            data.append(
                                {
                                    "id": mid,
                                    "object": "model",
                                    "created": m.get("created", 0),
                                    "owned_by": m.get("owned_by", "litellm"),
                                }
                            )
                            seen.add(mid)
        except Exception as e:
            logger.debug("LiteLLM model fetch failed: %s", e)

    return {"object": "list", "data": data}
