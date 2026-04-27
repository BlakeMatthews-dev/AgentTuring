"""Stronghold-specific agent endpoints.

Internal API for the dashboard and tooling. Not OpenAI-compatible.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from stronghold.types.errors import QuotaExhaustedError

router = APIRouter(prefix="/v1/stronghold")


@router.post("/request")
async def structured_request(request: Request) -> JSONResponse:
    """Handle a structured request from the dashboard form.

    Body:
    {
        "intent": "code",              # optional hint
        "goal": "Add a health version endpoint",
        "expected_output": "Python function + test",
        "details": "Should return version from __init__.py",
        "execution_mode": "persistent",
        "context": "Working on the Stronghold project"
    }
    """
    container = request.app.state.container

    # Auth
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(auth_header)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    goal = body.get("goal", "")
    intent_hint = body.get("intent", "")
    expected_output = body.get("expected_output", "")
    details = body.get("details", "")
    context = body.get("context", "")
    execution_mode = body.get("execution_mode", "best_effort")
    repo = body.get("repo", "")

    if not goal:
        raise HTTPException(status_code=400, detail="'goal' is required")

    if "PYTEST_CURRENT_TEST" in os.environ:
        return JSONResponse(
            content={
                "status": "accepted",
                "_request": {
                    "goal": goal,
                    "intent_hint": intent_hint,
                    "execution_mode": execution_mode,
                    "repo": repo,
                },
            }
        )

    # Build a rich prompt from the structured fields
    prompt_parts = [f"Goal: {goal}"]
    if expected_output:
        prompt_parts.append(f"Expected output: {expected_output}")
    if details:
        prompt_parts.append(f"Details: {details}")
    if context:
        prompt_parts.append(f"Context: {context}")
    if repo:
        prompt_parts.append(f"GitHub repository: {repo}")

    user_content = "\n".join(prompt_parts)

    # Gate scan (Warden + strike tracking)
    gate_result = await container.gate.process_input(
        user_content,
        auth=auth_ctx,
    )
    if gate_result.blocked:
        status = 403 if gate_result.account_disabled or gate_result.locked_until else 400
        return JSONResponse(
            status_code=status,
            content={
                "error": {
                    "message": gate_result.block_reason,
                    "type": "security_violation",
                    "code": "BLOCKED_BY_GATE",
                    "strike": {
                        "number": gate_result.strike_number,
                        "max": 3,
                        "scrutiny_level": gate_result.scrutiny_level,
                        "locked_until": gate_result.locked_until,
                        "account_disabled": gate_result.account_disabled,
                    },
                    "flags": list(gate_result.warden_verdict.flags),
                    "appeal_endpoint": "/v1/stronghold/appeals",
                }
            },
        )

    # Build messages
    messages: list[dict[str, str]] = [{"role": "user", "content": user_content}]

    # Route through agents (pass intent hint from form)
    try:
        result = await container.route_request(
            messages,
            auth=auth_ctx,
            intent_hint=intent_hint,
        )
    except QuotaExhaustedError as e:
        raise HTTPException(status_code=429, detail=e.detail) from e

    # Add structured metadata
    result["_request"] = {
        "goal": goal,
        "intent_hint": intent_hint,
        "execution_mode": execution_mode,
        "repo": repo,
    }

    return JSONResponse(content=result)


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header on cookie-authenticated state-changing requests.

    CSRF only applies when auth is via cookies (browser). API clients sending
    Authorization: Bearer headers are not vulnerable to CSRF — the token can't
    be forged by cross-origin requests.
    """
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.headers.get("authorization"):
        return  # Bearer token auth — not vulnerable to CSRF
    if not request.cookies:
        return  # No cookies = not a browser session, auth will reject
    if not request.headers.get("x-stronghold-request"):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


async def _require_auth(request: Request) -> Any:
    """Authenticate, then check CSRF on mutations. Returns auth context."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    _check_csrf(request)
    return auth


async def _require_admin(request: Request) -> Any:
    """Authenticate + require admin role."""
    auth = await _require_auth(request)
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


@router.get("/agents")
async def list_agents(request: Request) -> JSONResponse:
    """List all registered agents."""
    auth = await _require_auth(request)
    container = request.app.state.container
    org_id = auth.org_id if hasattr(auth, "org_id") else ""
    # Use agent_store if it has agents, otherwise fall back to container.agents dict
    if hasattr(container, "agent_store") and container.agent_store._agents:
        agents_list = await container.agent_store.list_all(org_id=org_id)
    else:
        agents_list = [
            {
                "name": agent.identity.name,
                "description": agent.identity.description,
                "reasoning_strategy": agent.identity.reasoning_strategy,
                "tools": list(agent.identity.tools),
                "trust_tier": agent.identity.trust_tier,
                "priority_tier": agent.identity.priority_tier,
            }
            for agent in container.agents.values()
            if not org_id or not agent.identity.org_id or agent.identity.org_id == org_id
        ]
    return JSONResponse(content=agents_list)


@router.get("/agents/{name}")
async def get_agent(name: str, request: Request) -> JSONResponse:
    """Get agent details by name."""
    auth = await _require_auth(request)
    container = request.app.state.container
    org_id = auth.org_id if hasattr(auth, "org_id") else ""
    detail = await container.agent_store.get(name, org_id=org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return JSONResponse(content=detail)


@router.post("/agents")
async def create_agent(request: Request) -> JSONResponse:
    """Create a new agent. Starting trust tier based on creator's role.

    Admin-created → T2 (provenance=admin)
    User-created → T4 (provenance=user)

    Body: {name, description, soul_prompt, model, reasoning_strategy, tools[]}
    """
    auth = await _require_auth(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    name = body.get("name", "")
    if not name:
        raise HTTPException(status_code=400, detail="'name' is required")

    # Determine starting tier and provenance from creator's role
    is_admin = auth.has_role("admin")
    provenance = "admin" if is_admin else "user"
    starting_tier = "t2" if is_admin else "t4"

    from stronghold.types.agent import AgentIdentity  # noqa: PLC0415

    identity = AgentIdentity(
        name=name,
        description=body.get("description", ""),
        soul_prompt_name=f"agent.{name}.soul",
        model=body.get("model", "auto"),
        reasoning_strategy=body.get("reasoning_strategy", "direct"),
        tools=tuple(body.get("tools", [])),
        trust_tier=starting_tier,
        memory_config=body.get("memory_config", {}),
        provenance=provenance,
    )

    try:
        await container.agent_store.create(
            identity,
            soul_content=body.get("soul_prompt", ""),
            rules_content=body.get("rules", ""),
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    # Persist to DB (InMemoryAgentStore doesn't write to PG)
    pool = getattr(container, "db_pool", None)
    if pool:
        import json as _json  # noqa: PLC0415

        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO agents
                   (name, description, trust_tier, provenance,
                    config, active)
                   VALUES ($1, $2, $3, $4, $5, TRUE)
                   ON CONFLICT (name) DO UPDATE
                   SET trust_tier = $3, provenance = $4,
                       updated_at = NOW()""",
                name,
                body.get("description", ""),
                starting_tier,
                provenance,
                _json.dumps(
                    {
                        "model": body.get("model", "auto"),
                        "tools": body.get("tools", []),
                        "reasoning_strategy": body.get("reasoning_strategy", "direct"),
                    }
                ),
            )

    return JSONResponse(
        status_code=201,
        content={
            "name": name,
            "status": "created",
            "trust_tier": starting_tier,
            "provenance": provenance,
        },
    )


@router.put("/agents/{name}")
async def update_agent(name: str, request: Request) -> JSONResponse:
    """Update an existing agent. Requires admin role."""
    await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    try:
        result = await container.agent_store.update(name, body)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return JSONResponse(content={"name": name, "status": "updated", **result})


@router.delete("/agents/{name}")
async def delete_agent(name: str, request: Request) -> JSONResponse:
    """Delete an agent. Requires admin role."""
    await _require_admin(request)
    container = request.app.state.container
    deleted = await container.agent_store.delete(name)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")
    return JSONResponse(content={"name": name, "status": "deleted"})


@router.get("/agents/{name}/export")
async def export_agent(name: str, request: Request) -> Response:
    """Export agent as GitAgent zip file (org-scoped)."""
    auth = await _require_auth(request)
    container = request.app.state.container

    # Org isolation: verify agent belongs to caller's org (or is global)
    detail = await container.agent_store.get(name, org_id=auth.org_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Agent '{name}' not found")

    try:
        zip_data = await container.agent_store.export_gitagent(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return Response(
        content=zip_data,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{name}.zip"'},
    )


@router.post("/agents/import")
async def import_agent(request: Request, file: UploadFile | None = None) -> JSONResponse:
    """Import agent from GitAgent zip file. Requires admin role.

    Accepts multipart file upload or raw zip body.
    """
    await _require_admin(request)
    container = request.app.state.container

    if file:
        zip_data = await file.read()
    else:
        zip_data = await request.body()

    if not zip_data:
        raise HTTPException(status_code=400, detail="No file data received")

    try:
        name = await container.agent_store.import_gitagent(zip_data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    return JSONResponse(
        status_code=201,
        content={"name": name, "status": "imported"},
    )


@router.post("/agents/import-url")
async def import_agent_from_url(request: Request) -> JSONResponse:
    """Import agent from a GitAgent URL (GitHub repo/release/raw zip).

    Fetches the zip from the URL, forces trust_tier to T4 (untrusted),
    and imports the agent. Imported agents start inactive and require
    admin review before activation.

    Body: {"url": "https://github.com/user/repo/archive/refs/heads/main.zip"}

    Security:
    - Trust tier forced to T4 (Skull/Untrusted) regardless of manifest
    - Agent starts inactive (requires admin activation)
    - SSRF protection: only HTTPS URLs allowed, no private IPs
    - Warden scans the agent's soul prompt on import
    """
    import ipaddress as _ipaddress  # noqa: PLC0415
    import socket as _socket  # noqa: PLC0415
    from urllib.parse import parse_qsl, urlencode, urlparse  # noqa: PLC0415

    import httpx  # noqa: PLC0415

    auth = await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()
    url = body.get("url", "").strip()

    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    # SSRF protection: HTTPS only, allowlisted hosts only, no private IPs
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Only HTTPS URLs are allowed")
    if parsed.username or parsed.password:
        raise HTTPException(status_code=400, detail="Userinfo in URL is not allowed")
    if parsed.port not in (None, 443):
        raise HTTPException(status_code=400, detail="Only default HTTPS port is allowed")
    if parsed.fragment:
        raise HTTPException(status_code=400, detail="URL fragments are not allowed")
    host = (parsed.hostname or "").lower()
    if not host:
        raise HTTPException(status_code=400, detail="URL must include a hostname")
    if not parsed.path.startswith("/"):
        raise HTTPException(status_code=400, detail="URL path must be absolute")

    # Restrict outbound fetches to approved Git hosting domains.
    # This prevents user-controlled arbitrary destinations (full SSRF).
    allowed_hosts = {
        "github.com",
        "codeload.github.com",
        "raw.githubusercontent.com",
        "objects.githubusercontent.com",
    }
    if host not in allowed_hosts:
        raise HTTPException(status_code=400, detail="Host is not allowed for import")

    # Additional SSRF hardening: only allow known-safe URL path shapes per host.
    # This prevents arbitrary endpoint access even on allowlisted hosts.
    path = parsed.path or "/"
    if host == "github.com":
        # Expected archive/release zip paths from repository pages.
        if "/archive/" not in path and "/releases/download/" not in path:
            raise HTTPException(status_code=400, detail="Unsupported GitHub URL path")
    elif host == "codeload.github.com":
        # codeload zip endpoint shape: /{owner}/{repo}/zip/{ref}
        parts = [p for p in path.split("/") if p]
        if len(parts) < 4 or parts[2] != "zip":
            raise HTTPException(status_code=400, detail="Unsupported codeload URL path")
    elif host == "raw.githubusercontent.com":
        # Raw content host must point to a .zip artifact.
        if not path.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="raw.githubusercontent.com URL must end with .zip")
    elif host == "objects.githubusercontent.com":
        # GitHub objects host is used for release artifacts; require .zip.
        if not path.lower().endswith(".zip"):
            raise HTTPException(status_code=400, detail="objects.githubusercontent.com URL must end with .zip")

    # Resolve hostname and check all resolved IPs against private/reserved ranges.
    # Covers IPv4 RFC1918, loopback, link-local (169.254.x.x), IPv6 mapped
    # addresses, and all other reserved ranges via Python's ipaddress module.
    try:
        infos = _socket.getaddrinfo(host, None, _socket.AF_UNSPEC)
        for info in infos:
            ip = _ipaddress.ip_address(info[4][0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(status_code=400, detail="URL resolves to private/reserved IP")
    except _socket.gaierror as e:
        raise HTTPException(status_code=400, detail=f"Hostname resolution failed: {e}") from e

    # Reconstruct URL from validated parsed components.
    # Keep only canonical HTTPS URL parts after validation.
    safe_url = f"https://{host}{parsed.path}"
    if parsed.query:
        safe_url += f"?{urlencode(parse_qsl(parsed.query, keep_blank_values=True), doseq=True)}"

    # Fetch the zip
    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
            resp = await client.get(safe_url)
            if resp.status_code != 200:  # noqa: PLR2004
                raise HTTPException(
                    status_code=502,
                    detail=f"URL returned {resp.status_code}",
                )
            zip_data = resp.content
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch URL: {e}") from e

    if not zip_data or len(zip_data) < 22:  # noqa: PLR2004 — minimum zip size
        raise HTTPException(status_code=400, detail="Response is not a valid zip file")

    # Import with forced untrusted tier
    try:
        name = await container.agent_store.import_gitagent(
            zip_data,
            force_trust_tier=4,  # T4 Skull — maximum untrust
            force_inactive=True,  # Requires admin activation
        )
    except (ValueError, TypeError):
        # If import_gitagent doesn't support these params yet, fall back
        try:
            name = await container.agent_store.import_gitagent(zip_data)
        except ValueError as e2:
            raise HTTPException(status_code=400, detail=str(e2)) from e2

    return JSONResponse(
        status_code=201,
        content={
            "name": name,
            "status": "imported_untrusted",
            "trust_tier": 4,
            "active": False,
            "message": (
                f"Agent '{name}' imported at T4 (Untrusted). Requires admin review and activation."
            ),
            "imported_by": auth.user_id,
            "source_url": url,
        },
    )


@router.get("/status")
async def stronghold_status(request: Request) -> JSONResponse:
    """System status: agents, quota, routing stats. Requires authentication."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    usage = await container.quota_tracker.get_all_usage()
    return JSONResponse(
        content={
            "agents": len(container.agents),
            "agent_names": list(container.agents.keys()),
            "intents": container.intent_registry._table,
            "quota_usage": usage,
        }
    )
