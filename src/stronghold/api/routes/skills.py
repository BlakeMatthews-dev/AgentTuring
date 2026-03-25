"""API route: skills — CRUD for the skill ecosystem."""

from __future__ import annotations

import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.skills")

router = APIRouter()


def _select_forge_model(container: Any) -> str:
    """Pick a real configured LiteLLM model id for forge operations."""
    models = getattr(container.config, "models", {}) or {}
    preferred_names = ("mistral-large", "mistral-small", "gemini-flash")

    for name in preferred_names:
        cfg = models.get(name)
        if isinstance(cfg, dict):
            litellm_id = cfg.get("litellm_id")
            if isinstance(litellm_id, str) and litellm_id:
                return litellm_id

    for cfg in models.values():
        if isinstance(cfg, dict):
            litellm_id = cfg.get("litellm_id")
            if isinstance(litellm_id, str) and litellm_id:
                return litellm_id

    return "mistral/mistral-large-latest"


def _sanitize_generated_skill(content: str) -> str:
    """Normalize raw LLM output into parseable SKILL.md text."""
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:markdown|md)?\s*\n", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\n```\s*$", "", cleaned)

    frontmatter_start = cleaned.find("---\n")
    if frontmatter_start > 0:
        cleaned = cleaned[frontmatter_start:]

    return cleaned.strip()


def _ensure_skill_body(content: str) -> str:
    """Repair forge output when the model returns frontmatter without a body."""
    match = re.match(r"^(---\s*\n.*?\n---)\s*$", content, re.DOTALL)
    if not match:
        return content

    description_match = re.search(r'^description:\s*"?(.*?)"?\s*$', content, re.MULTILINE)
    default_desc = "Use this skill as described."
    description = description_match.group(1).strip() if description_match else default_desc
    body = (
        f"Use this skill when {description.lower()}.\n"
        "Follow the declared parameters exactly and return concise, structured results."
    )
    return f"{match.group(1)}\n\n{body}"


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


@router.get("/v1/stronghold/skills")
async def list_skills(request: Request) -> JSONResponse:
    """List all registered skills (M2: org-scoped)."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    org_id = auth.org_id if hasattr(auth, "org_id") else ""
    # Use org-scoped list if skill_registry supports it, else fall back
    if hasattr(container, "skill_registry") and hasattr(container.skill_registry, "list_all"):
        skills = container.skill_registry.list_all(org_id=org_id)
    else:
        skills = container.tool_registry.list_all()
    return JSONResponse(
        content=[
            {
                "name": s.name,
                "description": s.description,
                "groups": list(s.groups),
                "endpoint": s.endpoint,
            }
            for s in skills
        ]
    )


@router.post("/v1/stronghold/skills/forge")
async def forge_skill(request: Request) -> JSONResponse:
    """Forge a new skill via LLM generation. Admin only."""
    _check_csrf(request)
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

    body: dict[str, Any] = await request.json()
    description = body.get("description", "")
    if not description:
        raise HTTPException(status_code=400, detail="description is required")

    # Generate SKILL.md via LLM
    forge_prompt = (
        "Generate a SKILL.md file for an agent tool.\n"
        "The user wants: " + description + "\n\n"
        "Output ONLY the SKILL.md content in this exact format:\n"
        "---\n"
        "name: snake_case_name\n"
        'description: "One-line description"\n'
        "groups: [general]\n"
        "parameters:\n"
        "  type: object\n"
        "  properties:\n"
        "    param_name:\n"
        "      type: string\n"
        '      description: "What this param does"\n'
        "  required: [param_name]\n"
        'trust_tier: "t3"\n'
        "---\n\n"
        "System prompt instructions here.\n\n"
        "Rules: name must be snake_case (a-z, 0-9, underscores, 2-51 chars). "
        "Output ONLY the SKILL.md content, no explanations."
    )

    try:
        forge_model = _select_forge_model(container)
        result = await container.llm.complete(
            messages=[{"role": "user", "content": forge_prompt}],
            model=forge_model,
            max_tokens=1500,
            temperature=0.3,
        )
        choices = result.get("choices", [])
        generated = choices[0].get("message", {}).get("content", "") if choices else ""
        generated = _sanitize_generated_skill(generated)
        generated = _ensure_skill_body(generated)
    except Exception as e:
        logger.exception("LLM generation failed during skill forge: %s", e)
        raise HTTPException(status_code=502, detail="LLM generation failed") from e

    if not generated.strip():
        raise HTTPException(status_code=502, detail="LLM returned empty content")

    # Security scan the generated content
    verdict = await container.warden.scan(generated, "tool_result")
    if not verdict.clean:
        raise HTTPException(
            status_code=400,
            detail=f"Generated skill blocked by security scan: {', '.join(verdict.flags)}",
        )

    # Parse the generated SKILL.md
    from stronghold.skills.parser import parse_skill_file  # noqa: PLC0415

    try:
        skill = parse_skill_file(generated)
    except Exception as e:
        logger.exception("Generated skill failed validation: %s", e)
        raise HTTPException(
            status_code=422,
            detail="Generated skill failed validation",
        ) from e

    if skill is None:
        raise HTTPException(status_code=422, detail="Failed to parse generated skill")

    # Force trust tier to t3 (forged)
    from stronghold.types.skill import SkillDefinition  # noqa: PLC0415

    skill = SkillDefinition(
        name=skill.name,
        description=skill.description,
        groups=skill.groups,
        parameters=skill.parameters,
        system_prompt=skill.system_prompt,
        trust_tier="t3",
        source="forge",
    )

    # Register in skill registry
    from stronghold.skills.registry import InMemorySkillRegistry  # noqa: PLC0415

    if hasattr(container, "skill_registry") and isinstance(
        container.skill_registry, InMemorySkillRegistry
    ):
        container.skill_registry.register(skill)

    return JSONResponse(
        status_code=201,
        content={
            "name": skill.name,
            "description": skill.description,
            "groups": list(skill.groups),
            "trust_tier": skill.trust_tier,
            "status": "forged",
        },
    )


@router.delete("/v1/stronghold/skills/{name}")
async def delete_skill(name: str, request: Request) -> JSONResponse:
    """Delete a skill. Admin only."""
    _check_csrf(request)
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

    return JSONResponse(
        content={"status": "deleted", "name": name},
    )


@router.get("/v1/stronghold/skills/{name}")
async def get_skill(name: str, request: Request) -> JSONResponse:
    """Get full skill definition by name."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    defn = container.tool_registry.get(name)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    return JSONResponse(
        content={
            "name": defn.name,
            "description": defn.description,
            "groups": list(defn.groups),
            "endpoint": defn.endpoint,
            "parameters": defn.parameters,
            "system_prompt": defn.system_prompt if hasattr(defn, "system_prompt") else "",
            "trust_tier": defn.trust_tier if hasattr(defn, "trust_tier") else "t2",
        }
    )


@router.put("/v1/stronghold/skills/{name}")
async def update_skill(name: str, request: Request) -> JSONResponse:
    """Update an existing skill. Admin only.

    Body: {description?, groups?, parameters?, system_prompt?}
    """
    _check_csrf(request)
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

    defn = container.tool_registry.get(name)
    if not defn:
        raise HTTPException(status_code=404, detail=f"Skill '{name}' not found")

    return JSONResponse(
        content={"name": name, "status": "updated"},
    )


@router.post("/v1/stronghold/skills/validate")
async def validate_skill(request: Request) -> JSONResponse:
    """Validate a SKILL.md content string.

    Body: {"content": "---\\nname: my-skill\\n..."}
    Returns parsed fields + validation errors + security scan results.
    """
    _check_csrf(request)
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        await container.auth_provider.authenticate(auth_header, headers=dict(request.headers))
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="'content' is required")

    from stronghold.skills.parser import parse_skill_file  # noqa: PLC0415

    try:
        skill = parse_skill_file(content)
        if skill is None:
            return JSONResponse(
                content={"valid": False, "errors": ["Failed to parse skill"], "parsed": None}
            )
        return JSONResponse(
            content={
                "valid": True,
                "errors": [],
                "parsed": {
                    "name": skill.name,
                    "description": skill.description,
                    "parameters": skill.parameters,
                    "groups": list(skill.groups) if hasattr(skill, "groups") else [],
                },
            }
        )
    except Exception as e:
        logger.exception("Skill validation failed: %s", e)
        return JSONResponse(
            content={
                "valid": False,
                "errors": ["Skill validation failed"],
                "parsed": None,
            }
        )


@router.post("/v1/stronghold/skills/test")
async def test_skill(request: Request) -> JSONResponse:
    """Test a skill against sample input. Admin only.

    Body: {"skill_name": "my-skill", "test_input": {"param1": "value1"}}
    Executes the skill and returns the result.
    """
    _check_csrf(request)
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    if not auth.has_role("admin"):
        raise HTTPException(status_code=403, detail="Admin role required for skill installation")

    body: dict[str, Any] = await request.json()
    skill_name = body.get("skill_name", "")
    test_input = body.get("test_input", {})

    if not skill_name:
        raise HTTPException(status_code=400, detail="'skill_name' is required")

    # M1: Warden scan test_input before execution (Sentinel-lite).
    # Full Sentinel requires schema lookup; Warden catches injection.
    test_input_str = str(test_input)
    if hasattr(container, "warden") and container.warden:
        verdict = await container.warden.scan(test_input_str, "user_input")
        if not verdict.clean:
            return JSONResponse(
                status_code=400,
                content={
                    "skill_name": skill_name,
                    "success": False,
                    "output": f"Test input blocked by Warden: {', '.join(verdict.flags)}",
                },
            )

    try:
        result = await container.tool_dispatcher.execute(skill_name, test_input)

        # M1: Warden scan output too (post-call check)
        result_str = str(result)[:2000]
        if hasattr(container, "warden") and container.warden:
            out_verdict = await container.warden.scan(result_str, "tool_result")
            if not out_verdict.clean:
                result_str = f"[Output flagged by Warden: {', '.join(out_verdict.flags)}]"

        return JSONResponse(
            content={
                "skill_name": skill_name,
                "success": not str(result).startswith("Error"),
                "output": result_str,
            }
        )
    except Exception as e:
        logger.exception("Skill test execution failed for '%s': %s", skill_name, e)
        return JSONResponse(
            content={
                "skill_name": skill_name,
                "success": False,
                "output": "Error: Skill execution failed",
            }
        )
