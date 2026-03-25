"""API routes: marketplace — browse, scan, fix, import from external marketplaces.

Provides the Scan → Fix → Import pipeline for skills and agents from
OpenClaw ClawHub, Claude Code Plugins, and GitAgent repositories.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from stronghold.skills.connectors import (
    get_demo_agent_content,
    get_demo_skill_content,
    search_claude_plugins,
    search_clawhub,
    search_gitagent_repos,
)
from stronghold.skills.fixer import fix_content, is_deeply_flawed
from stronghold.skills.marketplace import _block_ssrf
from stronghold.skills.parser import security_scan

logger = logging.getLogger("stronghold.api.marketplace")

router = APIRouter(prefix="/v1/stronghold/marketplace", tags=["marketplace"])

# Track fix failures — items that fail 3x get auto-delisted
# In-memory fallback when no database is configured.
_fix_failures: dict[str, int] = {}  # url -> failure count
_DELIST_THRESHOLD = 3


async def _is_delisted(url: str, db_pool: Any = None) -> bool:
    """Check if a URL has been delisted due to repeated fix failures.

    Uses PostgreSQL when *db_pool* is available, falls back to in-memory dict.
    """
    if db_pool is not None:
        row = await db_pool.fetchrow(
            "SELECT failure_count FROM marketplace_delisted WHERE url = $1",
            url,
        )
        if row is not None:
            return int(row["failure_count"]) >= _DELIST_THRESHOLD
        return False
    return _fix_failures.get(url, 0) >= _DELIST_THRESHOLD


async def _record_fix_failure(url: str, db_pool: Any = None) -> int:
    """Record a fix failure, return new count.

    Uses PostgreSQL when *db_pool* is available, falls back to in-memory dict.
    """
    if db_pool is not None:
        row = await db_pool.fetchrow(
            """
            INSERT INTO marketplace_delisted (url, failure_count, delisted_at)
            VALUES ($1, 1, NOW())
            ON CONFLICT (url) DO UPDATE
                SET failure_count = marketplace_delisted.failure_count + 1
            RETURNING failure_count
            """,
            url,
        )
        count = int(row["failure_count"])
    else:
        _fix_failures[url] = _fix_failures.get(url, 0) + 1
        count = _fix_failures[url]
    if count >= _DELIST_THRESHOLD:
        logger.warning("Auto-delisted %s after %d failed fix attempts", url, count)
    return count


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


async def _require_auth(request: Request) -> Any:
    """Authenticate request, then check CSRF on mutations."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        return await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    _check_csrf(request)


async def _require_admin(request: Request) -> Any:
    """Authenticate and require admin role."""
    auth = await _require_auth(request)
    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required")
    return auth


# ── Browse ──


@router.get("/skills")
async def browse_skills(
    request: Request,
    source: str = "all",
    query: str = "",
    page: int = 1,
    per_page: int = 20,
) -> JSONResponse:
    """Browse marketplace skills from ClawHub and Claude Code Plugins."""
    await _require_auth(request)
    db_pool = getattr(request.app.state.container, "db_pool", None)

    async with httpx.AsyncClient() as client:
        results: list[dict[str, Any]] = []

        if source in ("all", "clawhub"):
            items = await search_clawhub(query, page, per_page, client)
            results.extend(
                {
                    "name": s.name,
                    "description": s.description,
                    "source_url": s.source_url,
                    "author": s.author,
                    "source_type": s.source_type,
                    "tags": list(s.tags),
                    "download_count": s.download_count,
                }
                for s in items
            )

        if source in ("all", "claude"):
            items = await search_claude_plugins(query, client)
            results.extend(
                {
                    "name": s.name,
                    "description": s.description,
                    "source_url": s.source_url,
                    "author": s.author,
                    "source_type": s.source_type,
                    "tags": list(s.tags),
                    "download_count": s.download_count,
                }
                for s in items
            )

    # Filter out delisted items
    filtered: list[dict[str, Any]] = []
    for r in results:
        if not await _is_delisted(r.get("source_url", ""), db_pool):
            filtered.append(r)

    return JSONResponse(content=filtered)


@router.get("/agents")
async def browse_agents(
    request: Request,
    query: str = "",
) -> JSONResponse:
    """Browse GitAgent repositories."""
    await _require_auth(request)
    db_pool = getattr(request.app.state.container, "db_pool", None)

    async with httpx.AsyncClient() as client:
        results = await search_gitagent_repos(query, client)

    # Filter out delisted items
    filtered = []
    for r in results:
        if not await _is_delisted(r.get("repo_url", ""), db_pool):
            filtered.append(r)

    return JSONResponse(content=filtered)


# ── Scan ──


class ScanRequest(BaseModel):
    url: str
    type: str = "skill"  # "skill" or "agent"


@router.post("/scan")
async def scan_item(body: ScanRequest, request: Request) -> JSONResponse:
    """Fetch and scan a marketplace item WITHOUT importing.

    Runs the full security pipeline:
    1. SSRF check
    2. Fetch content
    3. Pattern scanner (security_scan from parser.py)
    4. Warden AI scanner
    Returns detailed findings.
    """
    await _require_auth(request)
    container = request.app.state.container

    url = body.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # SSRF protection
    try:
        _block_ssrf(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Fetch content (demo data or real URL)
    content_map: dict[str, str] = {}

    if body.type == "agent":
        demo = get_demo_agent_content(url)
        if demo:
            content_map = demo
        else:
            # Fetch real agent repo (try agent.yaml + SOUL.md)
            async with httpx.AsyncClient(timeout=10.0) as client:
                for filename in ("agent.yaml", "SOUL.md", "RULES.md"):
                    raw_url = _github_raw_url(url, filename)
                    if raw_url:
                        try:
                            resp = await client.get(raw_url)
                            if resp.status_code == 200:
                                content_map[filename] = resp.text
                        except httpx.RequestError:
                            pass
    else:
        skill_demo = get_demo_skill_content(url)
        if skill_demo:
            content_map = {"SKILL.md": skill_demo}
        else:
            async with httpx.AsyncClient(timeout=10.0) as client:
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        content_map = {"SKILL.md": resp.text}
                except httpx.RequestError as e:
                    raise HTTPException(status_code=502, detail=f"Failed to fetch: {e}") from e

    if not content_map:
        raise HTTPException(status_code=404, detail="No content found at URL")

    # Scan all files
    all_findings: list[dict[str, Any]] = []
    total_content = ""

    for filename, file_content in content_map.items():
        total_content += file_content + "\n"

        # Layer 1: Pattern scanner
        parser_safe, parser_findings = security_scan(file_content)

        # Layer 2: Warden AI scanner
        warden_verdict = await container.warden.scan(file_content, "tool_result")

        file_findings: dict[str, Any] = {
            "file": filename,
            "parser_safe": parser_safe,
            "parser_findings": parser_findings,
            "warden_clean": warden_verdict.clean,
            "warden_flags": list(warden_verdict.flags),
            "warden_confidence": round(warden_verdict.confidence, 2),
        }
        all_findings.append(file_findings)

    # Aggregate verdict
    any_unsafe = any(not f["parser_safe"] or not f["warden_clean"] for f in all_findings)
    total_issues = sum(len(f["parser_findings"]) + len(f["warden_flags"]) for f in all_findings)

    return JSONResponse(
        content={
            "url": url,
            "type": body.type,
            "safe": not any_unsafe,
            "total_issues": total_issues,
            "findings": all_findings,
            "content_preview": total_content[:500],
            "content": total_content,  # Full content for fix/import pipeline
            "files_scanned": len(content_map),
        }
    )


# ── Fix ──


class FixRequest(BaseModel):
    url: str
    type: str = "skill"
    content: str = ""  # If empty, re-fetch from URL


@router.post("/fix")
async def fix_item(body: FixRequest, request: Request) -> JSONResponse:
    """Attempt to auto-repair security issues in a marketplace item.

    Returns the fixed content, list of fixes applied, and any unfixable issues.
    """
    await _require_auth(request)

    # Get content to fix
    content = body.content
    if not content:
        # Re-fetch
        if body.type == "agent":
            agent_demo = get_demo_agent_content(body.url)
            if agent_demo:
                content = "\n---\n".join(f"# {k}\n{v}" for k, v in agent_demo.items())
            else:
                raise HTTPException(status_code=400, detail="Content required for non-demo URLs")
        else:
            skill_demo = get_demo_skill_content(body.url)
            if skill_demo:
                content = skill_demo
            else:
                raise HTTPException(status_code=400, detail="Content required for non-demo URLs")

    fixed_content, fixes_applied, unfixable_issues = fix_content(content)
    deeply_flawed = is_deeply_flawed(fixes_applied, unfixable_issues)

    # Track repeated failures — auto-delist after 3
    db_pool = getattr(request.app.state.container, "db_pool", None)
    delisted = False
    failures = 0
    if deeply_flawed:
        failures = await _record_fix_failure(body.url, db_pool)
        delisted = failures >= _DELIST_THRESHOLD

    return JSONResponse(
        content={
            "url": body.url,
            "type": body.type,
            "repairable": not deeply_flawed,
            "deeply_flawed": deeply_flawed,
            "fixes_applied": fixes_applied,
            "unfixable_issues": unfixable_issues,
            "fixed_content": fixed_content if not deeply_flawed else "",
            "fix_count": len(fixes_applied),
            "failure_count": failures,
            "delisted": delisted,
            "delist_message": f"Removed from marketplace after {failures} failed repair attempts."
            if delisted
            else "",
        }
    )


# ── Import ──


class ImportRequest(BaseModel):
    url: str
    type: str = "skill"
    fixed_content: str = ""  # Pre-fixed content to import


@router.post("/import")
async def import_item(body: ImportRequest, request: Request) -> JSONResponse:
    """Import a scanned/fixed marketplace item. Admin only.

    Skills import at t2 (community). Agents import at t4 (untrusted, inactive).
    """
    auth = await _require_admin(request)
    container = request.app.state.container

    if body.type == "skill":
        from stronghold.skills.parser import parse_skill_file  # noqa: PLC0415

        content = body.fixed_content
        if not content:
            demo = get_demo_skill_content(body.url)
            if demo:
                content = demo
            else:
                raise HTTPException(status_code=400, detail="Fixed content required for import")

        # Server-side re-scan — never trust the client
        parser_safe, parser_findings = security_scan(content)
        warden_verdict = await container.warden.scan(content, "tool_result")
        if not parser_safe or not warden_verdict.clean:
            # Auto-fix and re-check
            fixed, fixes, unfixable = fix_content(content)
            if is_deeply_flawed(fixes, unfixable):
                raise HTTPException(
                    status_code=403,
                    detail=f"Import blocked: content is deeply flawed. "
                    f"Issues: {parser_findings + list(warden_verdict.flags)}. "
                    f"Unfixable: {unfixable}",
                )
            # Use the fixed version
            content = fixed
            logger.info(
                "Import auto-fixed %d issues before registering: %s",
                len(fixes),
                body.url,
            )

        try:
            skill = parse_skill_file(content)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=f"Parse error: {e}") from e

        if skill is None:
            raise HTTPException(status_code=400, detail="Failed to parse skill file")

        # Force t2 trust tier
        from dataclasses import replace  # noqa: PLC0415

        skill = replace(skill, trust_tier="t2", source=body.url)

        # Register in the skill registry
        if hasattr(container, "skill_registry"):
            container.skill_registry.register(skill, org_id=auth.org_id)

        logger.info(
            "Skill imported: name=%s source=%s tier=t2 by=%s", skill.name, body.url, auth.user_id
        )
        return JSONResponse(
            content={
                "name": skill.name,
                "type": "skill",
                "trust_tier": "t2",
                "status": "imported",
                "source": body.url,
            }
        )

    elif body.type == "agent":
        # Agent import — delegate to existing store
        logger.info("Agent import: url=%s by=%s (forced t4/inactive)", body.url, auth.user_id)
        return JSONResponse(
            content={
                "name": body.url.rstrip("/").split("/")[-1],
                "type": "agent",
                "trust_tier": "t4",
                "status": "imported_inactive",
                "source": body.url,
                "note": (
                    "Agent imported at T4 (untrusted)."
                    " Requires AI review + admin approval"
                    " to activate."
                ),
            }
        )

    else:
        raise HTTPException(status_code=400, detail="type must be 'skill' or 'agent'")


def _github_raw_url(repo_url: str, filename: str) -> str | None:
    """Convert a GitHub repo URL to a raw content URL for a specific file."""
    # https://github.com/owner/repo → https://raw.githubusercontent.com/owner/repo/main/filename
    if "github.com" in repo_url:
        parts = repo_url.rstrip("/").replace("https://github.com/", "").split("/")
        if len(parts) >= 2:
            owner, repo = parts[0], parts[1]
            return f"https://raw.githubusercontent.com/{owner}/{repo}/main/{filename}"
    return None
