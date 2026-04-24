"""github_raw: escape-hatch tool for the 1% of GitHub use cases playbooks miss.

Design principle (plan §2.4): keep the primary MCP surface ≤20 playbooks
by shipping ONE raw wrapper per integration rather than a per-endpoint
fan-out. Callers supply `method` + `endpoint` + optional `params` / `body`;
we proxy to the GitHub REST API with bot-installation-token auth and
return the JSON response verbatim.

Guardrails (defense-in-depth with the Casbin tool policy at
src/stronghold/security/tool_policy/):
- Method allowlist: GET, POST, PATCH, PUT, DELETE
- Path allowlist: /repos/, /user, /users/, /orgs/, /search/, /gists/
- Path denylist:  /admin/, /enterprise/, /scim/, /app/
- Every call is logged at INFO with method + endpoint + principal (for
  the Sentinel audit trail)

T1-only trust tier, gated by agent allowlist — see plan §2.4.
"""

from __future__ import annotations

import logging
from typing import Any

from stronghold.playbooks.github._client import GitHubClient
from stronghold.types.tool import ToolDefinition, ToolResult

logger = logging.getLogger("stronghold.tools.github_raw")

GITHUB_RAW_TOOL_DEF = ToolDefinition(
    name="github_raw",
    description=(
        "Raw GitHub REST API escape hatch. Only use when no playbook covers "
        "the need. Provide method (GET/POST/PATCH/PUT/DELETE), endpoint "
        "(e.g. /repos/acme/widget/stars), optional params dict, optional "
        "body_json dict. T1 trust tier only."
    ),
    parameters={
        "type": "object",
        "properties": {
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PATCH", "PUT", "DELETE"],
            },
            "endpoint": {
                "type": "string",
                "description": "API path beginning with '/' (e.g. /repos/o/r).",
            },
            "params": {"type": "object", "description": "Query string parameters."},
            "body_json": {"type": "object", "description": "JSON request body."},
        },
        "required": ["method", "endpoint"],
    },
)

_ALLOWED_METHODS = frozenset({"GET", "POST", "PATCH", "PUT", "DELETE"})
_ALLOWED_PATH_PREFIXES = (
    "/repos/",
    "/user",
    "/users/",
    "/orgs/",
    "/search/",
    "/gists/",
    "/notifications",
    "/issues",
)
_DENY_PATH_PREFIXES = (
    "/admin/",
    "/enterprise/",
    "/scim/",
    "/app/",
)


class GitHubRawExecutor:
    """ToolExecutor for `github_raw`. Stateless; constructs a client per call."""

    def __init__(self, *, bot: str = "gatekeeper") -> None:
        self._bot = bot

    @property
    def name(self) -> str:
        return "github_raw"

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        method = str(arguments.get("method", "")).upper()
        endpoint = str(arguments.get("endpoint", ""))
        params = arguments.get("params") or None
        body_json = arguments.get("body_json") or None

        if method not in _ALLOWED_METHODS:
            return ToolResult(
                success=False,
                error=f"Method not allowed: {method!r}. Use one of {sorted(_ALLOWED_METHODS)}.",
            )
        if not endpoint.startswith("/"):
            return ToolResult(
                success=False,
                error=f"Endpoint must start with '/': got {endpoint!r}",
            )
        if any(endpoint.startswith(p) for p in _DENY_PATH_PREFIXES):
            return ToolResult(
                success=False,
                error=f"Endpoint denied by policy: {endpoint}",
            )
        if not any(endpoint.startswith(p) for p in _ALLOWED_PATH_PREFIXES):
            return ToolResult(
                success=False,
                error=(
                    f"Endpoint not allowlisted: {endpoint}. "
                    f"Allowed prefixes: {list(_ALLOWED_PATH_PREFIXES)}"
                ),
            )

        logger.info("github_raw %s %s", method, endpoint)
        client = GitHubClient(bot=self._bot)
        try:
            resp = await client.request(method, endpoint, params=params, json_body=body_json)
        except Exception as exc:  # noqa: BLE001 — tool boundary
            return ToolResult(success=False, error=f"{type(exc).__name__}: {exc}")

        if resp.status_code >= 400:
            return ToolResult(
                success=False,
                error=f"GitHub {resp.status_code}: {resp.text[:500]}",
                content=resp.text,
            )

        content_type = resp.headers.get("content-type", "")
        if "json" in content_type:
            import json  # noqa: PLC0415

            return ToolResult(content=json.dumps(resp.json()), success=True)
        return ToolResult(content=resp.text, success=True)
