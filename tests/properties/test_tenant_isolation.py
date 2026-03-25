"""Property-based tests for multi-tenant isolation.

Uses hypothesis to generate random org/team/user combinations and
verify that data isolation invariants ALWAYS hold.

These are the strongest guarantees for Fortune 100 due diligence:
"For ANY two organizations, data written by one is NEVER visible to the other."
"""

from __future__ import annotations

import asyncio

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.memory.learnings.store import InMemoryLearningStore
from stronghold.memory.outcomes import InMemoryOutcomeStore
from stronghold.sessions.store import (
    InMemorySessionStore,
    build_session_id,
    validate_session_ownership,
)
from stronghold.types.memory import Learning


# Strategy: org IDs are non-empty alphanumeric strings
org_ids = st.text(
    alphabet=st.characters(whitelist_categories=("Ll", "Nd")),
    min_size=1,
    max_size=20,
)


class TestSessionIsolation:
    """Sessions: data written by org_a is never visible to org_b."""

    @given(org_a=org_ids, org_b=org_ids)
    @settings(max_examples=50)
    def test_cross_org_session_ownership(self, org_a: str, org_b: str) -> None:
        """Session owned by org_a is never owned by org_b (unless same org)."""
        sid = build_session_id(org_a, "team", "user", "chat")
        if org_a == org_b:
            assert validate_session_ownership(sid, org_b)
        else:
            assert not validate_session_ownership(sid, org_b)

    @given(org_a=org_ids)
    @settings(max_examples=20)
    def test_session_ownership_reflexive(self, org_a: str) -> None:
        """An org always owns its own sessions."""
        sid = build_session_id(org_a, "team", "user", "chat")
        assert validate_session_ownership(sid, org_a)

    @given(org_a=org_ids, org_b=org_ids)
    @settings(max_examples=50)
    def test_session_data_isolation(self, org_a: str, org_b: str) -> None:
        """Messages appended by org_a cannot be read by org_b."""
        if org_a == org_b:
            return  # Skip same-org case

        store = InMemorySessionStore()
        sid_a = build_session_id(org_a, "team", "user", "main")
        sid_b = build_session_id(org_b, "team", "user", "main")

        asyncio.get_event_loop().run_until_complete(
            store.append_messages(sid_a, [{"role": "user", "content": "secret-a"}])
        )

        # org_b's session is a different key
        history_b = asyncio.get_event_loop().run_until_complete(
            store.get_history(sid_b)
        )
        assert len(history_b) == 0, "org_b must not see org_a's messages"


class TestLearningIsolation:
    """Learnings: org_a queries must never return org_b's learnings."""

    @given(org_a=org_ids, org_b=org_ids)
    @settings(max_examples=50)
    def test_cross_org_learning_invisible(self, org_a: str, org_b: str) -> None:
        """Learning stored by org_a is invisible to org_b."""
        if org_a == org_b:
            return

        store = InMemoryLearningStore()
        lr = Learning(
            category="test",
            trigger_keys=["deploy", "fix"],
            learning="secret correction",
            tool_name="shell",
            org_id=org_a,
        )
        asyncio.get_event_loop().run_until_complete(store.store(lr))

        # org_b should see nothing
        results = asyncio.get_event_loop().run_until_complete(
            store.find_relevant("deploy fix", org_id=org_b)
        )
        assert len(results) == 0, f"org_b ({org_b}) must not see org_a ({org_a}) learnings"


class TestOutcomeIsolation:
    """Outcomes: org_a stats must exclude org_b's outcomes."""

    @given(org_a=org_ids, org_b=org_ids)
    @settings(max_examples=50)
    def test_cross_org_outcome_invisible(self, org_a: str, org_b: str) -> None:
        """Outcomes recorded by org_a excluded from org_b's stats."""
        if org_a == org_b:
            return

        from datetime import UTC, datetime

        from stronghold.types.memory import Outcome

        store = InMemoryOutcomeStore()
        asyncio.get_event_loop().run_until_complete(
            store.record(
                Outcome(
                    task_type="code",
                    success=True,
                    model_used="m1",
                    org_id=org_a,
                    created_at=datetime.now(UTC),
                )
            )
        )

        stats = asyncio.get_event_loop().run_until_complete(
            store.get_task_completion_rate(org_id=org_b)
        )
        assert stats["total"] == 0, f"org_b ({org_b}) must not see org_a ({org_a}) outcomes"


class TestWardenDeterminism:
    """Warden: same input always produces same flags (deterministic)."""

    @given(text=st.text(min_size=5, max_size=200))
    @settings(max_examples=30)
    def test_warden_scan_deterministic(self, text: str) -> None:
        """Scanning the same text twice produces identical results."""
        from stronghold.security.warden.detector import Warden

        w = Warden()
        v1 = asyncio.get_event_loop().run_until_complete(w.scan(text, "user_input"))
        v2 = asyncio.get_event_loop().run_until_complete(w.scan(text, "user_input"))
        assert v1.clean == v2.clean
        assert v1.flags == v2.flags
