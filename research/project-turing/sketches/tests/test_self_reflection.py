"""Tests for turing.self_reflection: ReflectionOutput, budget checks, session tracking."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import turing.self_reflection as sr
from turing.self_reflection import (
    REFLECTION_CLAIM_CAP,
    REFLECTION_LESSON_CAP,
    REFLECTION_MEMORY_CAP,
    REFLECTION_MIN_MEMORIES,
    REFLECTION_TODO_CAP,
    REFLECTION_WISDOM_CAP,
    ReflectionOutput,
    ReflectionOutputBudgetExceeded,
    check_output_budget,
    get_reflection_counts,
    record_reflection_session,
    select_reflection_memories,
)


@pytest.fixture(autouse=True)
def _reset_counts():
    sr._SESSION_COUNTS.clear()
    yield
    sr._SESSION_COUNTS.clear()


def test_reflection_output_defaults_are_zero() -> None:
    out = ReflectionOutput()
    assert out.lessons == 0
    assert out.wisdom_candidates == 0
    assert out.todo_revisions == 0
    assert out.personality_claims == 0


def test_check_output_budget_passes_under_limit() -> None:
    out = ReflectionOutput(lessons=2)
    check_output_budget(out, "lessons")


def test_check_output_budget_raises_at_limit() -> None:
    out = ReflectionOutput(lessons=REFLECTION_LESSON_CAP)
    with pytest.raises(ReflectionOutputBudgetExceeded) as exc_info:
        check_output_budget(out, "lessons")
    assert exc_info.value.category == "lessons"
    assert exc_info.value.limit == REFLECTION_LESSON_CAP


def test_select_reflection_memories_returns_capped_list(repo, self_id) -> None:
    now = datetime.now(UTC)
    repo.conn.execute("PRAGMA ignore_check_constraints = ON")
    for i in range(60):
        tier = "REGRET" if i < 35 else "OBSERVATION"
        repo.conn.execute(
            "INSERT INTO episodic_memory "
            "(memory_id, self_id, tier, source, content, weight, affect, "
            "confidence_at_creation, surprise_delta, intent_at_time, "
            "immutable, reinforcement_count, contradiction_count, deleted, "
            "created_at, last_accessed_at, context) "
            "VALUES (?, ?, ?, 'i_did', ?, 0.5, 0.0, 0.5, 0.0, '', 0, 0, 0, 0, ?, ?, NULL)",
            (f"mem:{i}", self_id, tier, f"content {i}", now.isoformat(), now.isoformat()),
        )
    repo.conn.commit()
    repo.conn.execute("PRAGMA ignore_check_constraints = OFF")
    result = select_reflection_memories(repo, self_id, now)
    assert isinstance(result, list)
    assert len(result) <= REFLECTION_MEMORY_CAP


def test_record_reflection_session_increments_counts() -> None:
    record_reflection_session(ReflectionOutput(lessons=2, wisdom_candidates=1))
    counts = get_reflection_counts()
    assert counts["sessions"] == 1
    assert counts["lessons"] == 2
    assert counts["wisdom_candidates"] == 1
    record_reflection_session(ReflectionOutput(lessons=1))
    counts = get_reflection_counts()
    assert counts["sessions"] == 2
    assert counts["lessons"] == 3


def test_get_reflection_counts_returns_copy() -> None:
    record_reflection_session(ReflectionOutput())
    first = get_reflection_counts()
    first["sessions"] = 999
    second = get_reflection_counts()
    assert second["sessions"] == 1


def test_reflection_lesson_cap_is_three() -> None:
    assert REFLECTION_LESSON_CAP == 3
