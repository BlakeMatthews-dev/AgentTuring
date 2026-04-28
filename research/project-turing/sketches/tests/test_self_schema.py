"""Tests for specs/self-schema.md: AC-22.* and companion dataclass validation."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from turing.repo import Repo
from turing.self_model import (
    ActivationContributor,
    ContributorOrigin,
    Hobby,
    Interest,
    Mood,
    NodeKind,
    Passion,
    PersonalityAnswer,
    PersonalityFacet,
    PersonalityItem,
    PersonalityRevision,
    Preference,
    PreferenceKind,
    SelfTodo,
    SelfTodoRevision,
    Skill,
    SkillKind,
    TodoStatus,
    Trait,
    facet_node_id,
)
from turing.self_repo import SelfRepo


# --------- fixtures ----------------------------------------------------------


@pytest.fixture
def repos() -> tuple[Repo, SelfRepo]:
    r = Repo(None)
    yield r, SelfRepo(r.conn)
    r.close()


@pytest.fixture
def self_id(repos) -> str:
    r, _ = repos
    from turing.self_identity import bootstrap_self_id

    return bootstrap_self_id(r.conn)


def _now() -> datetime:
    return datetime.now(UTC)


# --------- AC-22.1..3 identity + NodeKind -----------------------------------


def test_ac_22_1_facet_requires_self_id() -> None:
    with pytest.raises(ValueError, match="self_id is required"):
        PersonalityFacet(
            node_id="facet:openness.inquisitiveness",
            self_id="",
            trait=Trait.OPENNESS,
            facet_id="inquisitiveness",
            score=3.0,
            last_revised_at=_now(),
        )


def test_ac_22_2_every_node_kind_member_has_string_value() -> None:
    assert {k.value for k in NodeKind} == {
        "personality_facet",
        "passion",
        "hobby",
        "interest",
        "preference",
        "skill",
        "todo",
        "mood",
    }


def test_ac_22_3_facet_node_id_is_well_formed() -> None:
    nid = facet_node_id(Trait.OPENNESS, "inquisitiveness")
    assert nid == "facet:openness.inquisitiveness"


# --------- AC-22.4..5 personality facet constraints -------------------------


def test_ac_22_5_facet_score_above_range_raises() -> None:
    with pytest.raises(ValueError, match="facet score out of range"):
        PersonalityFacet(
            node_id="x",
            self_id="s",
            trait=Trait.OPENNESS,
            facet_id="inquisitiveness",
            score=5.1,
            last_revised_at=_now(),
        )


def test_ac_22_5_facet_score_below_range_raises() -> None:
    with pytest.raises(ValueError, match="facet score out of range"):
        PersonalityFacet(
            node_id="x",
            self_id="s",
            trait=Trait.OPENNESS,
            facet_id="inquisitiveness",
            score=0.99,
            last_revised_at=_now(),
        )


def test_ac_22_5_facet_trait_facet_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="does not belong to trait"):
        PersonalityFacet(
            node_id="x",
            self_id="s",
            trait=Trait.OPENNESS,
            facet_id="sincerity",  # belongs to HONESTY_HUMILITY
            score=3.0,
            last_revised_at=_now(),
        )


def test_ac_22_5_facet_uniqueness_db_enforced(repos, self_id) -> None:
    _, srepo = repos
    f = PersonalityFacet(
        node_id=facet_node_id(Trait.OPENNESS, "inquisitiveness"),
        self_id=self_id,
        trait=Trait.OPENNESS,
        facet_id="inquisitiveness",
        score=3.0,
        last_revised_at=_now(),
    )
    srepo.insert_facet(f)
    # Inserting a different node_id but same (self_id, trait, facet_id) must fail.
    f2 = PersonalityFacet(
        node_id="other-id",
        self_id=self_id,
        trait=Trait.OPENNESS,
        facet_id="inquisitiveness",
        score=4.0,
        last_revised_at=_now(),
    )
    with pytest.raises(sqlite3.IntegrityError):
        srepo.insert_facet(f2)


# --------- AC-22.7 answer range --------------------------------------------


def test_ac_22_7_personality_answer_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="1..5"):
        PersonalityAnswer(
            node_id="a",
            self_id="s",
            item_id="i",
            revision_id=None,
            answer_1_5=6,
            justification_text="",
            asked_at=_now(),
        )


def test_ac_22_7_personality_answer_justification_cap() -> None:
    with pytest.raises(ValueError, match="justification_text"):
        PersonalityAnswer(
            node_id="a",
            self_id="s",
            item_id="i",
            revision_id=None,
            answer_1_5=3,
            justification_text="x" * 201,
            asked_at=_now(),
        )


# --------- AC-22.8 revision length ------------------------------------------


def test_ac_22_8_revision_sample_length_must_be_20() -> None:
    with pytest.raises(ValueError, match="exactly 20 items"):
        PersonalityRevision(
            node_id="rn",
            self_id="s",
            revision_id="r",
            ran_at=_now(),
            sampled_item_ids=["x"] * 19,
            deltas_by_facet={},
        )


# --------- AC-22.9 passion strength + rank ---------------------------------


def test_ac_22_9_passion_strength_range() -> None:
    with pytest.raises(ValueError, match="strength out of range"):
        Passion(
            node_id="p",
            self_id="s",
            text="x",
            strength=1.1,
            rank=0,
            first_noticed_at=_now(),
        )


def test_ac_22_9_passion_rank_negative_raises() -> None:
    with pytest.raises(ValueError, match="rank must be >= 0"):
        Passion(
            node_id="p",
            self_id="s",
            text="x",
            strength=0.5,
            rank=-1,
            first_noticed_at=_now(),
        )


def test_ac_22_9_passion_rank_uniqueness_db_enforced(repos, self_id) -> None:
    _, srepo = repos
    srepo.insert_passion(
        Passion(
            node_id="p1",
            self_id=self_id,
            text="A",
            strength=0.5,
            rank=0,
            first_noticed_at=_now(),
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        srepo.insert_passion(
            Passion(
                node_id="p2",
                self_id=self_id,
                text="B",
                strength=0.5,
                rank=0,
                first_noticed_at=_now(),
            )
        )


# --------- AC-22.12 preference uniqueness -----------------------------------


def test_ac_22_12_preference_unique_on_kind_target(repos, self_id) -> None:
    _, srepo = repos
    srepo.insert_preference(
        Preference(
            node_id="pr1",
            self_id=self_id,
            kind=PreferenceKind.LIKE,
            target="cats",
            strength=0.9,
            rationale="",
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        srepo.insert_preference(
            Preference(
                node_id="pr2",
                self_id=self_id,
                kind=PreferenceKind.LIKE,
                target="cats",
                strength=0.3,
                rationale="",
            )
        )


# --------- AC-22.13..14 skill invariants ------------------------------------


def test_ac_22_13_skill_stored_level_range() -> None:
    with pytest.raises(ValueError, match="stored_level out of range"):
        Skill(
            node_id="sk",
            self_id="s",
            name="x",
            kind=SkillKind.INTELLECTUAL,
            stored_level=1.01,
            last_practiced_at=_now(),
        )


# --------- AC-22.15..16 todo invariants -------------------------------------


def test_ac_22_15_todo_requires_motivator() -> None:
    with pytest.raises(ValueError, match="motivated_by_node_id is required"):
        SelfTodo(
            node_id="t",
            self_id="s",
            text="x",
            motivated_by_node_id="",
        )


def test_ac_22_15_completed_todo_requires_outcome_text() -> None:
    with pytest.raises(ValueError, match="outcome_text"):
        SelfTodo(
            node_id="t",
            self_id="s",
            text="x",
            motivated_by_node_id="passion:1",
            status=TodoStatus.COMPLETED,
            outcome_text="",
        )


def test_ac_22_15_todo_text_cap_500() -> None:
    SelfTodo(
        node_id="t",
        self_id="s",
        text="x" * 500,
        motivated_by_node_id="passion:1",
    )
    with pytest.raises(ValueError, match="exceeds 500"):
        SelfTodo(
            node_id="t2",
            self_id="s",
            text="x" * 501,
            motivated_by_node_id="passion:1",
        )


def test_ac_22_16_todo_revisions_are_append_only(repos, self_id) -> None:
    r, srepo = repos
    srepo.insert_todo(
        SelfTodo(
            node_id="t",
            self_id=self_id,
            text="original",
            motivated_by_node_id="passion:1",
        )
    )
    srepo.insert_todo_revision(
        SelfTodoRevision(
            node_id="rev1",
            self_id=self_id,
            todo_id="t",
            revision_num=1,
            text_before="original",
            text_after="updated",
            revised_at=_now(),
        )
    )
    # UPDATE must be blocked by the trigger.
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        r.conn.execute(
            "UPDATE self_todo_revisions SET text_after = ? WHERE node_id = ?",
            ("tampered", "rev1"),
        )
        r.conn.commit()
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        r.conn.execute("DELETE FROM self_todo_revisions WHERE node_id = ?", ("rev1",))
        r.conn.commit()


# --------- AC-22.17..18 mood singleton + range ------------------------------


def test_ac_22_17_mood_is_singleton_per_self_id(repos, self_id) -> None:
    _, srepo = repos
    srepo.insert_mood(
        Mood(
            self_id=self_id,
            valence=0.0,
            arousal=0.3,
            focus=0.5,
            last_tick_at=_now(),
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        srepo.insert_mood(
            Mood(
                self_id=self_id,
                valence=0.0,
                arousal=0.3,
                focus=0.5,
                last_tick_at=_now(),
            )
        )


def test_ac_22_18_mood_valence_range_enforced() -> None:
    with pytest.raises(ValueError, match="valence out of range"):
        Mood(
            self_id="s",
            valence=1.1,
            arousal=0.3,
            focus=0.5,
            last_tick_at=_now(),
        )


def test_ac_22_18_mood_arousal_range_enforced() -> None:
    with pytest.raises(ValueError, match="arousal out of range"):
        Mood(
            self_id="s",
            valence=0.0,
            arousal=-0.1,
            focus=0.5,
            last_tick_at=_now(),
        )


# --------- AC-22.19..21 contributor graph -----------------------------------


def test_ac_22_19_contributor_weight_range() -> None:
    with pytest.raises(ValueError, match="weight out of range"):
        ActivationContributor(
            node_id="c",
            self_id="s",
            target_node_id="facet:openness.inquisitiveness",
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:1",
            source_kind="passion",
            weight=1.01,
            origin=ContributorOrigin.SELF,
            rationale="",
        )


def test_ac_22_20_contributor_no_self_loop() -> None:
    with pytest.raises(ValueError, match="cannot target itself"):
        ActivationContributor(
            node_id="c",
            self_id="s",
            target_node_id="passion:1",
            target_kind=NodeKind.PASSION,
            source_id="passion:1",
            source_kind="passion",
            weight=0.5,
            origin=ContributorOrigin.SELF,
            rationale="",
        )


def test_ac_22_21_retrieval_contributor_requires_expiry() -> None:
    with pytest.raises(ValueError, match="retrieval contributors must set expires_at"):
        ActivationContributor(
            node_id="c",
            self_id="s",
            target_node_id="facet:openness.inquisitiveness",
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="mem:1",
            source_kind="retrieval",
            weight=0.3,
            origin=ContributorOrigin.RETRIEVAL,
            rationale="",
        )


def test_ac_22_21_non_retrieval_contributor_rejects_expiry() -> None:
    with pytest.raises(ValueError, match="others must not"):
        ActivationContributor(
            node_id="c",
            self_id="s",
            target_node_id="facet:openness.inquisitiveness",
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:1",
            source_kind="passion",
            weight=0.3,
            origin=ContributorOrigin.SELF,
            rationale="",
            expires_at=_now() + timedelta(minutes=5),
        )


# --------- AC-22.19 DB check: same target/source rejected at DB level -------


def test_ac_22_20_db_rejects_self_loop(repos, self_id) -> None:
    r, _ = repos
    now = _now().isoformat()
    with pytest.raises(sqlite3.IntegrityError):
        r.conn.execute(
            """INSERT INTO self_activation_contributors
               (node_id, self_id, target_node_id, target_kind,
                source_id, source_kind, weight, origin, rationale,
                expires_at, retracted_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("c", self_id, "X", "passion", "X", "passion", 0.5, "self", "", None, None, now, now),
        )
        r.conn.commit()


def test_ac_22_21_db_enforces_retrieval_expiry_correlation(repos, self_id) -> None:
    r, _ = repos
    now = _now()
    iso = now.isoformat()
    exp = (now + timedelta(minutes=5)).isoformat()
    # Non-retrieval + expires_at set should fail.
    with pytest.raises(sqlite3.IntegrityError):
        r.conn.execute(
            """INSERT INTO self_activation_contributors
               (node_id, self_id, target_node_id, target_kind,
                source_id, source_kind, weight, origin, rationale,
                expires_at, retracted_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("c", self_id, "A", "passion", "B", "passion", 0.5, "self", "", exp, None, iso, iso),
        )
        r.conn.commit()
