"""Tests for the in-memory OutcomeStore wiring in make_test_container.

The original file (issue #626) asserted ``hasattr(store, "__class__")``
(tautology — every Python object has one) and ``store._outcomes == []``.
This replacement drives the real ``record`` / ``get_task_completion_rate``
contract so that a regression in the store implementation actually fails.
"""

from __future__ import annotations

from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.types.memory import Outcome
from tests.fakes import make_test_container


class TestDefaultOutcomeStoreWiring:
    """make_test_container wires an InMemoryOutcomeStore that starts
    empty and assigns monotonically increasing IDs on record."""

    def test_container_provides_in_memory_outcome_store(self) -> None:
        container = make_test_container()
        assert type(container.outcome_store) is InMemoryOutcomeStore

    async def test_fresh_store_has_zero_completion_rate(self) -> None:
        container = make_test_container()
        stats = await container.outcome_store.get_task_completion_rate(days=7)
        assert stats["total"] == 0
        assert stats["succeeded"] == 0
        assert stats["failed"] == 0
        assert stats["rate"] == 0.0


class TestOutcomeRecordContract:
    """Record returns a fresh, monotonically increasing ID, and the
    recorded outcome is retrievable via completion stats."""

    async def test_record_assigns_incrementing_ids(self) -> None:
        store = make_test_container().outcome_store

        o1 = Outcome(
            user_id="alice",
            org_id="__system__",
            model_used="m",
            success=True,
        )
        o2 = Outcome(
            user_id="bob",
            org_id="__system__",
            model_used="m",
            success=False,
        )
        id1 = await store.record(o1)
        id2 = await store.record(o2)

        assert id1 == 1
        assert id2 == 2
        assert o1.id == 1
        assert o2.id == 2

    async def test_recorded_outcomes_feed_completion_rate(self) -> None:
        store = make_test_container().outcome_store
        for i in range(4):
            await store.record(
                Outcome(
                    user_id=f"u{i}",
                    org_id="__system__",
                    model_used="m",
                    success=(i % 2 == 0),
                )
            )

        stats = await store.get_task_completion_rate(days=30, org_id="__system__")
        assert stats["total"] == 4
        assert stats["succeeded"] == 2
        assert stats["failed"] == 2
        assert stats["rate"] == 0.5

    async def test_org_scoping_isolates_outcomes(self) -> None:
        """Cross-org reads must not leak — other orgs see zero total."""
        store = make_test_container().outcome_store
        await store.record(
            Outcome(
                user_id="alice",
                org_id="acme",
                model_used="m",
                success=True,
            )
        )
        # Different org asking for its own stats sees nothing.
        other = await store.get_task_completion_rate(days=30, org_id="wayland")
        assert other["total"] == 0
        # Same org sees its single outcome.
        same = await store.get_task_completion_rate(days=30, org_id="acme")
        assert same["total"] == 1
        assert same["succeeded"] == 1
