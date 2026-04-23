"""Tests for InMemoryCheckpointStore — the SessionCheckpoint store (S1.3)."""

from __future__ import annotations

from datetime import UTC, datetime

from stronghold.memory.sessions.store import InMemoryCheckpointStore
from stronghold.types.memory import MemoryScope, SessionCheckpoint


def _cp(
    checkpoint_id: str = "",
    *,
    org_id: str = "org-1",
    user_id: str | None = "u-1",
    agent_id: str | None = "artificer",
    team_id: str | None = "team-1",
    scope: MemoryScope = MemoryScope.SESSION,
    created_at: datetime | None = None,
    summary: str = "s",
) -> SessionCheckpoint:
    return SessionCheckpoint(
        checkpoint_id=checkpoint_id,
        session_id="sess-1",
        agent_id=agent_id,
        user_id=user_id,
        org_id=org_id,
        team_id=team_id,
        scope=scope,
        branch=None,
        summary=summary,
        decisions=(),
        remaining=(),
        notes=(),
        failed_approaches=(),
        created_at=created_at or datetime.now(UTC),
        source="agent",
    )


async def test_save_returns_stable_id() -> None:
    """AC 2: save returns a non-empty id."""
    store = InMemoryCheckpointStore()
    cp = _cp()
    cp_id = await store.save(cp)
    assert cp_id
    assert isinstance(cp_id, str)


async def test_load_returns_saved_checkpoint() -> None:
    """Baseline: save then load returns an equivalent checkpoint."""
    store = InMemoryCheckpointStore()
    cp = _cp(summary="my summary")
    cp_id = await store.save(cp)
    loaded = await store.load(cp_id, org_id="org-1")
    assert loaded is not None
    assert loaded.summary == "my summary"


async def test_load_respects_org_isolation() -> None:
    """AC 3: cross-org load returns None even with a valid checkpoint_id."""
    store = InMemoryCheckpointStore()
    cp = _cp(org_id="org-a")
    cp_id = await store.save(cp)
    # Same id, different org → None (never a leak)
    assert await store.load(cp_id, org_id="org-b") is None
    # Same org → returns the checkpoint
    assert await store.load(cp_id, org_id="org-a") is not None


async def test_list_recent_respects_scope_filter() -> None:
    """AC 4: list_recent respects scope filter / tenant boundary."""
    store = InMemoryCheckpointStore()
    await store.save(_cp(org_id="org-a", summary="a"))
    await store.save(_cp(org_id="org-b", summary="b"))
    org_a_items = await store.list_recent(org_id="org-a")
    assert len(org_a_items) == 1
    assert org_a_items[0].summary == "a"


async def test_list_recent_limit() -> None:
    """AC 5: list_recent respects the limit parameter."""
    store = InMemoryCheckpointStore()
    for i in range(50):
        await store.save(_cp(summary=f"c{i}"))
    items = await store.list_recent(org_id="org-1", limit=10)
    assert len(items) == 10


async def test_list_recent_ordering() -> None:
    """AC 5: results sorted by created_at descending."""
    store = InMemoryCheckpointStore()
    t_old = datetime(2026, 1, 1, tzinfo=UTC)
    t_new = datetime(2026, 4, 23, tzinfo=UTC)
    await store.save(_cp(summary="old", created_at=t_old))
    await store.save(_cp(summary="new", created_at=t_new))
    items = await store.list_recent(org_id="org-1")
    assert [i.summary for i in items] == ["new", "old"]


async def test_user_scope_isolation_between_users_same_org() -> None:
    """AC 4 (scope): users in same org isolated when list_recent filters by user_id."""
    store = InMemoryCheckpointStore()
    await store.save(_cp(user_id="alice", summary="alice's"))
    await store.save(_cp(user_id="bob", summary="bob's"))
    alice_only = await store.list_recent(org_id="org-1", user_id="alice")
    assert len(alice_only) == 1
    assert alice_only[0].summary == "alice's"


async def test_team_scope_filter() -> None:
    """list_recent respects team_id filter."""
    store = InMemoryCheckpointStore()
    await store.save(_cp(team_id="team-a", summary="a"))
    await store.save(_cp(team_id="team-b", summary="b"))
    team_a = await store.list_recent(org_id="org-1", team_id="team-a")
    assert [i.summary for i in team_a] == ["a"]


async def test_agent_scope_filter() -> None:
    """list_recent respects agent_id filter."""
    store = InMemoryCheckpointStore()
    await store.save(_cp(agent_id="artificer", summary="art"))
    await store.save(_cp(agent_id="scribe", summary="scr"))
    artificer_only = await store.list_recent(org_id="org-1", agent_id="artificer")
    assert [i.summary for i in artificer_only] == ["art"]
