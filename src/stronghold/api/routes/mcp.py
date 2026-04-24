"""MCP server management API.

Endpoints for the full MCP lifecycle:
- Browse catalog of known MCP servers
- Deploy/stop/remove managed servers in K8s
- List deployed servers with status
- Register custom/remote servers from repo URLs
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.mcp")

router = APIRouter(prefix="/v1/stronghold/mcp")


_ENV_METACHARS = (";", "|", "&", "`", "$(", "${", "\n", "\r", "\0")
_ENV_KEY_MAX_LEN = 64
_ENV_VAL_MAX_LEN = 4096


def _sanitize_env(raw: dict[str, Any]) -> dict[str, str]:
    """Validate env vars for custom MCP images — closes BACKLOG D5 (env)."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="env must be a mapping")
    cleaned: dict[str, str] = {}
    for key, val in raw.items():
        if not isinstance(key, str) or not key:
            raise HTTPException(status_code=400, detail="env keys must be non-empty strings")
        if len(key) > _ENV_KEY_MAX_LEN:
            raise HTTPException(status_code=400, detail=f"env key too long: {key!r}")
        if not all(c.isalnum() or c == "_" for c in key):
            raise HTTPException(
                status_code=400,
                detail=f"env key must be alphanumeric + underscore: {key!r}",
            )
        val_s = str(val)
        if len(val_s) > _ENV_VAL_MAX_LEN:
            raise HTTPException(status_code=400, detail=f"env value too long for {key!r}")
        for meta in _ENV_METACHARS:
            if meta in val_s:
                raise HTTPException(
                    status_code=400,
                    detail=f"env value for {key!r} contains forbidden metacharacter {meta!r}",
                )
        cleaned[key] = val_s
    return cleaned


def _sanitize_secrets(raw: dict[str, Any], auth_ctx: Any) -> dict[str, str]:
    """Restrict secret references to the caller's namespace — BACKLOG D5 (secrets)."""
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="secrets must be a mapping")
    roles = getattr(auth_ctx, "roles", None) or frozenset()
    is_super = "super_admin" in roles
    org_id = getattr(auth_ctx, "org_id", "") or ""
    tenant_prefix = f"stronghold-{org_id}-" if org_id else "stronghold-"
    shared_prefix = "stronghold-shared-"
    cleaned: dict[str, str] = {}
    for key, ref in raw.items():
        if not isinstance(key, str) or not key:
            raise HTTPException(
                status_code=400,
                detail="secret keys must be non-empty strings",
            )
        ref_s = str(ref)
        # ref is like "my-secret:key" or "secretRef/my-secret/key"
        secret_name = ref_s.split(":", 1)[0].split("/")[0] or ref_s
        if is_super and secret_name.startswith(shared_prefix):
            cleaned[key] = ref_s
            continue
        if not secret_name.startswith(tenant_prefix):
            raise HTTPException(
                status_code=403,
                detail=(
                    f"secret {secret_name!r} not in tenant namespace "
                    f"(must start with {tenant_prefix!r})"
                ),
            )
        cleaned[key] = ref_s
    return cleaned


def _require_org_match(server: Any, auth_ctx: Any) -> None:
    """Cross-tenant guard for mutation endpoints — closes BACKLOG C6/H12.

    Super-admins (role includes 'super_admin') bypass the check so they
    can manage built-in / global servers. Everyone else must be acting
    on a server in their own org.
    """
    roles = getattr(auth_ctx, "roles", None) or frozenset()
    if "super_admin" in roles:
        return
    server_org = getattr(server, "org_id", "") or ""
    caller_org = getattr(auth_ctx, "org_id", "") or ""
    if not server_org:
        # Built-in / global servers require super-admin to mutate.
        raise HTTPException(
            status_code=403,
            detail="super_admin role required to mutate global MCP servers",
        )
    if server_org != caller_org:
        raise HTTPException(
            status_code=403,
            detail=f"MCP server '{getattr(server, 'name', '?')}' belongs to another org",
        )


def _check_csrf(request: Request) -> None:
    """Verify CSRF defense header on cookie-authenticated mutations.

    CSRF only applies when auth is via cookies (browser session).
    Bearer token auth and unauthenticated requests are not CSRF-vulnerable.
    """
    if request.method not in ("POST", "PUT", "DELETE"):
        return
    if request.headers.get("authorization"):
        return  # Bearer token — not CSRF-vulnerable
    # Only enforce CSRF when a session cookie is present (browser auth)
    if not request.cookies:
        return  # No cookies = not a browser session, auth will reject
    if not request.headers.get("x-stronghold-request"):
        raise HTTPException(
            status_code=403,
            detail="Missing X-Stronghold-Request header (CSRF protection)",
        )


@router.get("/catalog")
async def list_catalog(request: Request) -> JSONResponse:
    """List available MCP servers from the built-in catalog."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    return JSONResponse(content={"servers": container.mcp_registry.catalog()})


@router.get("/registries/search")
async def search_registries(request: Request) -> JSONResponse:
    """Search external MCP registries (Smithery, Official, Glama).

    Query params:
    - q: search query (required)
    - registry: filter to specific registry (smithery, official, glama, or "all")
    - scan: if "true", run security scan on results
    """
    from stronghold.mcp.registries import (  # noqa: PLC0415
        scan_registry_server,
        search_all_registries,
        search_glama,
        search_official_registry,
        search_smithery,
    )

    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    query = request.query_params.get("q", "")
    if not query:
        raise HTTPException(status_code=400, detail="'q' query parameter required")

    registry_filter = request.query_params.get("registry", "all")
    do_scan = request.query_params.get("scan", "false").lower() == "true"

    # Search selected registries
    if registry_filter == "all":
        grouped = await search_all_registries(query)
        all_results = []
        for servers in grouped.values():
            all_results.extend(servers)
    elif registry_filter == "smithery":
        all_results = await search_smithery(query)
    elif registry_filter == "official":
        all_results = await search_official_registry(query)
    elif registry_filter == "glama":
        all_results = await search_glama(query)
    else:
        raise HTTPException(status_code=400, detail=f"Unknown registry: {registry_filter}")

    # Security scan if requested
    if do_scan:
        import asyncio  # noqa: PLC0415

        warden = container.warden
        scanned = await asyncio.gather(
            *(scan_registry_server(s, warden=warden) for s in all_results)
        )
        all_results = list(scanned)

    return JSONResponse(
        content={
            "query": query,
            "registry": registry_filter,
            "scanned": do_scan,
            "total": len(all_results),
            "servers": [s.to_dict() for s in all_results],
        }
    )


@router.get("/servers")
async def list_servers(request: Request) -> JSONResponse:
    """List all deployed/registered MCP servers."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    servers = container.mcp_registry.list_all(org_id=auth_ctx.org_id)

    # Enrich with live pod status if deployer is available
    result = []
    for s in servers:
        data = s.to_dict()
        if hasattr(container, "mcp_deployer") and container.mcp_deployer:
            try:
                pod_status = await container.mcp_deployer.get_pod_status(s)
                data["pod"] = pod_status
            except Exception:
                data["pod"] = {"phase": "unknown"}
        result.append(data)

    return JSONResponse(content={"servers": result})


@router.post("/servers")
async def deploy_server(request: Request) -> JSONResponse:
    """Deploy an MCP server.

    Body options:
    - {"catalog": "github"} — deploy from built-in catalog
    - {"name": "my-server", "image": "ghcr.io/...", ...} — custom image
    - {"repo_url": "https://github.com/..."} — clone, scan, build, deploy (future)
    """
    _check_csrf(request)
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()

    # Option 1: Deploy from catalog
    catalog_name = body.get("catalog")
    if catalog_name:
        try:
            server = container.mcp_registry.register_from_catalog(
                catalog_name,
                org_id=auth_ctx.org_id,
                env_overrides=body.get("env"),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        # Deploy to K8s
        if container.mcp_deployer:
            try:
                server = await container.mcp_deployer.deploy(server)
            except Exception as e:
                logger.warning("K8s deploy failed for %s: %s", catalog_name, e)
                from stronghold.mcp.types import MCPServerStatus as _MCPStatus  # noqa: PLC0415

                server.status = _MCPStatus.FAILED
                server.error = str(e)

        return JSONResponse(
            status_code=201,
            content={
                "server": server.to_dict(),
                "message": f"Deployed {catalog_name} from catalog",
            },
        )

    # Option 2: Custom image
    name = body.get("name")
    image = body.get("image")
    if name and image:
        # BACKLOG D5 fix: custom-image deploy requires admin role.
        # Catalog deploys (Option 1 above) remain open to engineers.
        caller_roles = getattr(auth_ctx, "roles", None) or frozenset()
        if "admin" not in caller_roles and "super_admin" not in caller_roles:
            raise HTTPException(
                status_code=403,
                detail="admin role required for custom MCP image deployment",
            )

        import re as _re  # noqa: PLC0415

        from stronghold.mcp.types import MCPServerSpec  # noqa: PLC0415

        # Validate name: K8s-safe (lowercase alphanumeric + hyphens, max 40 chars)
        if not _re.match(r"^[a-z0-9][a-z0-9-]{0,38}[a-z0-9]$", str(name)):
            raise HTTPException(
                status_code=400,
                detail="name must be lowercase alphanumeric + hyphens, 2-40 chars",
            )

        # Validate image: must be from allowed registries, no shell metacharacters
        from stronghold.mcp.registry import MCPRegistry  # noqa: PLC0415

        allowed_registries = MCPRegistry.ALLOWED_IMAGE_PREFIXES
        image_str = str(image)
        if not any(image_str.startswith(r) for r in allowed_registries):
            raise HTTPException(
                status_code=400,
                detail=f"Image must be from allowed registries: {', '.join(allowed_registries)}. "
                "Contact admin to whitelist additional registries.",
            )
        if any(c in image_str for c in (";", "&", "|", "$", "`", "\n", "\r")):
            raise HTTPException(status_code=400, detail="Image contains invalid characters")

        # Validate trust_tier: enum only
        valid_tiers = {"t0", "t1", "t2", "t3", "t4", "skull"}
        trust_tier = str(body.get("trust_tier", "t3"))
        if trust_tier not in valid_tiers:
            raise HTTPException(
                status_code=400,
                detail=f"trust_tier must be one of: {', '.join(sorted(valid_tiers))}",
            )

        # Validate port: reasonable range
        port = int(body.get("port", 3000))
        if not (1024 <= port <= 65535):  # noqa: PLR2004
            raise HTTPException(status_code=400, detail="port must be 1024-65535")

        # BACKLOG D5 fix: env var + secret allowlist for custom image deploy.
        # - env: reject any value containing shell metachars; cap key length.
        # - secrets: restrict secretKeyRef to the caller's tenant namespace
        #   (stronghold-<org_id>). Super-admins can reference shared secrets
        #   prefixed `stronghold-shared-`.
        raw_env = body.get("env", {}) or {}
        raw_secrets = body.get("secrets", {}) or {}
        env = _sanitize_env(raw_env)
        secrets = _sanitize_secrets(raw_secrets, auth_ctx)

        spec = MCPServerSpec(
            name=name,
            image=image_str,
            description=str(body.get("description", ""))[:200],
            port=port,
            env=env,
            secrets=secrets,
            trust_tier=trust_tier,
            # args are NOT user-controllable — always use transport default
        )
        server = container.mcp_registry.register(spec, org_id=auth_ctx.org_id)

        if container.mcp_deployer:
            try:
                server = await container.mcp_deployer.deploy(server)
            except Exception as e:
                logger.warning("K8s deploy failed for %s: %s", name, e)
                from stronghold.mcp.types import MCPServerStatus  # noqa: PLC0415

                server.status = MCPServerStatus.FAILED
                server.error = str(e)

        return JSONResponse(
            status_code=201,
            content={"server": server.to_dict(), "message": f"Deployed {name}"},
        )

    # Option 3: GitHub repo (future — scan, build, deploy)
    repo_url = body.get("repo_url")
    if repo_url:
        # For now, return the pipeline status — full implementation in v1.1
        return JSONResponse(
            status_code=202,
            content={
                "message": "Repository pipeline accepted",
                "repo_url": repo_url,
                "pipeline": {
                    "clone": "pending",
                    "scan": "pending",
                    "build": "pending",
                    "deploy": "pending",
                    "discover": "pending",
                },
                "note": (
                    "Repo-to-deploy pipeline ships in v1.1."
                    " Use 'catalog' or 'image' for"
                    " immediate deployment."
                ),
            },
        )

    raise HTTPException(status_code=400, detail="Provide 'catalog', 'image'+'name', or 'repo_url'")


@router.post("/servers/{name}/stop")
async def stop_server(name: str, request: Request) -> JSONResponse:
    """Stop (scale to 0) an MCP server."""
    _check_csrf(request)
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    server = container.mcp_registry.get(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    _require_org_match(server, auth_ctx)  # BACKLOG H12 fix

    if container.mcp_deployer:
        server = await container.mcp_deployer.stop(server)

    return JSONResponse(content={"server": server.to_dict()})


@router.post("/servers/{name}/start")
async def start_server(name: str, request: Request) -> JSONResponse:
    """Start (scale to 1) a stopped MCP server."""
    _check_csrf(request)
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    server = container.mcp_registry.get(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    _require_org_match(server, auth_ctx)  # BACKLOG H12 fix

    if container.mcp_deployer:
        server = await container.mcp_deployer.start(server)

    return JSONResponse(content={"server": server.to_dict()})


@router.delete("/servers/{name}")
async def remove_server(name: str, request: Request) -> JSONResponse:
    """Remove an MCP server entirely (delete K8s resources)."""
    _check_csrf(request)
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth_ctx = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    server = container.mcp_registry.get(name)
    if not server:
        raise HTTPException(status_code=404, detail=f"MCP server '{name}' not found")
    _require_org_match(server, auth_ctx)  # BACKLOG C6 fix

    if container.mcp_deployer:
        await container.mcp_deployer.remove(server)

    container.mcp_registry.remove(name)
    return JSONResponse(content={"message": f"Removed {name}", "status": "removed"})
