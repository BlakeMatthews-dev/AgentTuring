"""API route: admin — learnings, outcomes, mutations, config reload."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.admin")

router = APIRouter()


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


async def _require_admin(request: Request) -> Any:
    """Authenticate, require admin, then check CSRF on mutations."""
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
    _check_csrf(request)
    return auth


@router.get("/v1/stronghold/admin/learnings")
async def list_learnings(request: Request) -> JSONResponse:
    """List all learnings (org-scoped for non-system users)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    store = container.learning_store
    all_learnings = await store.list_all(org_id=auth.org_id)
    return JSONResponse(
        content=[
            {
                "id": lr.id,
                "category": lr.category,
                "learning": lr.learning[:200],
                "tool_name": lr.tool_name,
                "hit_count": lr.hit_count,
                "status": lr.status,
                "org_id": lr.org_id,
            }
            for lr in all_learnings
        ]
    )


@router.post("/v1/stronghold/admin/learnings")
async def add_learning(request: Request) -> JSONResponse:
    """Manually add a learning."""
    auth = await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    learning_text = body.get("learning", "")

    # Warden scan: reject learning text containing threats / injection
    verdict = await container.warden.scan(learning_text, "user_input")
    if not verdict.clean:
        return JSONResponse(
            status_code=400,
            content={
                "error": f"Learning text blocked by security scan: {', '.join(verdict.flags)}"
            },
        )

    from stronghold.types.memory import Learning

    learning = Learning(
        category=body.get("category", "general"),
        trigger_keys=body.get("trigger_keys", []),
        learning=learning_text,
        tool_name=body.get("tool_name", ""),
        org_id=auth.org_id,
        team_id=auth.team_id,
    )
    lr_id = await container.learning_store.store(learning)
    return JSONResponse(content={"id": lr_id, "status": "stored"})


@router.get("/v1/stronghold/admin/outcomes")
async def get_outcomes(request: Request) -> JSONResponse:
    """Get task completion rate stats (org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    stats = await container.outcome_store.get_task_completion_rate(
        org_id=auth.org_id,
    )
    return JSONResponse(content=stats)


@router.get("/v1/stronghold/admin/audit")
async def get_audit_log(request: Request, limit: int = 100) -> JSONResponse:
    """Get recent audit log entries (org-scoped)."""
    limit = min(max(limit, 1), 500)
    auth = await _require_admin(request)
    container = request.app.state.container
    entries = await container.audit_log.get_entries(org_id=auth.org_id, limit=limit)
    return JSONResponse(
        content=[
            {
                "boundary": e.boundary,
                "user_id": e.user_id,
                "org_id": e.org_id,
                "tool_name": e.tool_name,
                "verdict": e.verdict,
                "detail": e.detail,
                "timestamp": str(e.timestamp),
            }
            for e in entries
            if auth.org_id == "__system__" or e.org_id == auth.org_id
        ]
    )


@router.get("/v1/stronghold/admin/learnings/approvals")
async def list_learning_approvals(request: Request) -> JSONResponse:
    """List pending learning approval requests (org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    if not hasattr(container, "learning_approval_gate") or not container.learning_approval_gate:
        return JSONResponse(content={"approvals": [], "gate_enabled": False})
    approvals = container.learning_approval_gate.get_all(org_id=auth.org_id)
    return JSONResponse(content={"approvals": approvals, "gate_enabled": True})


@router.post("/v1/stronghold/admin/learnings/approve")
async def approve_learning(request: Request) -> JSONResponse:
    """Approve a pending learning for promotion. Admin only.

    Body: {"learning_id": 42, "notes": "Looks correct"}
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    if not hasattr(container, "learning_approval_gate") or not container.learning_approval_gate:
        raise HTTPException(status_code=501, detail="Approval gate not enabled")

    body: dict[str, Any] = await request.json()
    learning_id = body.get("learning_id", 0)
    notes = body.get("notes", "")

    result = container.learning_approval_gate.approve(learning_id, auth.user_id, notes)
    if not result:
        raise HTTPException(status_code=404, detail="No pending approval for this learning")
    return JSONResponse(
        content={
            "learning_id": learning_id,
            "status": "approved",
            "reviewed_by": auth.user_id,
        }
    )


@router.post("/v1/stronghold/admin/learnings/reject")
async def reject_learning(request: Request) -> JSONResponse:
    """Reject a pending learning. Admin only.

    Body: {"learning_id": 42, "reason": "Incorrect correction"}
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    if not hasattr(container, "learning_approval_gate") or not container.learning_approval_gate:
        raise HTTPException(status_code=501, detail="Approval gate not enabled")

    body: dict[str, Any] = await request.json()
    learning_id = body.get("learning_id", 0)
    reason = body.get("reason", "")

    result = container.learning_approval_gate.reject(learning_id, auth.user_id, reason)
    if not result:
        raise HTTPException(status_code=404, detail="No pending approval for this learning")
    return JSONResponse(
        content={
            "learning_id": learning_id,
            "status": "rejected",
            "reason": reason,
        }
    )


# ── User Management (Approval Queue) ──


@router.get("/v1/stronghold/admin/users")
async def list_users(request: Request, status: str = "") -> JSONResponse:
    """List users, optionally filtered by status (pending/approved/rejected/disabled)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    is_system = auth.org_id == "__system__"

    async with pool.acquire() as conn:
        if status and is_system:
            rows = await conn.fetch(
                "SELECT * FROM users WHERE status = $1 ORDER BY created_at DESC", status
            )
        elif status:
            rows = await conn.fetch(
                "SELECT * FROM users WHERE status = $1 AND org_id = $2 ORDER BY created_at DESC",
                status,
                auth.org_id,
            )
        elif is_system:
            rows = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC")
        else:
            rows = await conn.fetch(
                "SELECT * FROM users WHERE org_id = $1 ORDER BY created_at DESC",
                auth.org_id,
            )

    return JSONResponse(
        content=[
            {
                "id": r["id"],
                "email": r["email"],
                "display_name": r["display_name"],
                "org_id": r["org_id"],
                "team_id": r["team_id"],
                "roles": r["roles"] if isinstance(r["roles"], list) else [],
                "status": r["status"],
                "approved_by": r["approved_by"],
                "approved_at": str(r["approved_at"]) if r["approved_at"] else None,
                "created_at": str(r["created_at"]),
            }
            for r in rows
        ]
    )


@router.post("/v1/stronghold/admin/users/{user_id}/approve")
async def approve_user(user_id: int, request: Request) -> JSONResponse:
    """Approve a pending user."""
    auth = await _require_admin(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with pool.acquire() as conn:
        if auth.org_id == "__system__":
            result = await conn.execute(
                """UPDATE users SET status = 'approved', approved_by = $1,
                   approved_at = NOW(), updated_at = NOW()
                   WHERE id = $2 AND status = 'pending'""",
                auth.user_id,
                user_id,
            )
        else:
            result = await conn.execute(
                """UPDATE users SET status = 'approved', approved_by = $1,
                   approved_at = NOW(), updated_at = NOW()
                   WHERE id = $2 AND status = 'pending' AND org_id = $3""",
                auth.user_id,
                user_id,
                auth.org_id,
            )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found or not pending")

    logger.info("User approved: id=%d by=%s", user_id, auth.user_id)
    return JSONResponse(content={"id": user_id, "status": "approved", "approved_by": auth.user_id})


@router.post("/v1/stronghold/admin/users/{user_id}/reject")
async def reject_user(user_id: int, request: Request) -> JSONResponse:
    """Reject a pending user."""
    auth = await _require_admin(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with pool.acquire() as conn:
        if auth.org_id == "__system__":
            result = await conn.execute(
                """UPDATE users SET status = 'rejected', updated_at = NOW()
                   WHERE id = $1 AND status = 'pending'""",
                user_id,
            )
        else:
            result = await conn.execute(
                """UPDATE users SET status = 'rejected', updated_at = NOW()
                   WHERE id = $1 AND status = 'pending' AND org_id = $2""",
                user_id,
                auth.org_id,
            )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found or not pending")

    logger.info("User rejected: id=%d by=%s", user_id, auth.user_id)
    return JSONResponse(content={"id": user_id, "status": "rejected"})


@router.post("/v1/stronghold/admin/users/approve-team")
async def approve_team(request: Request) -> JSONResponse:
    """Approve all pending users in an org/team."""
    auth = await _require_admin(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    body: dict[str, Any] = await request.json()
    team_id = body.get("team_id", "")

    # Non-system admins must use their own org_id; system admins may specify any
    org_id = body.get("org_id", "") if auth.org_id == "__system__" else auth.org_id

    if not org_id:
        raise HTTPException(status_code=400, detail="org_id is required")

    async with pool.acquire() as conn:
        if team_id:
            result = await conn.execute(
                """UPDATE users SET status = 'approved', approved_by = $1,
                   approved_at = NOW(), updated_at = NOW()
                   WHERE org_id = $2 AND team_id = $3 AND status = 'pending'""",
                auth.user_id,
                org_id,
                team_id,
            )
        else:
            result = await conn.execute(
                """UPDATE users SET status = 'approved', approved_by = $1,
                   approved_at = NOW(), updated_at = NOW()
                   WHERE org_id = $2 AND status = 'pending'""",
                auth.user_id,
                org_id,
            )

    count = int(result.split()[-1]) if result else 0
    scope = f"org={org_id}" + (f" team={team_id}" if team_id else " (all teams)")
    logger.info("Bulk approve: %s count=%d by=%s", scope, count, auth.user_id)
    return JSONResponse(content={"approved_count": count, "scope": scope})


@router.post("/v1/stronghold/admin/users/{user_id}/disable")
async def disable_user(user_id: int, request: Request) -> JSONResponse:
    """Disable an approved user."""
    auth = await _require_admin(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with pool.acquire() as conn:
        if auth.org_id == "__system__":
            result = await conn.execute(
                """UPDATE users SET status = 'disabled', updated_at = NOW()
                   WHERE id = $1 AND status != 'disabled'""",
                user_id,
            )
        else:
            result = await conn.execute(
                """UPDATE users SET status = 'disabled', updated_at = NOW()
                   WHERE id = $1 AND status != 'disabled' AND org_id = $2""",
                user_id,
                auth.org_id,
            )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found or already disabled")

    logger.info("User disabled: id=%d by=%s", user_id, auth.user_id)
    return JSONResponse(content={"id": user_id, "status": "disabled"})


@router.put("/v1/stronghold/admin/users/{user_id}/roles")
async def update_user_roles(user_id: int, request: Request) -> JSONResponse:
    """Update roles for a user. Requires admin role."""
    auth = await _require_admin(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    body: dict[str, Any] = await request.json()
    roles = body.get("roles")
    if not isinstance(roles, list) or not all(isinstance(r, str) for r in roles):
        raise HTTPException(status_code=400, detail="roles must be a list of strings")

    import json

    async with pool.acquire() as conn:
        result = await conn.execute(
            "UPDATE users SET roles = $1::jsonb, updated_at = NOW() WHERE id = $2",
            json.dumps(roles),
            user_id,
        )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("User roles updated: id=%d roles=%s by=%s", user_id, roles, auth.user_id)
    return JSONResponse(content={"id": user_id, "roles": roles})


# ── Agent Trust Tier Management ──

# Trust tier promotion rules:
#   Admin-created: T2 → T1 (requires AI review)
#   User-created:  T4 → T3 (AI review) → T2 (admin review)
#   Community:     Skull → T4 (user+AI review) → T3 (admin review, CAPPED)
_PROMOTION_MAP: dict[str, dict[str, str]] = {
    # provenance: {current_tier: next_tier_after_review}
    "builtin": {},  # Cannot promote — already T0
    "admin": {"t2": "t1"},  # AI review: T2 → T1
    "user": {"t4": "t3", "t3": "t2"},  # AI: T4→T3, Admin: T3→T2
    "community": {"skull": "t4", "t4": "t3"},  # User+AI: Skull→T4, Admin: T4→T3 (CAPPED)
}


@router.post("/v1/stronghold/admin/agents/{agent_name}/ai-review")
async def ai_review_agent(agent_name: str, request: Request) -> JSONResponse:
    """Run Warden AI security review on an agent's soul prompt and tools.

    Scans the agent definition for injection, role-hijacking, tool abuse,
    and PII exposure. Updates the agent's ai_reviewed flag and potentially
    promotes its trust tier.
    """
    auth = await _require_admin(request)
    container = request.app.state.container

    agent_data = await container.agent_store.get(agent_name)
    if not agent_data:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    # Get the soul prompt content
    soul_content = ""
    if hasattr(container.agent_store, "_souls"):
        soul_content = container.agent_store._souls.get(agent_name, "")  # noqa: SLF001
    if not soul_content:
        soul_content = agent_data.get("soul_prompt_preview", "")

    # Build review content: soul prompt + tools list + strategy
    tools_list = ", ".join(agent_data.get("tools", []))
    strategy = agent_data.get("reasoning_strategy", "direct")
    review_text = (
        f"Agent: {agent_name}\n"
        f"Strategy: {strategy}\n"
        f"Tools: {tools_list}\n"
        f"Soul Prompt:\n{soul_content}"
    )

    # Run Warden scan
    verdict = await container.warden.scan(review_text, "user_input")

    # Read trust metadata from DB
    pool = getattr(container, "db_pool", None)
    old_tier = agent_data.get("trust_tier", "t4")
    provenance = agent_data.get("provenance", "user")
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT trust_tier, provenance, user_reviewed FROM agents WHERE name = $1",
                agent_name,
            )
            if row:
                old_tier = row["trust_tier"]
                provenance = row["provenance"]

    # Compute promotion
    new_tier = old_tier
    promo_map = _PROMOTION_MAP.get(provenance, {})
    if (
        verdict.clean
        and old_tier in promo_map
        and (
            provenance == "admin"
            or (provenance == "user" and old_tier == "t4")
            or (provenance == "community" and agent_data.get("user_reviewed"))
        )
    ):
        new_tier = promo_map[old_tier]

    # Persist to DB (source of truth for trust metadata)
    pool = getattr(container, "db_pool", None)
    if pool:
        flags_str = ",".join(verdict.flags) if verdict.flags else ""
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE agents SET ai_reviewed = TRUE, ai_review_clean = $1, ai_review_flags = $2,
                   trust_tier = $3, updated_at = NOW() WHERE name = $4""",
                verdict.clean,
                flags_str,
                new_tier,
                agent_name,
            )
            await conn.execute(
                """INSERT INTO agent_trust_audit
                   (agent_name, old_tier, new_tier, action,
                    performed_by, details)
                   VALUES ($1, $2, $3, 'ai_review', $4, $5)""",
                agent_name,
                old_tier,
                new_tier,
                auth.user_id,
                f"clean={verdict.clean} flags={flags_str}"
                if flags_str
                else f"clean={verdict.clean}",
            )

    # Also update in-memory store if possible
    with contextlib.suppress(ValueError, TypeError):
        await container.agent_store.update(agent_name, {"trust_tier": new_tier})

    logger.info(
        "AI review: agent=%s clean=%s flags=%s tier=%s→%s by=%s",
        agent_name,
        verdict.clean,
        verdict.flags,
        old_tier,
        new_tier,
        auth.user_id,
    )

    return JSONResponse(
        content={
            "agent": agent_name,
            "ai_review": {
                "clean": verdict.clean,
                "flags": list(verdict.flags),
                "confidence": verdict.confidence,
            },
            "trust_tier": {"old": old_tier, "new": new_tier},
            "promoted": new_tier != old_tier,
        }
    )


@router.post("/v1/stronghold/admin/agents/{agent_name}/admin-review")
async def admin_review_agent(agent_name: str, request: Request) -> JSONResponse:
    """Admin approves an agent for tier promotion.

    Requires AI review to have passed first (for user/community agents).
    Promotes: user T3→T2, community T4→T3 (capped).
    """
    auth = await _require_admin(request)
    container = request.app.state.container

    agent_data = await container.agent_store.get(agent_name)
    if not agent_data:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

    # Read trust metadata from DB
    pool = getattr(container, "db_pool", None)
    old_tier = agent_data.get("trust_tier", "t4")
    provenance = "user"
    ai_reviewed = False
    ai_clean = False
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT trust_tier, provenance, ai_reviewed,"
                " ai_review_clean FROM agents WHERE name = $1",
                agent_name,
            )
            if row:
                old_tier = row["trust_tier"]
                provenance = row["provenance"]
                ai_reviewed = row["ai_reviewed"]
                ai_clean = row["ai_review_clean"]

    # Gate: AI review must pass before admin review promotes
    if not ai_reviewed:
        raise HTTPException(
            status_code=400, detail="AI security review must be completed first. Run ai-review."
        )
    if not ai_clean:
        raise HTTPException(
            status_code=400,
            detail="AI review flagged issues. Resolve flags before admin approval.",
        )

    # Promote based on provenance rules
    new_tier = old_tier
    promo_map = _PROMOTION_MAP.get(provenance, {})
    if old_tier in promo_map and provenance in ("user", "community"):
        new_tier = promo_map[old_tier]

    if new_tier == old_tier:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Agent at {old_tier} with provenance '{provenance}'"
                " cannot be promoted further by admin review."
            ),
        )

    # Persist to DB
    pool = getattr(container, "db_pool", None)
    if pool:
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE agents SET admin_reviewed = TRUE, admin_reviewed_by = $1,
                   trust_tier = $2, updated_at = NOW() WHERE name = $3""",
                auth.user_id,
                new_tier,
                agent_name,
            )
            await conn.execute(
                """INSERT INTO agent_trust_audit
                   (agent_name, old_tier, new_tier, action,
                    performed_by, details)
                   VALUES ($1, $2, $3, 'admin_review', $4, $5)""",
                agent_name,
                old_tier,
                new_tier,
                auth.user_id,
                f"provenance={provenance}",
            )

    with contextlib.suppress(ValueError, TypeError):
        await container.agent_store.update(agent_name, {"trust_tier": new_tier})

    logger.info(
        "Admin review: agent=%s tier=%s→%s by=%s provenance=%s",
        agent_name,
        old_tier,
        new_tier,
        auth.user_id,
        provenance,
    )

    return JSONResponse(
        content={
            "agent": agent_name,
            "trust_tier": {"old": old_tier, "new": new_tier},
            "promoted": True,
            "reviewed_by": auth.user_id,
            "provenance": provenance,
        }
    )


@router.get("/v1/stronghold/admin/agents/{agent_name}/trust")
async def get_agent_trust(agent_name: str, request: Request) -> JSONResponse:
    """Get trust tier details and review history for an agent."""
    await _require_admin(request)
    container = request.app.state.container

    # Read trust metadata from DB (source of truth)
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    async with pool.acquire() as conn:
        agent_row = await conn.fetchrow(
            """SELECT name, trust_tier, provenance, ai_reviewed, ai_review_clean, ai_review_flags,
                      admin_reviewed, admin_reviewed_by, user_reviewed, active
               FROM agents WHERE name = $1""",
            agent_name,
        )
        if not agent_row:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")

        rows = await conn.fetch(
            "SELECT * FROM agent_trust_audit"
            " WHERE agent_name = $1"
            " ORDER BY created_at DESC LIMIT 20",
            agent_name,
        )

    audit = [
        {
            "action": r["action"],
            "old": r["old_tier"],
            "new": r["new_tier"],
            "by": r["performed_by"],
            "details": r["details"],
            "at": str(r["created_at"]),
        }
        for r in rows
    ]

    return JSONResponse(
        content={
            "agent": agent_name,
            "trust_tier": agent_row["trust_tier"],
            "provenance": agent_row["provenance"],
            "active": agent_row["active"],
            "reviews": {
                "ai_reviewed": agent_row["ai_reviewed"],
                "ai_review_clean": agent_row["ai_review_clean"],
                "ai_review_flags": agent_row["ai_review_flags"],
                "admin_reviewed": agent_row["admin_reviewed"],
                "admin_reviewed_by": agent_row["admin_reviewed_by"],
                "user_reviewed": agent_row["user_reviewed"],
            },
            "audit_trail": audit,
        }
    )


def days_in_cycle(billing_cycle: str) -> int:
    """Estimate days elapsed in the current billing cycle."""
    from datetime import UTC, datetime  # noqa: PLC0415

    now = datetime.now(UTC)
    if billing_cycle == "daily":
        return 1
    # Monthly: days elapsed so far this month
    return max(now.day, 1)


@router.get("/v1/stronghold/admin/quota")
async def get_quota(request: Request) -> JSONResponse:
    """Get enriched quota usage: raw tokens + provider budgets + percentages + burn rate."""
    auth = await _require_admin(request)
    container = request.app.state.container

    from stronghold.quota.billing import cycle_key as _cycle_key  # noqa: PLC0415
    from stronghold.types.model import ProviderConfig  # noqa: PLC0415

    # Get raw usage records
    usage_records = await container.quota_tracker.get_all_usage()

    # Build provider configs from config (filter unknown fields for forward compat)
    _prov_fields = {f.name for f in ProviderConfig.__dataclass_fields__.values()}
    providers_cfg: dict[str, ProviderConfig] = {}
    for name, raw in container.config.providers.items():
        if isinstance(raw, dict):
            providers_cfg[name] = ProviderConfig(
                **{k: v for k, v in raw.items() if k in _prov_fields}
            )
        elif isinstance(raw, ProviderConfig):
            providers_cfg[name] = raw

    # Build usage lookup: (provider, cycle_key) -> record
    usage_by_key: dict[tuple[str, str], dict[str, object]] = {}
    for rec in usage_records:
        key = (str(rec["provider"]), str(rec["cycle_key"]))
        usage_by_key[key] = rec

    # Enrich each provider with budget + current usage + percentage
    enriched: list[dict[str, object]] = []
    total_tokens_all = 0
    total_requests_all = 0
    total_budget_all = 0
    providers_exhausted = 0

    from stronghold.quota.billing import daily_budget as _daily_budget  # noqa: PLC0415

    total_cost_all = 0.0

    for prov_name, prov_cfg in providers_cfg.items():
        ck = _cycle_key(prov_cfg.billing_cycle)
        rec = usage_by_key.get((prov_name, ck))
        total_tokens = int(str(rec["total_tokens"])) if rec else 0
        input_tokens = int(str(rec["input_tokens"])) if rec else 0
        output_tokens = int(str(rec["output_tokens"])) if rec else 0
        request_count = int(str(rec["request_count"])) if rec else 0
        usage_pct = (total_tokens / prov_cfg.free_tokens) if prov_cfg.free_tokens > 0 else 0.0
        has_paygo = (
            prov_cfg.overage_cost_per_1k_input > 0 or prov_cfg.overage_cost_per_1k_output > 0
        )

        if usage_pct >= 1.0 and not has_paygo:
            providers_exhausted += 1

        total_tokens_all += total_tokens
        total_requests_all += request_count
        total_budget_all += prov_cfg.free_tokens

        # Burn rate: tokens per day based on cycle progress
        _daily_budget(prov_cfg.free_tokens, prov_cfg.billing_cycle)
        # Estimate days elapsed in this cycle from request count pattern
        # Simple heuristic: use total_tokens / daily_budget to get utilization days
        burn_rate = round(total_tokens / max(days_in_cycle(prov_cfg.billing_cycle), 1), 1)
        remaining = max(prov_cfg.free_tokens - total_tokens, 0)
        days_left = round(remaining / burn_rate, 1) if burn_rate > 0 else None

        # Cost estimate for overage
        overage_tokens = max(total_tokens - prov_cfg.free_tokens, 0)
        cost = 0.0
        if overage_tokens > 0 and has_paygo:
            # Split proportionally between input and output
            ratio = input_tokens / max(total_tokens, 1)
            cost = (overage_tokens * ratio * prov_cfg.overage_cost_per_1k_input / 1000) + (
                overage_tokens * (1 - ratio) * prov_cfg.overage_cost_per_1k_output / 1000
            )
        total_cost_all += cost

        enriched.append(
            {
                "provider": prov_name,
                "status": prov_cfg.status,
                "billing_cycle": prov_cfg.billing_cycle,
                "cycle_key": ck,
                "free_tokens": prov_cfg.free_tokens,
                "total_tokens": total_tokens,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "request_count": request_count,
                "usage_pct": round(usage_pct, 4),
                "has_paygo": has_paygo,
                "daily_burn_rate": burn_rate,
                "days_until_exhaustion": days_left,
                "overage_cost": round(cost, 4),
            }
        )

    # Sort: active first, then by usage_pct descending (most-used first)
    enriched.sort(
        key=lambda x: (x["status"] != "active", -(x["usage_pct"] or 0)),  # type: ignore[operator]
    )

    overall_pct = (total_tokens_all / total_budget_all) if total_budget_all > 0 else 0.0

    # Fetch coin wallets for the caller's org
    wallets: list[dict[str, object]] = []
    if hasattr(container, "coin_ledger") and container.coin_ledger:
        try:
            wallets = await container.coin_ledger.list_wallets(org_id=auth.org_id)
        except Exception:
            logger.debug("coin_ledger.list_wallets failed (non-critical)")

    return JSONResponse(
        content={
            "providers": enriched,
            "wallets": wallets,
            "summary": {
                "total_providers": len(providers_cfg),
                "active_providers": sum(1 for p in providers_cfg.values() if p.status == "active"),
                "exhausted_providers": providers_exhausted,
                "total_tokens": total_tokens_all,
                "total_requests": total_requests_all,
                "total_budget": total_budget_all,
                "overall_usage_pct": round(overall_pct, 4),
                "total_overage_cost": round(total_cost_all, 4),
            },
        }
    )


@router.get("/v1/stronghold/admin/quota/usage")
async def get_quota_usage(
    request: Request,
    group_by: str = "user_id",
    days: int = 7,
) -> JSONResponse:
    """Get aggregated token usage breakdown by dimension.

    Query params:
        group_by: user_id | team_id | org_id | model_used | agent_id | provider
        days: lookback window (default 7)
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    days = min(max(days, 1), 90)

    allowed = {"user_id", "team_id", "org_id", "model_used", "agent_id", "provider"}
    if group_by not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"group_by must be one of: {', '.join(sorted(allowed))}",
        )

    breakdown = await container.outcome_store.get_usage_breakdown(
        group_by=group_by,
        days=days,
        org_id=auth.org_id,
    )

    return JSONResponse(
        content={
            "group_by": group_by,
            "days": days,
            "data": breakdown,
        }
    )


@router.get("/v1/stronghold/admin/coins/denominations")
async def get_coin_denominations(request: Request) -> JSONResponse:
    """Return the coin denomination map used by quota wallets."""
    await _require_admin(request)
    container = request.app.state.container
    return JSONResponse(content=container.coin_ledger.denominations())


@router.get("/v1/stronghold/admin/coins/pricing")
async def get_coin_pricing(request: Request) -> JSONResponse:
    """Return per-model coin pricing for the pricing table UI."""
    await _require_admin(request)
    container = request.app.state.container

    from stronghold.quota.coins import (  # noqa: PLC0415
        DENOMINATION_FACTORS,
        MICROCHIPS_PER_COPPER,
        format_microchips,
    )

    models_cfg = container.config.models
    pricing: list[dict[str, object]] = []
    for model_id, raw in models_cfg.items():
        if not isinstance(raw, dict):
            continue
        quote = container.coin_ledger.quote(model_id, raw.get("provider", ""), 1000, 1000)
        pricing.append(
            {
                "model": model_id,
                "provider": quote.provider,
                "tier": raw.get("tier", ""),
                "quality": raw.get("quality", 0),
                "base": format_microchips(quote.base_microchips),
                "per_1k_input": format_microchips(quote.input_rate_microchips),
                "per_1k_output": format_microchips(quote.output_rate_microchips),
                "example_1k_cost": format_microchips(quote.charged_microchips),
                "pricing_version": quote.pricing_version,
            }
        )
    pricing.sort(key=lambda x: float(str(x.get("quality", 0))), reverse=True)

    return JSONResponse(
        content={
            "denominations": {
                "microchips_per_copper": MICROCHIPS_PER_COPPER,
                "factors": DENOMINATION_FACTORS,
                "exchange_rates": {
                    name: {"microchips": factor * MICROCHIPS_PER_COPPER, "in_copper": factor}
                    for name, factor in DENOMINATION_FACTORS.items()
                },
            },
            "models": pricing,
        }
    )


@router.get("/v1/stronghold/admin/coins/wallets")
async def list_coin_wallets(
    request: Request,
    owner_type: str = "",
    owner_id: str = "",
) -> JSONResponse:
    """List configured coin wallets with current-cycle usage and remaining balance."""
    auth = await _require_admin(request)
    container = request.app.state.container
    scope_org = "" if auth.org_id == "__system__" else auth.org_id
    wallets = await container.coin_ledger.list_wallets(
        org_id=scope_org,
        owner_type=owner_type,
        owner_id=owner_id,
    )
    return JSONResponse(content={"wallets": wallets})


@router.put("/v1/stronghold/admin/coins/wallets")
async def upsert_coin_wallet(request: Request) -> JSONResponse:
    """Create or update a user/team/org coin wallet."""
    auth = await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    from stronghold.quota.coins import coins_to_microchips  # noqa: PLC0415

    owner_type = str(body.get("owner_type", "")).strip().lower()
    owner_id = str(body.get("owner_id", "")).strip()
    if not owner_type or not owner_id:
        raise HTTPException(status_code=400, detail="owner_type and owner_id are required")

    scope_org = str(body.get("org_id", "")).strip()
    if auth.org_id != "__system__":
        scope_org = auth.org_id
    if owner_type == "org" and not scope_org:
        raise HTTPException(status_code=400, detail="org wallets require org_id")

    scope_team = str(body.get("team_id", "")).strip()
    budget_microchips = coins_to_microchips(
        body.get("budget_amount", 0),
        str(body.get("budget_denomination", "copper")),
    )
    hard_limit_microchips = coins_to_microchips(
        body.get("hard_limit_amount", body.get("budget_amount", 0)),
        str(body.get("hard_limit_denomination", body.get("budget_denomination", "copper"))),
    )

    try:
        wallet = await container.coin_ledger.upsert_wallet(
            owner_type=owner_type,
            owner_id=owner_id,
            org_id=scope_org,
            team_id=scope_team,
            label=str(body.get("label", "")).strip(),
            billing_cycle=str(body.get("billing_cycle", "monthly")),
            budget_microchips=budget_microchips,
            hard_limit_microchips=hard_limit_microchips,
            soft_limit_ratio=float(body.get("soft_limit_ratio", 0.8)),
            overage_allowed=bool(body.get("overage_allowed", False)),
            active=bool(body.get("active", True)),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return JSONResponse(content=wallet)


# ── Daily Refill + Conversion ──

# Default daily copper allowance (configurable per-wallet in future)
_DEFAULT_DAILY_COPPER = 50  # 50 copper = 50,000 microchips


@router.get("/v1/stronghold/admin/coins/refill")
async def get_refill_status(request: Request) -> JSONResponse:
    """Show today's daily copper allowance: granted, spent, remaining.

    The daily refill gives each user wallet a copper allowance per day.
    Unspent coppers expire at cycle reset. Convert to silver to save them.
    """
    from stronghold.quota.billing import cycle_key as _ck  # noqa: PLC0415
    from stronghold.quota.coins import (  # noqa: PLC0415
        MICROCHIPS_PER_COPPER,
        format_microchips,
    )

    auth = await _require_admin(request)
    container = request.app.state.container

    daily_copper = _DEFAULT_DAILY_COPPER
    daily_microchips = daily_copper * MICROCHIPS_PER_COPPER
    today_key = _ck("daily")

    # Sum today's debit entries for this user, scoped to their org
    spent_today = 0
    if hasattr(container, "db_pool") and container.db_pool:
        async with container.db_pool.acquire() as conn:
            row = await conn.fetchval(
                """SELECT COALESCE(-SUM(delta_microchips), 0)
                   FROM coin_ledger_entries
                   WHERE user_id = $1 AND org_id = $2
                     AND cycle_key = $3 AND delta_microchips < 0""",
                auth.user_id,
                auth.org_id,
                today_key,
            )
            spent_today = int(row or 0)

    remaining = max(daily_microchips - spent_today, 0)

    # Read super-admin-adjustable banking rate
    banking_rate = 40  # default
    if hasattr(container, "coin_ledger"):
        banking_rate = await container.coin_ledger.get_banking_rate()

    convertible_copper = remaining // MICROCHIPS_PER_COPPER
    banked_microchips = remaining * banking_rate // 100

    return JSONResponse(
        content={
            "daily_allowance": format_microchips(daily_microchips),
            "spent_today": format_microchips(spent_today),
            "remaining_today": format_microchips(remaining),
            "cycle_key": today_key,
            "banking_rate_pct": banking_rate,
            "convertible_copper": convertible_copper,
            "max_banked_value": format_microchips(banked_microchips),
        }
    )


@router.post("/v1/stronghold/admin/coins/convert")
async def convert_coins(request: Request) -> JSONResponse:
    """Currency Exchange: convert free daily copper into persistent silver.

    Body: {"copper_amount": 10}
    Copper is the free daily faucet — expires at end of day.  Users must
    actively exchange copper to keep it.  The exchange rate (default 40%)
    is super-admin adjustable.  Purchased coins bypass copper entirely and
    go straight into silver or higher.

    Silver coins can only be spent on silver-tier models and below.
    Higher-tier models require gold/platinum/diamond (purchased).
    """
    import uuid  # noqa: PLC0415

    from stronghold.quota.billing import cycle_key as _ck  # noqa: PLC0415
    from stronghold.quota.coins import (  # noqa: PLC0415
        MICROCHIPS_PER_COPPER,
        format_microchips,
    )

    auth = await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    # SEC-014: guard int() against non-numeric input
    try:
        copper_amount = int(body.get("copper_amount", 0))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"copper_amount must be an integer: {e}") from e
    if copper_amount < 10:
        raise HTTPException(status_code=400, detail="Minimum conversion: 10 copper")

    copper_microchips = copper_amount * MICROCHIPS_PER_COPPER

    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Conversion requires PostgreSQL")

    # Read the current banking rate (super-admin adjustable)
    banking_rate = await container.coin_ledger.get_banking_rate()
    silver_microchips = copper_microchips * banking_rate // 100

    # Find user's daily wallet (copper source) and silver exchange wallet
    wallets = await container.coin_ledger.list_wallets(
        org_id=auth.org_id,
        owner_type="user",
        owner_id=auth.user_id,
    )
    daily_wallet = next((w for w in wallets if w["denomination"] == "copper"), None)
    if not daily_wallet:
        raise HTTPException(status_code=404, detail="No daily wallet found — nothing to convert")

    if daily_wallet["remaining_microchips"] < copper_microchips:
        remaining_copper = daily_wallet["remaining_microchips"] // MICROCHIPS_PER_COPPER
        raise HTTPException(
            status_code=400,
            detail=f"Insufficient balance: need {copper_amount} copper, "
            f"have {remaining_copper} copper remaining today",
        )

    # Find or auto-create the silver exchange wallet (monthly, denomination=silver)
    silver_wallet = next((w for w in wallets if w["denomination"] == "silver"), None)
    if not silver_wallet:
        silver_wallet = await container.coin_ledger.upsert_wallet(
            owner_type="user",
            owner_id=auth.user_id,
            org_id=auth.org_id,
            team_id=auth.team_id,
            label="Silver Exchange",
            billing_cycle="monthly",
            denomination="silver",
            budget_microchips=0,
            hard_limit_microchips=0,
            soft_limit_ratio=1.0,
            overage_allowed=False,
            active=True,
        )

    # Unique request_id per conversion for idempotency and audit trail
    convert_id = f"convert-{uuid.uuid4().hex[:12]}"

    async with pool.acquire() as conn, conn.transaction():
        # Debit full copper from daily wallet (they lose the full amount)
        await conn.execute(
            """INSERT INTO coin_ledger_entries
                   (wallet_id, cycle_key, entry_kind, delta_microchips,
                    request_id, org_id, team_id, user_id, pricing_version)
                   VALUES ($1, $2, 'adjustment', $3, $4, $5, $6, $7, 'conversion-v1')""",
            daily_wallet["id"],
            _ck("daily"),
            -copper_microchips,
            convert_id,
            auth.org_id,
            auth.team_id,
            auth.user_id,
        )
        # Credit discounted silver to exchange wallet (exchange rate applied)
        await conn.execute(
            """INSERT INTO coin_ledger_entries
                   (wallet_id, cycle_key, entry_kind, delta_microchips,
                    request_id, org_id, team_id, user_id, pricing_version)
                   VALUES ($1, $2, 'credit', $3, $4, $5, $6, $7, 'conversion-v1')""",
            silver_wallet["id"],
            _ck("monthly"),
            silver_microchips,
            convert_id,
            auth.org_id,
            auth.team_id,
            auth.user_id,
        )

    logger.info(
        "Coin exchange: user=%s copper=%d credited=%d rate=%d%% id=%s",
        auth.user_id,
        copper_amount,
        silver_microchips,
        banking_rate,
        convert_id,
    )

    return JSONResponse(
        content={
            "converted": {
                "copper_spent": format_microchips(copper_microchips),
                "silver_credited": format_microchips(silver_microchips),
            },
            "copper_amount": copper_amount,
            "banking_rate_pct": banking_rate,
            "convert_id": convert_id,
        }
    )


@router.get("/v1/stronghold/admin/coins/settings")
async def get_coin_settings(request: Request) -> JSONResponse:
    """Get coin system settings (banking rate, etc.)."""
    await _require_admin(request)
    container = request.app.state.container
    banking_rate = 40
    if hasattr(container, "coin_ledger"):
        banking_rate = await container.coin_ledger.get_banking_rate()
    return JSONResponse(
        content={
            "banking_rate_pct": banking_rate,
            "daily_copper_allowance": _DEFAULT_DAILY_COPPER,
        }
    )


@router.put("/v1/stronghold/admin/coins/settings")
async def update_coin_settings(request: Request) -> JSONResponse:
    """Update coin system settings. Requires admin role.

    Body: {"banking_rate_pct": 40}
    TODO: Gate on superadmin role once trust tiers are wired.
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()

    if "banking_rate_pct" in body:
        rate = int(body["banking_rate_pct"])
        if not 1 <= rate <= 100:
            raise HTTPException(status_code=400, detail="banking_rate_pct must be 1-100")
        await container.coin_ledger.set_banking_rate(rate)
        logger.info(
            "Coin settings updated: banking_rate_pct=%d by user=%s",
            rate,
            auth.user_id,
        )

    # Return current settings after update
    banking_rate = await container.coin_ledger.get_banking_rate()
    return JSONResponse(
        content={
            "banking_rate_pct": banking_rate,
            "daily_copper_allowance": _DEFAULT_DAILY_COPPER,
        }
    )


@router.get("/v1/stronghold/admin/quota/timeseries")
async def get_quota_timeseries(
    request: Request,
    group_by: str = "",
    days: int = 7,
) -> JSONResponse:
    """Get daily token usage timeseries, optionally grouped.

    Query params:
        group_by: (optional) user_id | team_id | model_used | provider
        days: lookback window (default 7, max 90)
    """
    auth = await _require_admin(request)
    container = request.app.state.container
    days = min(max(days, 1), 90)

    allowed = {"user_id", "team_id", "org_id", "model_used", "agent_id", "provider", ""}
    if group_by not in allowed:
        raise HTTPException(status_code=400, detail="Invalid group_by dimension")

    series = await container.outcome_store.get_daily_timeseries(
        group_by=group_by,
        days=days,
        org_id=auth.org_id,
    )

    return JSONResponse(
        content={
            "group_by": group_by or None,
            "days": days,
            "series": series,
        }
    )


@router.post("/v1/stronghold/admin/quota/analyze")
async def analyze_quota(request: Request) -> JSONResponse:
    """AI analyst: answer natural language questions about usage data.

    Body: {"question": "Which user consumed the most tokens last week?"}
    Returns: {"answer": "...", "chart": <Chart.js config or null>}
    """
    import json as _json  # noqa: PLC0415

    auth = await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    if len(question) > 1000:
        raise HTTPException(status_code=400, detail="question must be under 1000 characters")

    # Warden scan the question
    verdict = await container.warden.scan(question, "user_input")
    if not verdict.clean:
        return JSONResponse(
            status_code=400,
            content={"error": f"Question blocked: {', '.join(verdict.flags)}"},
        )

    # Gather context: all breakdowns (by user, team, model, provider)
    data_sections: list[str] = []
    for dim in ("user_id", "team_id", "model_used", "provider"):
        rows = await container.outcome_store.get_usage_breakdown(
            group_by=dim,
            days=30,
            org_id=auth.org_id,
        )
        if rows:
            header = f"=== Usage by {dim} (last 30 days) ==="
            lines = [header]
            for r in rows[:20]:
                success_rate = (
                    round(r["success_count"] / r["request_count"] * 100, 1)
                    if r["request_count"] > 0
                    else 0
                )
                lines.append(
                    f"  {r['group']}: {r['total_tokens']} tokens "
                    f"({r['input_tokens']} in / {r['output_tokens']} out), "
                    f"{r['request_count']} requests, "
                    f"{success_rate}% success, "
                    f"avg {r['avg_response_ms']}ms"
                )
            data_sections.append("\n".join(lines))

    # Daily timeseries (last 14 days)
    ts = await container.outcome_store.get_daily_timeseries(
        group_by="",
        days=14,
        org_id=auth.org_id,
    )
    if ts:
        ts_lines = ["=== Daily Token Usage (last 14 days) ==="]
        for day in ts:
            ts_lines.append(
                f"  {day['date']}: {day['total_tokens']} tokens, {day['request_count']} requests"
            )
        data_sections.append("\n".join(ts_lines))

    # Provider quota context with burn rate
    from stronghold.quota.billing import cycle_key as _ck  # noqa: PLC0415
    from stronghold.types.model import ProviderConfig  # noqa: PLC0415

    prov_lines = ["=== Provider Budgets & Burn Rate ==="]
    usage_records = await container.quota_tracker.get_all_usage()
    _pf = {f.name for f in ProviderConfig.__dataclass_fields__.values()}
    for name, raw in container.config.providers.items():
        cfg = (
            ProviderConfig(**{k: v for k, v in raw.items() if k in _pf})
            if isinstance(raw, dict)
            else raw
        )
        ck = _ck(cfg.billing_cycle)
        used = 0
        for rec in usage_records:
            if str(rec["provider"]) == name and str(rec["cycle_key"]) == ck:
                used = int(rec["total_tokens"])
                break
        pct = round(used / cfg.free_tokens * 100, 1) if cfg.free_tokens > 0 else 0
        elapsed = days_in_cycle(cfg.billing_cycle)
        burn = round(used / max(elapsed, 1))
        remaining = max(cfg.free_tokens - used, 0)
        days_left = round(remaining / burn) if burn > 0 else None
        days_str = f", ~{days_left}d remaining" if days_left is not None else ""
        prov_lines.append(
            f"  {name}: {used}/{cfg.free_tokens} tokens ({pct}%), "
            f"{cfg.billing_cycle}, burn={burn}/day{days_str}, status={cfg.status}"
        )
    data_sections.append("\n".join(prov_lines))

    data_context = "\n\n".join(data_sections)

    system_prompt = (
        "You are the Stronghold Ledger Analyst. You analyze LLM usage data for "
        "an enterprise agent governance platform.\n\n"
        "RULES:\n"
        "- Answer concisely. Use **bold** for key numbers and *italic* for emphasis.\n"
        "- Use bullet points for lists. Keep answers under 300 words.\n"
        "- If a chart helps, include Chart.js v4 config between ```chartjs and ``` markers.\n"
        "- Chart config must be valid JSON: {type, data:{labels,datasets}, options}.\n"
        "- Chart types: 'bar' for comparisons, 'line' for trends, 'doughnut' for proportions.\n"
        "- Colors: ['#e2a529','#2d6a4f','#4ade80','#ff6b6b','#6b6b7b','#c9a227','#8b2500',"
        "'#f4c430','#a78bfa','#60a5fa'].\n"
        "- For line charts, set borderColor on datasets and fill:false.\n"
        "- Set options.plugins.legend.labels.color='#8b8b9b' and options.scales axes color.\n"
        "- Do NOT fabricate data. Only use what is provided.\n"
        "- When discussing burn rates, note remaining days to exhaustion.\n"
        "- At the end, suggest 1-2 follow-up questions the admin might want to ask.\n\n"
        f"DATA:\n{data_context}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": question},
    ]

    try:
        llm_response = await container.llm.complete(messages, "")
        choices = llm_response.get("choices", [])
        answer_text = choices[0].get("message", {}).get("content", "") if choices else ""
    except Exception:
        logger.exception("AI analyst LLM call failed")
        return JSONResponse(
            status_code=502,
            content={"error": "AI analyst temporarily unavailable"},
        )

    # Extract chart config if present
    chart = None
    if "```chartjs" in answer_text:
        parts = answer_text.split("```chartjs")
        if len(parts) > 1:
            chart_str = parts[1].split("```")[0].strip()
            try:
                chart = _json.loads(chart_str)
                # Remove the chart block from the text answer
                answer_text = parts[0].strip()
                if len(parts) > 1:
                    remainder = "```".join(parts[1].split("```")[1:]).strip()
                    if remainder:
                        answer_text += "\n" + remainder
            except _json.JSONDecodeError:
                pass  # Leave chart as None if parsing fails

    return JSONResponse(content={"answer": answer_text, "chart": chart})


@router.post("/v1/stronghold/admin/reload")
async def reload_config(request: Request) -> JSONResponse:
    """Hot-reload configuration."""
    await _require_admin(request)
    return JSONResponse(content={"status": "reload_not_yet_implemented"}, status_code=501)


# ── Strike Management ──


@router.get("/v1/stronghold/admin/strikes")
async def list_strikes(request: Request) -> JSONResponse:
    """List all users with strikes (org-scoped)."""
    auth = await _require_admin(request)
    container = request.app.state.container
    records = await container.strike_tracker.get_all_for_org(auth.org_id)
    return JSONResponse(content=[r.to_dict() for r in records if r.strike_count > 0])


@router.get("/v1/stronghold/admin/strikes/{user_id}")
async def get_user_strikes(user_id: str, request: Request) -> JSONResponse:
    """Get strike record for a specific user."""
    auth = await _require_admin(request)
    container = request.app.state.container
    record = await container.strike_tracker.get(user_id)
    if record is None:
        return JSONResponse(content={"strike_count": 0, "scrutiny_level": "normal"})
    # Verify org ownership: non-system admins can only view their own org's users
    if auth.org_id != "__system__" and getattr(record, "org_id", None) != auth.org_id:
        raise HTTPException(status_code=404, detail="No strike record for this user")
    return JSONResponse(content=record.to_dict())


@router.post("/v1/stronghold/admin/strikes/{user_id}/remove")
async def remove_strikes(user_id: str, request: Request) -> JSONResponse:
    """Remove strikes from a user. Any admin can do this.

    Body: {"count": N} to remove N strikes, or omit to clear all.
    """
    await _require_admin(request)
    container = request.app.state.container
    body: dict[str, Any] = await request.json()
    count = body.get("count")  # None = clear all

    record = await container.strike_tracker.remove_strikes(user_id, count)
    if record is None:
        raise HTTPException(status_code=404, detail="No strike record for this user")

    logger.info("Admin removed strikes: user=%s new_count=%d", user_id, record.strike_count)
    return JSONResponse(content=record.to_dict())


@router.post("/v1/stronghold/admin/strikes/{user_id}/unlock")
async def unlock_user(user_id: str, request: Request) -> JSONResponse:
    """Unlock a locked account. Requires team_admin or admin role."""
    auth = await _require_admin_or_role(request, "team_admin")
    container = request.app.state.container

    record = await container.strike_tracker.unlock(user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No strike record for this user")

    logger.info("Admin unlocked user: user=%s by=%s", user_id, auth.user_id)
    return JSONResponse(content=record.to_dict())


@router.post("/v1/stronghold/admin/strikes/{user_id}/enable")
async def enable_user(user_id: str, request: Request) -> JSONResponse:
    """Re-enable a disabled account. Requires org_admin or admin role."""
    auth = await _require_admin_or_role(request, "org_admin")
    container = request.app.state.container

    record = await container.strike_tracker.enable(user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No strike record for this user")

    logger.info("Admin re-enabled user: user=%s by=%s", user_id, auth.user_id)
    return JSONResponse(content=record.to_dict())


async def _require_admin_or_role(request: Request, role: str) -> Any:
    """Authenticate, require role, then check CSRF on mutations."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    if not auth.has_role("admin") and not auth.has_role(role):
        raise HTTPException(
            status_code=403,
            detail=f"Requires admin or {role} role",
        )
    _check_csrf(request)
    return auth


# ── Appeals ──


@router.post("/v1/stronghold/appeals")
async def submit_appeal(request: Request) -> JSONResponse:
    """Submit an appeal for a security violation.

    Any authenticated user can submit an appeal for their own strikes.
    Body: {"text": "explanation of why this was a false positive"}
    """
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        auth = await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    body: dict[str, Any] = await request.json()
    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Appeal text is required")
    if len(text) > 2000:
        raise HTTPException(status_code=400, detail="Appeal text must be under 2000 characters")

    recorded = await container.strike_tracker.submit_appeal(auth.user_id, text)
    if not recorded:
        return JSONResponse(
            content={"status": "no_strikes", "message": "No active strikes to appeal"},
            status_code=404,
        )

    logger.info("Appeal submitted: user=%s length=%d", auth.user_id, len(text))
    return JSONResponse(
        content={
            "status": "submitted",
            "message": "Your appeal has been submitted and will be reviewed by an administrator.",
        }
    )
