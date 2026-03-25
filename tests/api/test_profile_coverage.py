"""Tests for profile routes: user profile, level system, leaderboard."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.profile import (
    RANKS,
    TOKENS_PER_POINT,
    _calculate_level,
    _points_for_level,
    _rank_name,
    router,
)
from tests.fakes import FakeAuthProvider


# ── Level System Unit Tests ───────────────────────────────────────


class TestCalculateLevel:
    def test_zero_points(self) -> None:
        assert _calculate_level(0) == 0

    def test_negative_points(self) -> None:
        assert _calculate_level(-5) == 0

    def test_one_point(self) -> None:
        assert _calculate_level(1) == 1  # log2(2) = 1

    def test_three_points(self) -> None:
        assert _calculate_level(3) == 2  # log2(4) = 2

    def test_seven_points(self) -> None:
        assert _calculate_level(7) == 3  # log2(8) = 3

    def test_max_level_capped(self) -> None:
        assert _calculate_level(999_999) == len(RANKS) - 1  # max 10

    def test_exact_boundary(self) -> None:
        # Level 5 requires 31 pts: 2^5 - 1
        assert _calculate_level(31) == 5
        assert _calculate_level(30) == 4


class TestRankName:
    def test_level_zero(self) -> None:
        assert _rank_name(0) == "Peasant"

    def test_level_five(self) -> None:
        assert _rank_name(5) == RANKS[5]

    def test_max_level(self) -> None:
        assert _rank_name(10) == "Sovereign"

    def test_beyond_max_clamped(self) -> None:
        assert _rank_name(99) == "Sovereign"


class TestPointsForLevel:
    def test_level_zero(self) -> None:
        assert _points_for_level(0) == 0

    def test_level_one(self) -> None:
        assert _points_for_level(1) == 1

    def test_level_five(self) -> None:
        assert _points_for_level(5) == 31

    def test_level_ten(self) -> None:
        assert _points_for_level(10) == 1023


# ── Fake DB + Outcome Store ──────────────────────────────────────


class FakeRow(dict[str, Any]):
    """Dict subclass that supports both [] and .get() access."""

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(key)


class FakeConnection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._rows = [FakeRow(r) for r in (rows or [])]
        self.executed: list[str] = []

    async def fetchrow(self, sql: str, *args: Any) -> FakeRow | None:
        self.executed.append(sql)
        return self._rows[0] if self._rows else None

    async def fetch(self, sql: str, *args: Any) -> list[FakeRow]:
        self.executed.append(sql)
        return self._rows

    async def execute(self, sql: str, *args: Any) -> str:
        self.executed.append(sql)
        return "UPDATE 1"


class FakePool:
    def __init__(self, conn: FakeConnection) -> None:
        self._conn = conn

    def acquire(self) -> FakePool:
        return self

    async def __aenter__(self) -> FakeConnection:
        return self._conn

    async def __aexit__(self, *args: Any) -> None:
        pass


class FakeOutcomeStore:
    """Outcome store returning configurable usage breakdowns."""

    def __init__(self, breakdown: list[dict[str, Any]] | None = None) -> None:
        self._breakdown = breakdown or []

    async def get_usage_breakdown(self, **kwargs: Any) -> list[dict[str, Any]]:
        return self._breakdown

    async def record(self, outcome: Any) -> int:
        return 1

    async def get_task_completion_rate(self, **kwargs: Any) -> dict[str, Any]:
        return {}

    async def get_experience_context(self, task_type: str, **kwargs: Any) -> str:
        return ""

    async def list_outcomes(self, **kwargs: Any) -> list[Any]:
        return []


class FailingOutcomeStore(FakeOutcomeStore):
    async def get_usage_breakdown(self, **kwargs: Any) -> list[dict[str, Any]]:
        msg = "DB down"
        raise RuntimeError(msg)


# ── Minimal Container ────────────────────────────────────────────


class _Container:
    def __init__(
        self,
        *,
        auth_provider: Any = None,
        db_pool: Any = None,
        outcome_store: Any = None,
    ) -> None:
        self.auth_provider = auth_provider or FakeAuthProvider()
        self.db_pool = db_pool
        self.outcome_store = outcome_store or FakeOutcomeStore()


def _make_app(
    *,
    db_pool: Any = None,
    outcome_store: Any = None,
    auth_provider: Any = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.container = _Container(
        auth_provider=auth_provider or FakeAuthProvider(),
        db_pool=db_pool,
        outcome_store=outcome_store or FakeOutcomeStore(),
    )
    return app


AUTH = {"Authorization": "Bearer sk-test"}


# ── GET /v1/stronghold/profile ───────────────────────────────────


class TestGetProfile:
    def test_unauthenticated_returns_401(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile")
            assert resp.status_code == 401

    def test_no_db_returns_minimal_profile(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile", headers=AUTH)
            assert resp.status_code == 200
            data = resp.json()
            assert data["points"] == 0
            assert data["level"] == 0
            assert data["rank"] == "Peasant"
            assert data["level_progress"] >= 0

    def test_with_db_user(self) -> None:
        conn = FakeConnection(rows=[{
            "id": 1,
            "email": "alice@example.com",
            "display_name": "Alice",
            "org_id": "org-1",
            "team_id": "team-a",
            "roles": ["admin"],
            "avatar_data": "base64...",
            "bio": "hello",
            "team_bio": "we code",
        }])
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile", headers=AUTH)
            assert resp.status_code == 200
            data = resp.json()
            assert data["display_name"] == "Alice"
            assert data["bio"] == "hello"
            assert data["roles"] == ["admin"]

    def test_with_token_usage(self) -> None:
        outcome = FakeOutcomeStore(breakdown=[
            {"group": "system", "total_tokens": 500_000},
        ])
        app = _make_app(outcome_store=outcome)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile", headers=AUTH)
            data = resp.json()
            assert data["total_tokens"] == 500_000
            assert data["points"] == 500_000 // TOKENS_PER_POINT
            assert data["level"] > 0

    def test_outcome_store_failure_returns_zero_points(self) -> None:
        app = _make_app(outcome_store=FailingOutcomeStore())
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile", headers=AUTH)
            assert resp.status_code == 200
            assert resp.json()["points"] == 0

    def test_no_user_in_db_returns_empty_user_data(self) -> None:
        conn = FakeConnection(rows=[])
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile", headers=AUTH)
            assert resp.status_code == 200
            data = resp.json()
            assert "display_name" not in data  # no user_data merged

    def test_max_level_progress_is_one(self) -> None:
        # Give enough tokens for level 10 (1023+ points = 10_230_000 tokens)
        outcome = FakeOutcomeStore(breakdown=[
            {"group": "system", "total_tokens": 20_000_000},
        ])
        app = _make_app(outcome_store=outcome)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile", headers=AUTH)
            data = resp.json()
            assert data["level"] == 10
            assert data["rank"] == "Sovereign"
            assert data["level_progress"] == 1.0

    def test_roles_not_list_coerced(self) -> None:
        """If roles is a string in DB, profile returns empty list."""
        conn = FakeConnection(rows=[{
            "id": 1, "email": "a@b.c", "display_name": "A",
            "org_id": "o", "team_id": "t", "roles": "admin",
        }])
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/profile", headers=AUTH)
            assert resp.json()["roles"] == []


# ── PUT /v1/stronghold/profile ───────────────────────────────────


class TestUpdateProfile:
    def test_unauthenticated_returns_401(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.put("/v1/stronghold/profile", json={"bio": "hi"})
            assert resp.status_code == 401

    def test_no_db_returns_503(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.put("/v1/stronghold/profile", json={"bio": "hi"}, headers=AUTH)
            assert resp.status_code == 503
            assert "Database" in resp.json()["detail"]

    def test_no_valid_fields_returns_400(self) -> None:
        conn = FakeConnection()
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put("/v1/stronghold/profile", json={"unknown": "x"}, headers=AUTH)
            assert resp.status_code == 400
            assert "No valid fields" in resp.json()["detail"]

    def test_non_string_field_ignored(self) -> None:
        conn = FakeConnection()
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put("/v1/stronghold/profile", json={"bio": 42}, headers=AUTH)
            assert resp.status_code == 400  # no valid fields

    def test_avatar_too_large_returns_400(self) -> None:
        conn = FakeConnection()
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/profile",
                json={"avatar_data": "x" * 700_001},
                headers=AUTH,
            )
            assert resp.status_code == 400
            assert "Avatar too large" in resp.json()["detail"]

    def test_bio_too_long_returns_400(self) -> None:
        conn = FakeConnection()
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/profile",
                json={"bio": "x" * 2001},
                headers=AUTH,
            )
            assert resp.status_code == 400
            assert "too long" in resp.json()["detail"]

    def test_team_bio_too_long_returns_400(self) -> None:
        conn = FakeConnection()
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/profile",
                json={"team_bio": "x" * 2001},
                headers=AUTH,
            )
            assert resp.status_code == 400

    def test_successful_update(self) -> None:
        conn = FakeConnection()
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/profile",
                json={"bio": "hello", "display_name": "Alice"},
                headers=AUTH,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "updated"
            assert "bio" in data["fields"]
            assert "display_name" in data["fields"]
            assert any("UPDATE" in s for s in conn.executed)

    def test_user_not_found_returns_404(self) -> None:
        conn = FakeConnection()
        # Override execute to return 0 affected rows
        async def fake_execute(sql: str, *args: Any) -> str:
            return "UPDATE 0"
        conn.execute = fake_execute  # type: ignore[assignment]

        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/profile",
                json={"bio": "hello"},
                headers=AUTH,
            )
            assert resp.status_code == 404

    def test_multiple_fields_updated(self) -> None:
        conn = FakeConnection()
        app = _make_app(db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.put(
                "/v1/stronghold/profile",
                json={"bio": "a", "team_bio": "b", "avatar_data": "c", "display_name": "d"},
                headers=AUTH,
            )
            assert resp.status_code == 200
            assert len(resp.json()["fields"]) == 4


# ── GET /v1/stronghold/leaderboard ───────────────────────────────


class TestLeaderboard:
    def test_unauthenticated_returns_401(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard")
            assert resp.status_code == 401

    def test_empty_leaderboard(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard", headers=AUTH)
            assert resp.status_code == 200
            data = resp.json()
            assert data["entries"] == []
            assert data["days"] == 0

    def test_leaderboard_with_entries(self) -> None:
        outcome = FakeOutcomeStore(breakdown=[
            {"group": "alice@ex.com", "total_tokens": 100_000, "request_count": 50, "success_count": 45},
            {"group": "bob@ex.com", "total_tokens": 50_000, "request_count": 20, "success_count": 20},
        ])
        app = _make_app(outcome_store=outcome)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard", headers=AUTH)
            data = resp.json()
            assert len(data["entries"]) == 2
            assert data["entries"][0]["rank"] == 1
            assert data["entries"][0]["user_id"] == "alice@ex.com"
            assert data["entries"][0]["points"] == 100_000 // TOKENS_PER_POINT
            assert data["entries"][0]["success_rate"] == 0.9
            assert data["entries"][1]["rank"] == 2

    def test_leaderboard_with_db_enrichment(self) -> None:
        outcome = FakeOutcomeStore(breakdown=[
            {"group": "alice@ex.com", "total_tokens": 50_000, "request_count": 10, "success_count": 10},
        ])
        conn = FakeConnection(rows=[
            FakeRow({"email": "alice@ex.com", "display_name": "Alice", "avatar_data": "av", "team_id": "eng"}),
        ])
        app = _make_app(outcome_store=outcome, db_pool=FakePool(conn))
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard", headers=AUTH)
            entry = resp.json()["entries"][0]
            assert entry["display_name"] == "Alice"
            assert entry["avatar_data"] == "av"
            assert entry["team_id"] == "eng"

    def test_leaderboard_days_param(self) -> None:
        app = _make_app()
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard?days=7", headers=AUTH)
            assert resp.json()["days"] == 7

    def test_leaderboard_zero_requests_zero_success_rate(self) -> None:
        outcome = FakeOutcomeStore(breakdown=[
            {"group": "x@y.z", "total_tokens": 0, "request_count": 0, "success_count": 0},
        ])
        app = _make_app(outcome_store=outcome)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard", headers=AUTH)
            assert resp.json()["entries"][0]["success_rate"] == 0

    def test_leaderboard_limit_param(self) -> None:
        entries = [
            {"group": f"u{i}@x.com", "total_tokens": 1000 * i, "request_count": i, "success_count": i}
            for i in range(10)
        ]
        outcome = FakeOutcomeStore(breakdown=entries)
        app = _make_app(outcome_store=outcome)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard?limit=3", headers=AUTH)
            assert len(resp.json()["entries"]) == 3

    def test_leaderboard_no_db_uses_email_prefix(self) -> None:
        outcome = FakeOutcomeStore(breakdown=[
            {"group": "alice@example.com", "total_tokens": 10_000, "request_count": 1, "success_count": 1},
        ])
        app = _make_app(outcome_store=outcome)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/leaderboard", headers=AUTH)
            entry = resp.json()["entries"][0]
            assert entry["display_name"] == "alice"
