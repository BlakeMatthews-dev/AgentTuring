"""Self-reflection ritual — weekly scheduled reflection. See specs/self-reflection-ritual.md."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class ReflectionOutput:
    lessons: int = 0
    wisdom_candidates: int = 0
    todo_revisions: int = 0
    personality_claims: int = 0


REFLECTION_LESSON_CAP: int = 3
REFLECTION_WISDOM_CAP: int = 2
REFLECTION_TODO_CAP: int = 5
REFLECTION_CLAIM_CAP: int = 3
REFLECTION_MEMORY_CAP: int = 50
REFLECTION_MIN_MEMORIES: int = 3
REFLECTION_INPUT_BUDGET: int = 8000
REFLECTION_OUTPUT_BUDGET: int = 3000
REFLECTION_TIMEOUT_SEC: float = 60.0


class ReflectionOutputBudgetExceeded(Exception):
    def __init__(self, category: str, limit: int) -> None:
        self.category = category
        self.limit = limit
        super().__init__(f"reflection output budget exceeded: {category} (limit {limit})")


class ReflectionAdvisoryLock(Exception):
    pass


def select_reflection_memories(repo, self_id: str, now: datetime) -> list:
    rows = repo.conn.execute(
        "SELECT memory_id, content, tier, created_at FROM episodic_memory "
        "WHERE self_id = ? AND tier IN ('REGRET', 'AFFIRMATION') "
        "ORDER BY created_at DESC LIMIT 30",
        (self_id,),
    ).fetchall()
    observations = repo.conn.execute(
        "SELECT memory_id, content, tier, created_at FROM episodic_memory "
        "WHERE self_id = ? AND tier = 'OBSERVATION' "
        "ORDER BY created_at DESC LIMIT 20",
        (self_id,),
    ).fetchall()
    all_rows = list(rows) + list(observations)
    return all_rows[:REFLECTION_MEMORY_CAP]


def check_output_budget(output: ReflectionOutput, category: str) -> None:
    caps = {
        "lessons": REFLECTION_LESSON_CAP,
        "wisdom_candidates": REFLECTION_WISDOM_CAP,
        "todo_revisions": REFLECTION_TODO_CAP,
        "personality_claims": REFLECTION_CLAIM_CAP,
    }
    limit = caps.get(category)
    if limit is None:
        return
    current = getattr(output, category, 0)
    if current >= limit:
        raise ReflectionOutputBudgetExceeded(category, limit)


_SESSION_COUNTS: dict[str, int] = {}


def get_reflection_counts() -> dict[str, int]:
    return dict(_SESSION_COUNTS)


def record_reflection_session(output: ReflectionOutput) -> None:
    _SESSION_COUNTS["sessions"] = _SESSION_COUNTS.get("sessions", 0) + 1
    _SESSION_COUNTS["lessons"] = _SESSION_COUNTS.get("lessons", 0) + output.lessons
    _SESSION_COUNTS["wisdom_candidates"] = (
        _SESSION_COUNTS.get("wisdom_candidates", 0) + output.wisdom_candidates
    )
