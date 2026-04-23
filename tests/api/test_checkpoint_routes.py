"""Admin route tests for checkpoints (S1.3)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stronghold.api.routes.checkpoints import router as checkpoints_router
from stronghold.memory.sessions.store import InMemoryCheckpointStore
from stronghold.types.auth import AuthContext, IdentityKind
from stronghold.types.memory import MemoryScope, SessionCheckpoint


@dataclass
class _FakeAuthProvider:
    """Returns a configurable AuthContext (admin or non-admin) per Authorization value."""

    admin_key: str = "sk-admin"
    user_key: str = "sk-user"
    admin_org: str = "org-a"
    user_org: str = "org-a"

    async def authenticate(
        self,
        authorization: str | None,
        headers: dict[str, str] | None = None,  # noqa: ARG002
    ) -> AuthContext:
        if not authorization:
            raise ValueError("Missing Authorization")
        token = authorization.removeprefix("Bearer ").strip()
        if token == self.admin_key:
            return AuthContext(
                user_id="admin",
                org_id=self.admin_org,
                team_id="team-1",
                roles=frozenset({"admin"}),
                kind=IdentityKind.USER,
            )
        if token == self.user_key:
            return AuthContext(
                user_id="user",
                org_id=self.user_org,
                team_id="team-1",
                roles=frozenset(),
                kind=IdentityKind.USER,
            )
        raise ValueError("Invalid key")


def _make_cp(
    *,
    org_id: str,
    summary: str = "s",
    checkpoint_id: str = "",
    created_at: datetime | None = None,
) -> SessionCheckpoint:
    return SessionCheckpoint(
        checkpoint_id=checkpoint_id,
        session_id="sess-1",
        agent_id=None,
        user_id="u-1",
        org_id=org_id,
        team_id=None,
        scope=MemoryScope.SESSION,
        branch=None,
        summary=summary,
        decisions=(),
        remaining=(),
        notes=(),
        failed_approaches=(),
        created_at=created_at or datetime.now(UTC),
        source="agent",
    )


def _make_app(
    store: InMemoryCheckpointStore,
    auth: _FakeAuthProvider | None = None,
) -> FastAPI:
    """Minimal app with just the checkpoints router and a fake Container stub."""
    app = FastAPI()
    app.include_router(checkpoints_router)

    class _ContainerStub:
        pass

    container = _ContainerStub()
    container.auth_provider = auth or _FakeAuthProvider()  # type: ignore[attr-defined]
    container.checkpoint_store = store  # type: ignore[attr-defined]
    app.state.container = container
    return app


class TestListCheckpoints:
    def test_list_requires_admin_role(self) -> None:
        store = InMemoryCheckpointStore()
        app = _make_app(store)
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/admin/checkpoints",
                headers={"Authorization": "Bearer sk-user"},
            )
            assert resp.status_code == 403

    def test_list_requires_auth(self) -> None:
        store = InMemoryCheckpointStore()
        app = _make_app(store)
        with TestClient(app) as client:
            resp = client.get("/v1/stronghold/admin/checkpoints")
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_returns_items(self) -> None:
        store = InMemoryCheckpointStore()
        await store.save(_make_cp(org_id="org-a", summary="first"))
        await store.save(_make_cp(org_id="org-a", summary="second"))
        app = _make_app(store)
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/admin/checkpoints",
                headers={"Authorization": "Bearer sk-admin"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert "items" in body
            assert len(body["items"]) == 2
            assert {i["summary"] for i in body["items"]} == {"first", "second"}


class TestGetCheckpoint:
    @pytest.mark.asyncio
    async def test_get_returns_checkpoint(self) -> None:
        store = InMemoryCheckpointStore()
        cp_id = await store.save(_make_cp(org_id="org-a", summary="my cp"))
        app = _make_app(store)
        with TestClient(app) as client:
            resp = client.get(
                f"/v1/stronghold/admin/checkpoints/{cp_id}",
                headers={"Authorization": "Bearer sk-admin"},
            )
            assert resp.status_code == 200
            assert resp.json()["summary"] == "my cp"

    @pytest.mark.asyncio
    async def test_get_returns_404_for_unknown(self) -> None:
        store = InMemoryCheckpointStore()
        app = _make_app(store)
        with TestClient(app) as client:
            resp = client.get(
                "/v1/stronghold/admin/checkpoints/nonexistent",
                headers={"Authorization": "Bearer sk-admin"},
            )
            assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_returns_404_for_cross_org(self) -> None:
        """AC 3, 7: cross-org access returns 404, not 403 (existence hiding)."""
        store = InMemoryCheckpointStore()
        cp_id = await store.save(_make_cp(org_id="org-b", summary="other tenant"))
        # Auth provider returns admin for org-a; the checkpoint is in org-b.
        app = _make_app(store, _FakeAuthProvider(admin_org="org-a"))
        with TestClient(app) as client:
            resp = client.get(
                f"/v1/stronghold/admin/checkpoints/{cp_id}",
                headers={"Authorization": "Bearer sk-admin"},
            )
            assert resp.status_code == 404
