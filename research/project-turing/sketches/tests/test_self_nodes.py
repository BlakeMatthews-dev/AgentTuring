"""Tests for specs/self-nodes.md: AC-24.*."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from turing.self_model import (
    DEFAULT_DECAY_RATES,
    Passion,
    PreferenceKind,
    Skill,
    SkillKind,
    current_level,
)
from turing.self_nodes import (
    downgrade_skill,
    note_hobby,
    note_interest,
    note_passion,
    note_preference,
    note_skill,
    practice_skill,
    rerank_passions,
)


# --------- AC-24.1 passions -------------------------------------------------


def test_ac_24_1_passion_default_rank_and_strength(srepo, self_id, new_id) -> None:
    p = note_passion(srepo, self_id, "work that lasts", 0.8, new_id)
    assert p.strength == 0.8
    assert p.rank == 0
    assert p.self_id == self_id
    p2 = note_passion(srepo, self_id, "craft over speed", 0.7, new_id)
    assert p2.rank == 1


def test_ac_24_1_passion_strength_oor_raises(srepo, self_id, new_id) -> None:
    with pytest.raises(ValueError):
        note_passion(srepo, self_id, "x", 1.1, new_id)


def test_ac_24_1_passion_duplicate_text_case_insensitive_raises(srepo, self_id, new_id) -> None:
    note_passion(srepo, self_id, "Work that Lasts", 0.5, new_id)
    with pytest.raises(ValueError, match="duplicate passion"):
        note_passion(srepo, self_id, "work that LASTS", 0.5, new_id)


# --------- AC-24.2 hobbies --------------------------------------------------


def test_ac_24_2_hobby_last_engaged_at_starts_none(srepo, self_id, new_id) -> None:
    h = note_hobby(srepo, self_id, "Reading", "philosophy of mind", new_id)
    assert h.last_engaged_at is None


def test_ac_24_2_hobby_duplicate_raises(srepo, self_id, new_id) -> None:
    note_hobby(srepo, self_id, "Reading", "X", new_id)
    with pytest.raises(ValueError, match="duplicate hobby"):
        note_hobby(srepo, self_id, "reading", "Y", new_id)


# --------- AC-24.3 interests ------------------------------------------------


def test_ac_24_3_interest_last_noticed_none(srepo, self_id, new_id) -> None:
    i = note_interest(srepo, self_id, "Neuroscience", "brain stuff", new_id)
    assert i.last_noticed_at is None


def test_ac_24_3_interest_duplicate_raises(srepo, self_id, new_id) -> None:
    note_interest(srepo, self_id, "Neuroscience", "", new_id)
    with pytest.raises(ValueError, match="duplicate interest"):
        note_interest(srepo, self_id, "neuroscience", "", new_id)


# --------- AC-24.4 preferences ---------------------------------------------


def test_ac_24_4_preference_unique_kind_target(srepo, self_id, new_id) -> None:
    note_preference(srepo, self_id, PreferenceKind.LIKE, "cats", 0.8, "", new_id)
    with pytest.raises(ValueError, match="duplicate preference"):
        note_preference(srepo, self_id, PreferenceKind.LIKE, "cats", 0.5, "", new_id)


def test_ac_24_4_preference_different_kinds_ok(srepo, self_id, new_id) -> None:
    note_preference(srepo, self_id, PreferenceKind.LIKE, "cats", 0.8, "", new_id)
    # Same target, different kind: allowed.
    note_preference(srepo, self_id, PreferenceKind.FAVORITE, "cats", 0.9, "", new_id)


# --------- AC-24.5 skills ---------------------------------------------------


@pytest.mark.parametrize(
    "kind,expected_rate",
    [
        (SkillKind.INTELLECTUAL, 0.0005),
        (SkillKind.PHYSICAL, 0.005),
        (SkillKind.HABIT, 0.002),
        (SkillKind.SOCIAL, 0.001),
    ],
)
def test_ac_24_5_default_decay_rates(srepo, self_id, new_id, kind, expected_rate) -> None:
    s = note_skill(srepo, self_id, f"skill-{kind.value}", 0.5, kind, new_id)
    assert s.decay_rate_per_day == expected_rate


def test_ac_24_5_skill_duplicate_raises(srepo, self_id, new_id) -> None:
    note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
    with pytest.raises(ValueError, match="duplicate skill"):
        note_skill(srepo, self_id, "Python", 0.5, SkillKind.INTELLECTUAL, new_id)


# --------- AC-24.6 rerank passions ------------------------------------------


def test_ac_24_6_rerank_passions_atomic(srepo, self_id, new_id) -> None:
    p1 = note_passion(srepo, self_id, "A", 0.5, new_id)
    p2 = note_passion(srepo, self_id, "B", 0.5, new_id)
    p3 = note_passion(srepo, self_id, "C", 0.5, new_id)
    result = rerank_passions(srepo, self_id, [p3.node_id, p1.node_id, p2.node_id])
    ranks = {p.node_id: p.rank for p in result}
    assert ranks[p3.node_id] == 0
    assert ranks[p1.node_id] == 1
    assert ranks[p2.node_id] == 2


def test_ac_24_6_rerank_passions_incomplete_list_raises(srepo, self_id, new_id) -> None:
    p1 = note_passion(srepo, self_id, "A", 0.5, new_id)
    note_passion(srepo, self_id, "B", 0.5, new_id)
    with pytest.raises(ValueError, match="ordered_ids must match"):
        rerank_passions(srepo, self_id, [p1.node_id])


def test_ac_24_6_rerank_passions_phantom_id_raises(srepo, self_id, new_id) -> None:
    p1 = note_passion(srepo, self_id, "A", 0.5, new_id)
    p2 = note_passion(srepo, self_id, "B", 0.5, new_id)
    with pytest.raises(ValueError, match="ordered_ids must match"):
        rerank_passions(srepo, self_id, [p1.node_id, p2.node_id, "phantom"])


# --------- AC-24.10 practice_skill updates last_practiced_at ---------------


def test_ac_24_10_practice_updates_last_practiced_at(srepo, self_id, new_id) -> None:
    s = note_skill(srepo, self_id, "python", 0.5, SkillKind.INTELLECTUAL, new_id)
    # Backdate to test that practice_skill resets.
    s_old = s
    s_old.last_practiced_at = datetime.now(UTC) - timedelta(days=30)
    srepo.update_skill(s_old)
    before = srepo.get_skill(s.node_id).last_practiced_at
    after_skill = practice_skill(srepo, self_id, s.node_id)
    assert after_skill.last_practiced_at > before


def test_ac_24_15_practice_cannot_lower_stored_level(srepo, self_id, new_id) -> None:
    s = note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
    with pytest.raises(ValueError, match="cannot lower"):
        practice_skill(srepo, self_id, s.node_id, new_level=0.5)


def test_ac_24_15_downgrade_lowers_and_requires_reason(srepo, self_id, new_id) -> None:
    s = note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
    s2 = downgrade_skill(srepo, self_id, s.node_id, 0.4, "long disuse after injury")
    assert s2.stored_level == 0.4
    with pytest.raises(ValueError, match="reason is required"):
        downgrade_skill(srepo, self_id, s.node_id, 0.3, "")


# --------- AC-24.12..14 current_level maths --------------------------------


def test_ac_24_12_current_level_exponential_decay() -> None:
    s = Skill(
        node_id="x",
        self_id="s",
        name="p",
        kind=SkillKind.PHYSICAL,
        stored_level=1.0,
        decay_rate_per_day=0.005,
        last_practiced_at=datetime.now(UTC) - timedelta(days=30),
    )
    assert current_level(s, datetime.now(UTC)) == pytest.approx(math.exp(-0.15), rel=1e-4)


def test_ac_24_13_current_level_clamped(srepo, self_id, new_id) -> None:
    # stored_level=0.0 → current_level stays 0.0.
    s = note_skill(srepo, self_id, "obscure", 0.0, SkillKind.INTELLECTUAL, new_id)
    assert current_level(s, datetime.now(UTC)) == 0.0


def test_ac_24_14_current_level_is_pure_no_write(srepo, self_id, new_id) -> None:
    s = note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
    before = srepo.get_skill(s.node_id)
    # Advance clock by computing current_level many times.
    for _ in range(10):
        current_level(s, datetime.now(UTC) + timedelta(days=365))
    after = srepo.get_skill(s.node_id)
    # No persistence side effects.
    assert before.stored_level == after.stored_level
    assert before.last_practiced_at == after.last_practiced_at


# --------- AC-24.10 future clock returns stored_level (no past decay) ------


def test_practice_resets_decay_window(srepo, self_id, new_id) -> None:
    s = note_skill(srepo, self_id, "python", 0.9, SkillKind.PHYSICAL, new_id)
    # Backdate.
    s.last_practiced_at = datetime.now(UTC) - timedelta(days=100)
    srepo.update_skill(s)
    decayed = current_level(srepo.get_skill(s.node_id), datetime.now(UTC))
    practice_skill(srepo, self_id, s.node_id)
    fresh = current_level(srepo.get_skill(s.node_id), datetime.now(UTC))
    assert fresh > decayed
    assert fresh == pytest.approx(0.9, rel=1e-3)
