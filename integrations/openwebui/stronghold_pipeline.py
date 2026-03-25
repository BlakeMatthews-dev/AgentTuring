"""Stronghold Pipeline for OpenWebUI Pipelines container.

This file is deployed into the OpenWebUI Pipelines container.
It bridges OpenWebUI's chat interface to Stronghold's governance layer.

Users see Stronghold agents as model choices in OpenWebUI's model picker.
All requests flow through Stronghold's security stack (Gate, Warden,
Sentinel, rate limiting) before reaching the LLM.

Setup:
1. Deploy the Pipelines container alongside OpenWebUI
2. Copy this file to the pipelines volume
3. Configure STRONGHOLD_URL and STRONGHOLD_API_KEY in Pipelines UI
4. Stronghold agents appear as model choices in OpenWebUI
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Generator

import httpx
from pydantic import BaseModel

logger = logging.getLogger("stronghold.pipeline")


class Pipeline:
    """OpenWebUI Pipeline that routes through Stronghold governance."""

    class Valves(BaseModel):
        """Pipeline configuration (editable in Pipelines UI)."""

        STRONGHOLD_URL: str = os.getenv("STRONGHOLD_URL", "http://stronghold:8100")
        STRONGHOLD_API_KEY: str = os.getenv("STRONGHOLD_API_KEY", "")
        STRONGHOLD_TIMEOUT: int = 120

    def __init__(self) -> None:
        self.name = "Stronghold Chat"
        self.valves = self.Valves()
        self._agents: list[dict[str, str]] = []

    async def on_startup(self) -> None:
        """Verify Stronghold connectivity and cache agent list."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.valves.STRONGHOLD_URL}/health")
                if resp.status_code == 200:
                    logger.info("Stronghold connected: %s", resp.json())
                await self._refresh_agents(client)
        except Exception:
            logger.warning("Stronghold not reachable at startup", exc_info=True)

    async def on_shutdown(self) -> None:
        """Cleanup."""

    async def on_valves_updated(self) -> None:
        """Re-fetch agents when config changes."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await self._refresh_agents(client)
        except Exception:
            logger.warning("Failed to refresh agents", exc_info=True)

    def pipes(self) -> list[dict[str, str]]:
        """Expose Stronghold agents as model choices in OpenWebUI."""
        if not self._agents:
            return [{"id": "stronghold.auto", "name": "Stronghold (Auto-Route)"}]

        models = [{"id": "stronghold.auto", "name": "Stronghold (Auto-Route)"}]
        for agent in self._agents:
            name = agent.get("name", "unknown")
            desc = agent.get("description", "")
            display = f"Stronghold: {name}"
            if desc:
                display += f" - {desc[:50]}"
            models.append({"id": f"stronghold.{name}", "name": display})
        return models

    def pipe(
        self,
        body: dict[str, Any],
        __user__: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> str | Generator[str, None, None]:
        """Route request through Stronghold with user context.

        The Pipelines container calls this SYNCHRONOUSLY.
        Returns a string (non-streaming) or a Generator (streaming).
        """
        user = __user__ or {}
        model_id = body.get("model", "stronghold.auto")

        # Extract agent name from model ID
        intent_hint = ""
        if model_id.startswith("stronghold.") and model_id != "stronghold.auto":
            agent_name = model_id.removeprefix("stronghold.")
            intent_map = {
                "artificer": "code",
                "ranger": "search",
                "scribe": "creative",
                "warden-at-arms": "automation",
            }
            intent_hint = intent_map.get(agent_name, "")

        # Build headers with OpenWebUI user context
        headers = {
            "Authorization": f"Bearer {self.valves.STRONGHOLD_API_KEY}",
            "Content-Type": "application/json",
            "X-OpenWebUI-User-Email": user.get("email", ""),
            "X-OpenWebUI-User-Name": user.get("name", ""),
            "X-OpenWebUI-User-Id": user.get("id", ""),
            "X-OpenWebUI-User-Role": user.get("role", ""),
        }

        messages = body.get("messages", [])
        payload: dict[str, Any] = {"model": "auto", "messages": messages}
        if intent_hint:
            payload["intent_hint"] = intent_hint

        # Always use non-streaming — Stronghold returns full JSON responses.
        # The Pipelines container handles SSE wrapping for OpenWebUI.
        try:
            with httpx.Client(timeout=self.valves.STRONGHOLD_TIMEOUT) as client:
                resp = client.post(
                    f"{self.valves.STRONGHOLD_URL}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                )
                data = resp.json()
                return (
                    data.get("choices", [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
        except Exception as e:
            return f"Stronghold error: {e}"

    def _stream_response(
        self,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> Generator[str, None, None]:
        """Stream response from Stronghold as a sync generator."""
        payload["stream"] = True
        try:
            with httpx.Client(timeout=self.valves.STRONGHOLD_TIMEOUT) as client:
                with client.stream(
                    "POST",
                    f"{self.valves.STRONGHOLD_URL}/v1/chat/completions",
                    headers=headers,
                    json=payload,
                ) as resp:
                    for line in resp.iter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                content = (
                                    chunk.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                                if content:
                                    yield content
                            except json.JSONDecodeError:
                                yield data
        except Exception as e:
            yield f"Stronghold error: {e}"

    async def _refresh_agents(self, client: httpx.AsyncClient) -> None:
        """Fetch agent list from Stronghold."""
        resp = await client.get(
            f"{self.valves.STRONGHOLD_URL}/v1/stronghold/agents",
            headers={"Authorization": f"Bearer {self.valves.STRONGHOLD_API_KEY}"},
        )
        if resp.status_code == 200:
            data = resp.json()
            self._agents = data.get("agents", data) if isinstance(data, dict) else data
            logger.info("Loaded %d agents from Stronghold", len(self._agents))
