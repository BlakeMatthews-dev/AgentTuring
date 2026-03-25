"""API route: profile — user profile, avatar, bio, points, leaderboard."""

from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("stronghold.api.profile")

router = APIRouter()

# ── Level System ──
# 1 point per 10,000 tokens. Levels use log2 growth.
# Level N requires 2^N - 1 points to reach.

RANKS = [
    "Peasant",  # Level 0  (0 pts)
    "Squire",  # Level 1  (1+ pts)
    "Page",  # Level 2  (3+ pts)
    "Apprentice",  # Level 3  (7+ pts)
    "Knight",  # Level 4  (15+ pts)
    "Champion",  # Level 5  (31+ pts)
    "Commander",  # Level 6  (63+ pts)
    "Lord",  # Level 7  (127+ pts)
    "Baron",  # Level 8  (255+ pts)
    "Duke",  # Level 9  (511+ pts)
    "Sovereign",  # Level 10 (1023+ pts)
]

TOKENS_PER_POINT = 10_000


def _calculate_level(points: int) -> int:
    """Level = floor(log2(points + 1)). Max level 10."""
    if points <= 0:
        return 0
    return min(int(math.log2(points + 1)), len(RANKS) - 1)


def _rank_name(level: int) -> str:
    return RANKS[min(level, len(RANKS) - 1)]


def _points_for_level(level: int) -> int:
    """Points required to reach a level: 2^level - 1."""
    return int((2**level) - 1)


async def _authenticate(request: Request) -> Any:
    """Authenticate request and return AuthContext."""
    container = request.app.state.container
    auth_header = request.headers.get("authorization")
    try:
        return await container.auth_provider.authenticate(
            auth_header, headers=dict(request.headers)
        )
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e


@router.get("/v1/stronghold/profile")
async def get_profile(request: Request) -> JSONResponse:
    """Get the current user's profile with points and level."""
    auth = await _authenticate(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)

    # Fetch user record from DB
    user_data: dict[str, Any] = {}
    if pool:
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE email = $1", auth.user_id)
            if row:
                user_data = {
                    "id": row["id"],
                    "email": row["email"],
                    "display_name": row["display_name"],
                    "org_id": row["org_id"],
                    "team_id": row["team_id"],
                    "roles": row["roles"] if isinstance(row["roles"], list) else [],
                    "avatar_data": row.get("avatar_data", ""),
                    "bio": row.get("bio", ""),
                    "team_bio": row.get("team_bio", ""),
                }

    # Calculate points from all-time token usage
    total_tokens = 0
    try:
        breakdown = await container.outcome_store.get_usage_breakdown(
            group_by="user_id", days=0, org_id=auth.org_id
        )
        for entry in breakdown:
            if entry["group"] == auth.user_id:
                total_tokens = entry["total_tokens"]
                break
    except Exception:  # noqa: BLE001
        pass

    points = total_tokens // TOKENS_PER_POINT
    level = _calculate_level(points)
    rank = _rank_name(level)
    next_level_pts = _points_for_level(level + 1) if level < len(RANKS) - 1 else points
    current_level_pts = _points_for_level(level)
    progress = (
        (points - current_level_pts) / (next_level_pts - current_level_pts)
        if next_level_pts > current_level_pts
        else 1.0
    )

    return JSONResponse(
        content={
            **user_data,
            "total_tokens": total_tokens,
            "points": points,
            "level": level,
            "rank": rank,
            "next_level_points": next_level_pts,
            "level_progress": round(progress, 3),
        }
    )


@router.get("/v1/stronghold/profile/coins")
async def get_profile_coins(request: Request) -> JSONResponse:
    """Get the current user's applicable coin wallets and balances."""
    auth = await _authenticate(request)
    container = request.app.state.container
    summary = await container.coin_ledger.get_subject_summary(
        org_id=auth.org_id,
        team_id=auth.team_id,
        user_id=auth.user_id,
    )
    return JSONResponse(content=summary)


@router.put("/v1/stronghold/profile")
async def update_profile(request: Request) -> JSONResponse:
    """Update profile fields (avatar, bio, team_bio, display_name)."""
    auth = await _authenticate(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)
    if not pool:
        raise HTTPException(status_code=503, detail="Database not available")

    body: dict[str, Any] = await request.json()

    # Whitelist updatable fields
    updates: list[str] = []
    params: list[Any] = []
    param_idx = 1

    for field in ("display_name", "bio", "team_bio", "avatar_data"):
        if field in body:
            value = body[field]
            if not isinstance(value, str):
                continue
            # Limit avatar to ~500KB base64 (~375KB image)
            if field == "avatar_data" and len(value) > 700_000:
                raise HTTPException(status_code=400, detail="Avatar too large (max ~500KB)")
            # Limit bio fields to 2000 chars
            if field in ("bio", "team_bio") and len(value) > 2000:
                raise HTTPException(status_code=400, detail=f"{field} too long (max 2000 chars)")
            param_idx += 1
            updates.append(f"{field} = ${param_idx}")
            params.append(value)

    if not updates:
        raise HTTPException(status_code=400, detail="No valid fields to update")

    params.insert(0, auth.user_id)  # $1 = email
    sql = f"UPDATE users SET {', '.join(updates)}, updated_at = NOW() WHERE email = $1"

    async with pool.acquire() as conn:
        result = await conn.execute(sql, *params)

    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")

    logger.info("Profile updated: user=%s fields=%s", auth.user_id, list(body.keys()))
    return JSONResponse(content={"status": "updated", "fields": list(body.keys())})


@router.get("/v1/stronghold/leaderboard")
async def get_leaderboard(request: Request, days: int = 0, limit: int = 50) -> JSONResponse:
    """Get the leaderboard: users ranked by points (token usage).

    Args:
        days: Time window (0 = all-time, 7 = last week, 30 = last month)
        limit: Max entries to return (default 50)
    """
    auth = await _authenticate(request)
    container = request.app.state.container
    pool = getattr(container, "db_pool", None)

    # Get token usage breakdown
    breakdown = await container.outcome_store.get_usage_breakdown(
        group_by="user_id", days=days, org_id=auth.org_id
    )

    # Build user lookup for display names and avatars
    user_lookup: dict[str, dict[str, str]] = {}
    if pool:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT email, display_name, avatar_data, team_id FROM users WHERE org_id = $1",
                auth.org_id,
            )
            for r in rows:
                user_lookup[r["email"]] = {
                    "display_name": r["display_name"] or r["email"].split("@")[0],
                    "avatar_data": r.get("avatar_data", "") or "",
                    "team_id": r["team_id"] or "default",
                }

    entries = []
    for i, item in enumerate(breakdown[:limit]):
        user_id = item["group"]
        total_tokens = item["total_tokens"]
        points = total_tokens // TOKENS_PER_POINT
        level = _calculate_level(points)
        info = user_lookup.get(user_id, {})

        entries.append(
            {
                "rank": i + 1,
                "user_id": user_id,
                "display_name": info.get("display_name", user_id.split("@")[0]),
                "avatar_data": info.get("avatar_data", ""),
                "team_id": info.get("team_id", ""),
                "total_tokens": total_tokens,
                "points": points,
                "level": level,
                "rank_name": _rank_name(level),
                "requests": item["request_count"],
                "success_rate": round(item["success_count"] / item["request_count"], 2)
                if item["request_count"] > 0
                else 0,
            }
        )

    return JSONResponse(content={"entries": entries, "days": days})
