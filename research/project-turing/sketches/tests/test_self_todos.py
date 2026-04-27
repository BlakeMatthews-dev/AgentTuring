"""Tests for specs/self-todos.md: AC-26.*."""

from __future__ import annotations

import pytest

from turing.self_model import Passion, TodoStatus
from turing.self_repo import SelfRepo
from turing.self_todos import (
    TodoNotActive,
    TodoTextTooLong,
    archive_self_todo,
    complete_self_todo,
    revise_self_todo,
    write_self_todo,
)
from datetime import UTC, datetime


@pytest.fixture
def motivator(srepo, bootstrapped_id) -> str:
    srepo.insert_passion(
        Passion(
            node_id="passion:seed",
            self_id=bootstrapped_id,
            text="I care about things that last",
            strength=0.7,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    return "passion:seed"


# --------- AC-26.1..5 creation ---------------------------------------------


def test_ac_26_1_write_todo_defaults_active(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "Re-read Tulving", motivator, new_id)
    assert t.status == TodoStatus.ACTIVE
    assert t.outcome_text is None
    assert t.motivated_by_node_id == motivator


def test_ac_26_2_missing_motivator_raises(srepo, bootstrapped_id, new_id) -> None:
    with pytest.raises(ValueError, match="motivated_by_node_id is required"):
        write_self_todo(srepo, bootstrapped_id, "x", "", new_id)


def test_ac_26_3_dangling_motivator_raises(srepo, bootstrapped_id, new_id) -> None:
    with pytest.raises(ValueError, match="unknown motivator"):
        write_self_todo(srepo, bootstrapped_id, "x", "passion:ghost", new_id)


def test_ac_26_4_todo_text_cap(srepo, bootstrapped_id, new_id, motivator) -> None:
    # 500 OK
    write_self_todo(srepo, bootstrapped_id, "x" * 500, motivator, new_id)
    with pytest.raises(TodoTextTooLong):
        write_self_todo(srepo, bootstrapped_id, "x" * 501, motivator, new_id)


# --------- AC-26.6..10 revision -------------------------------------------


def test_ac_26_6_revise_appends_history(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "original", motivator, new_id)
    revise_self_todo(srepo, bootstrapped_id, t.node_id, "updated once", "clarification", new_id)
    revise_self_todo(srepo, bootstrapped_id, t.node_id, "updated twice", "more", new_id)
    revs = srepo.list_todo_revisions(t.node_id)
    assert [r.revision_num for r in revs] == [1, 2]
    assert [r.text_after for r in revs] == ["updated once", "updated twice"]


def test_ac_26_7_revise_completed_todo_raises(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "original", motivator, new_id)
    complete_self_todo(srepo, bootstrapped_id, t.node_id, "done", new_id)
    with pytest.raises(TodoNotActive):
        revise_self_todo(srepo, bootstrapped_id, t.node_id, "x", "x", new_id)


def test_ac_26_7_revise_archived_todo_raises(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "original", motivator, new_id)
    archive_self_todo(srepo, bootstrapped_id, t.node_id, "changed mind")
    with pytest.raises(TodoNotActive):
        revise_self_todo(srepo, bootstrapped_id, t.node_id, "x", "x", new_id)


def test_ac_26_8_revision_num_monotonic(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "a", motivator, new_id)
    for i in range(5):
        revise_self_todo(srepo, bootstrapped_id, t.node_id, f"v{i}", "r", new_id)
    revs = srepo.list_todo_revisions(t.node_id)
    assert [r.revision_num for r in revs] == [1, 2, 3, 4, 5]


# --------- AC-26.11..14 completion ----------------------------------------


def test_ac_26_11_complete_requires_outcome(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    with pytest.raises(ValueError, match="outcome_text is required"):
        complete_self_todo(srepo, bootstrapped_id, t.node_id, "  ", new_id)


def test_ac_26_11_complete_sets_status_and_outcome(
    srepo, bootstrapped_id, new_id, motivator
) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    done = complete_self_todo(srepo, bootstrapped_id, t.node_id, "great outcome", new_id)
    assert done.status == TodoStatus.COMPLETED
    assert done.outcome_text == "great outcome"


def test_ac_26_13_double_complete_raises(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    complete_self_todo(srepo, bootstrapped_id, t.node_id, "done", new_id)
    with pytest.raises(TodoNotActive):
        complete_self_todo(srepo, bootstrapped_id, t.node_id, "done again", new_id)


def test_ac_26_14_completion_writes_contributor_when_memory_id_provided(
    srepo, bootstrapped_id, new_id, motivator
) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    before = len(srepo.active_contributors_for(motivator, at=datetime.now(UTC)))
    complete_self_todo(
        srepo, bootstrapped_id, t.node_id, "done", new_id, affirmation_memory_id="mem:42"
    )
    after = srepo.active_contributors_for(motivator, at=datetime.now(UTC))
    assert len(after) == before + 1
    new = [c for c in after if c.source_id == "mem:42"][0]
    assert new.weight == pytest.approx(0.3)


# --------- AC-26.15..17 archival ------------------------------------------


def test_ac_26_15_archive_sets_status(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    archive_self_todo(srepo, bootstrapped_id, t.node_id, "priorities shifted")
    after = srepo.get_todo(t.node_id)
    assert after.status == TodoStatus.ARCHIVED


def test_ac_26_16_archive_completed_raises(srepo, bootstrapped_id, new_id, motivator) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    complete_self_todo(srepo, bootstrapped_id, t.node_id, "done", new_id)
    with pytest.raises(TodoNotActive):
        archive_self_todo(srepo, bootstrapped_id, t.node_id, "reason")


# --------- AC-26.18..19 queries -------------------------------------------


def test_ac_26_18_list_active_orders_by_created_at(
    srepo, bootstrapped_id, new_id, motivator
) -> None:
    t1 = write_self_todo(srepo, bootstrapped_id, "first", motivator, new_id)
    t2 = write_self_todo(srepo, bootstrapped_id, "second", motivator, new_id)
    t3 = write_self_todo(srepo, bootstrapped_id, "third", motivator, new_id)
    archive_self_todo(srepo, bootstrapped_id, t2.node_id, "skip")
    active = srepo.list_active_todos(bootstrapped_id)
    assert [t.node_id for t in active] == [t1.node_id, t3.node_id]


def test_ac_26_19_list_for_motivator(srepo, bootstrapped_id, new_id, motivator) -> None:
    write_self_todo(srepo, bootstrapped_id, "a", motivator, new_id)
    write_self_todo(srepo, bootstrapped_id, "b", motivator, new_id)
    got = srepo.list_todos_for_motivator(bootstrapped_id, motivator)
    assert {t.text for t in got} == {"a", "b"}


# --------- AC-26.22 lock/race (serial simulation) -------------------------


def test_ac_26_22_complete_after_revise_still_works(
    srepo, bootstrapped_id, new_id, motivator
) -> None:
    t = write_self_todo(srepo, bootstrapped_id, "original", motivator, new_id)
    revise_self_todo(srepo, bootstrapped_id, t.node_id, "updated", "reason", new_id)
    complete_self_todo(srepo, bootstrapped_id, t.node_id, "done", new_id)
    final = srepo.get_todo(t.node_id)
    assert final.text == "updated"
    assert final.status == TodoStatus.COMPLETED
