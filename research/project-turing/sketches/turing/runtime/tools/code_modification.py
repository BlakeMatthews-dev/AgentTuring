"""StrongholdClient: delegate work to the Stronghold agent governance platform.

Stronghold runs Quartermaster, Archie, Mason, Arbiter, and other agents.
Turing uses this tool to submit tasks, ask questions, or request code changes.

The tool is deliberately narrow — it accepts a structured payload and POSTs it
to one of three Stronghold endpoints:

  /v1/chat/completions     — ask a question, get a routed response
  /v1/stronghold/tasks     — submit a structured task with intent
  /v1/stronghold/request   — structured request with explicit intent routing

The caller (Turing's producers or chat handler) picks the endpoint and builds
the JSON payload. This tool just handles auth, transport, and error reporting.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Any
from urllib.error import URLError

from .base import Tool, ToolMode


logger = logging.getLogger("turing.runtime.tools.code_modification")

_DEFAULT_TIMEOUT = 60


class StrongholdClient:
    name = "code_modification"
    mode = ToolMode.WRITE

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout: int = _DEFAULT_TIMEOUT,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    def invoke(
        self,
        *,
        endpoint: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if endpoint not in _ALLOWED_ENDPOINTS:
            raise ValueError(
                f"endpoint must be one of {sorted(_ALLOWED_ENDPOINTS)}, got {endpoint!r}"
            )
        url = f"{self._base_url}{endpoint}"
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                logger.info("stronghold %s → %d bytes", endpoint, len(json.dumps(data)))
                return data
        except URLError as exc:
            reason = getattr(exc, "reason", str(exc))
            logger.error("stronghold %s failed: %s", endpoint, reason)
            return {"error": str(reason), "endpoint": endpoint}
        except Exception:
            logger.exception("stronghold %s unexpected error", endpoint)
            return {"error": "unexpected error", "endpoint": endpoint}


_ALLOWED_ENDPOINTS = {
    "/v1/chat/completions",
    "/v1/stronghold/tasks",
    "/v1/stronghold/request",
    "/v1/stronghold/gate",
}
