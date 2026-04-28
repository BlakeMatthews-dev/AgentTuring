"""Coverage gap filler for turing/self_todos.py.

Spec: AC-26 cross-self guards, motivator existence checks for
hobby/interest/preference/skill node prefixes, guess_node_kind mapping for all
prefixes, revise text-too-long guard, and complete without
affirmation_memory_id (no contributor written).

Acceptance criteria:
- write_self_todo rejects unknown motivator prefixes (not facet/passion/etc)
- revise_self_todo rejects text > 500 chars
- revise_self_todo rejects cross-self revision
- complete_self_todo without affirmation_memory_id writes no contributor
- archive_self_todo rejects cross-self archive
- complete_self_todo rejects cross-self completion
- guess_node_kind returns correct NodeKind for every prefix
- _motivator_exists returns True for hobby/interest/preference/skill prefixes
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_model import (
    Hobby,
    Interest,
    NodeKind,
    Passion,
    Preference,
    PreferenceKind,
    Skill,
    SkillKind,
    TodoStatus,
)
from turing.self_model import guess_node_kind
from turing.self_todos import (
    TodoNotActive,
    TodoTextTooLong,
    archive_self_todo,
    complete_self_todo,
    revise_self_todo,
    write_self_todo,
)


def _insert_passion(srepo, self_id) -> str:
    srepo.insert_passion(
        Passion(
            node_id="passion:seed",
            self_id=self_id,
            text="test passion",
            strength=0.5,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    return "passion:seed"


def _insert_facet(srepo, self_id) -> str:
    from turing.self_model import PersonalityFacet, Trait, facet_node_id

    fid = facet_node_id(Trait.HONESTY_HUMILITY, "sincerity")
    existing = srepo.get_facet(fid)
    if existing is not None:
        return fid
    srepo.insert_facet(
        PersonalityFacet(
            node_id=fid,
            self_id=self_id,
            trait=Trait.HONESTY_HUMILITY,
            facet_id="sincerity",
            score=3.0,
            last_revised_at=datetime.now(UTC),
        )
    )
    return fid


def _insert_hobby(srepo, self_id) -> str:
    srepo.insert_hobby(
        Hobby(
            node_id="hobby:1",
            self_id=self_id,
            name="reading",
            description="books",
        )
    )
    return "hobby:1"


def _insert_interest(srepo, self_id) -> str:
    srepo.insert_interest(
        Interest(
            node_id="interest:1",
            self_id=self_id,
            topic="neuroscience",
            description="brain",
        )
    )
    return "interest:1"


def _insert_preference(srepo, self_id) -> str:
    srepo.insert_preference(
        Preference(
            node_id="pref:1",
            self_id=self_id,
            kind=PreferenceKind.LIKE,
            target="coffee",
            strength=0.8,
            rationale="tasty",
        )
    )
    return "pref:1"


def _insert_skill(srepo, self_id) -> str:
    srepo.insert_skill(
        Skill(
            node_id="skill:1",
            self_id=self_id,
            name="python",
            kind=SkillKind.INTELLECTUAL,
            stored_level=0.7,
            last_practiced_at=datetime.now(UTC),
        )
    )
    return "skill:1"


def test_write_todo_with_facet_motivator(srepo, bootstrapped_id, new_id) -> None:
    fid = _insert_facet(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "read more", fid, new_id)
    assert t.motivated_by_node_id == fid
    assert t.status == TodoStatus.ACTIVE


def test_write_todo_with_hobby_motivator(srepo, bootstrapped_id, new_id) -> None:
    hid = _insert_hobby(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "practice more", hid, new_id)
    assert t.motivated_by_node_id == hid


def test_write_todo_with_interest_motivator(srepo, bootstrapped_id, new_id) -> None:
    iid = _insert_interest(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "explore deeper", iid, new_id)
    assert t.motivated_by_node_id == iid


def test_write_todo_with_preference_motivator(srepo, bootstrapped_id, new_id) -> None:
    pid = _insert_preference(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "lean into preference", pid, new_id)
    assert t.motivated_by_node_id == pid


def test_write_todo_with_skill_motivator(srepo, bootstrapped_id, new_id) -> None:
    sid = _insert_skill(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "level up", sid, new_id)
    assert t.motivated_by_node_id == sid


def test_write_todo_unknown_prefix_rejected(srepo, bootstrapped_id, new_id) -> None:
    with pytest.raises(ValueError, match="unknown motivator"):
        write_self_todo(srepo, bootstrapped_id, "x", "unknown:thing", new_id)


def test_revise_cross_self_raises(srepo, bootstrapped_id, new_id) -> None:
    motivator = _insert_passion(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    with pytest.raises(PermissionError, match="cross-self"):
        revise_self_todo(srepo, "other-self-id", t.node_id, "y", "r", new_id)


def test_revise_text_too_long(srepo, bootstrapped_id, new_id) -> None:
    motivator = _insert_passion(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    with pytest.raises(TodoTextTooLong):
        revise_self_todo(srepo, bootstrapped_id, t.node_id, "y" * 501, "r", new_id)


def test_complete_cross_self_raises(srepo, bootstrapped_id, new_id) -> None:
    motivator = _insert_passion(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    with pytest.raises(PermissionError, match="cross-self"):
        complete_self_todo(srepo, "other-self-id", t.node_id, "done", new_id)


def test_complete_without_affirmation_no_contributor(srepo, bootstrapped_id, new_id) -> None:
    motivator = _insert_passion(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    before = len(srepo.active_contributors_for(motivator, at=datetime.now(UTC)))
    complete_self_todo(srepo, bootstrapped_id, t.node_id, "done", new_id)
    after = srepo.active_contributors_for(motivator, at=datetime.now(UTC))
    assert len(after) == before


def test_archive_cross_self_raises(srepo, bootstrapped_id, new_id) -> None:
    motivator = _insert_passion(srepo, bootstrapped_id)
    t = write_self_todo(srepo, bootstrapped_id, "x", motivator, new_id)
    with pytest.raises(PermissionError, match="cross-self"):
        archive_self_todo(srepo, "other-self-id", t.node_id, "reason")


def test_guess_node_kind_facet() -> None:
    assert guess_node_kind("facet:foo") == NodeKind.PERSONALITY_FACET


def test_guess_node_kind_passion() -> None:
    assert guess_node_kind("passion:1") == NodeKind.PASSION


def test_guess_node_kind_hobby() -> None:
    assert guess_node_kind("hobby:1") == NodeKind.HOBBY


def test_guess_node_kind_interest() -> None:
    assert guess_node_kind("interest:1") == NodeKind.INTEREST


def test_guess_node_kind_preference() -> None:
    assert guess_node_kind("pref:1") == NodeKind.PREFERENCE


def test_guess_node_kind_skill() -> None:
    assert guess_node_kind("skill:1") == NodeKind.SKILL


def test_guess_node_kind_unknown_defaults_to_facet() -> None:
    assert guess_node_kind("something:else") == NodeKind.PERSONALITY_FACET
