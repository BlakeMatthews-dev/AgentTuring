"""Tests for specs/activation-graph.md: AC-25.*."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from turing.self_activation import (
    ActivationContext,
    RETRIEVAL_TTL,
    RETRIEVAL_WEIGHT_COEFFICIENT,
    SCALE,
    HOBBY_RECENCY_DAYS,
    INTEREST_RECENCY_DAYS,
    _recency_state,
    _sigmoid,
    active_now,
    source_state,
)
from turing.self_model import (
    ActivationContributor,
    ContributorOrigin,
    Hobby,
    Interest,
    Mood,
    NodeKind,
    Passion,
    PersonalityFacet,
    Preference,
    PreferenceKind,
    Skill,
    SkillKind,
    Trait,
    facet_node_id,
)


# --------- fixtures ----------------------------------------------------------


@pytest.fixture
def seeded_facet(srepo, self_id):
    nid = facet_node_id(Trait.OPENNESS, "inquisitiveness")
    srepo.insert_facet(
        PersonalityFacet(
            node_id=nid,
            self_id=self_id,
            trait=Trait.OPENNESS,
            facet_id="inquisitiveness",
            score=3.0,
            last_revised_at=datetime.now(UTC),
        )
    )
    return nid


@pytest.fixture
def seeded_passion(srepo, self_id):
    p = Passion(
        node_id="passion:1",
        self_id=self_id,
        text="I care about work that lasts",
        strength=0.8,
        rank=0,
        first_noticed_at=datetime.now(UTC),
    )
    srepo.insert_passion(p)
    return p


@pytest.fixture
def seeded_mood(srepo, self_id):
    srepo.insert_mood(
        Mood(self_id=self_id, valence=0.6, arousal=0.3, focus=0.5, last_tick_at=datetime.now(UTC))
    )


def _ctx(
    self_id: str, now: datetime | None = None, retrieval: dict[str, float] | None = None
) -> ActivationContext:
    return ActivationContext(
        self_id=self_id,
        now=now or datetime.now(UTC),
        retrieval_similarity=retrieval or {},
    )


# --------- AC-25.6 aggregation formula --------------------------------------


def test_ac_25_6_zero_contributors_returns_neutral(srepo, self_id, seeded_facet) -> None:
    got = active_now(srepo, seeded_facet, _ctx(self_id))
    # AC-25.20 says 0-contributor nodes return exactly 0.5 (sigmoid(0)).
    assert got == pytest.approx(0.5)


def test_ac_25_6_single_positive_self_contributor_moves_up(
    srepo, self_id, seeded_facet, seeded_passion
) -> None:
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c1",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id=seeded_passion.node_id,
            source_kind="passion",
            weight=0.8,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    raw = 0.8 * seeded_passion.strength
    expected = _sigmoid(raw / SCALE)
    got = active_now(srepo, seeded_facet, _ctx(self_id))
    assert got == pytest.approx(expected)


def test_ac_25_6_sum_over_multiple_contributors(srepo, self_id, seeded_facet) -> None:
    srepo.insert_passion(
        Passion(
            node_id="passion:10",
            self_id=self_id,
            text="x",
            strength=1.0,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    srepo.insert_passion(
        Passion(
            node_id="passion:11",
            self_id=self_id,
            text="y",
            strength=0.5,
            rank=1,
            first_noticed_at=datetime.now(UTC),
        )
    )
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c1",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:10",
            source_kind="passion",
            weight=0.6,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c2",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:11",
            source_kind="passion",
            weight=0.4,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    # raw = 0.6*1.0 + 0.4*0.5 = 0.8
    expected = _sigmoid(0.8 / SCALE)
    assert active_now(srepo, seeded_facet, _ctx(self_id)) == pytest.approx(expected)


# --------- AC-25.4 inhibitory + excitatory ---------------------------------


def test_ac_25_4_inhibitory_contributor_subtracts(
    srepo, self_id, seeded_facet, seeded_passion
) -> None:
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c+",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:1",
            source_kind="passion",
            weight=+0.5,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c-",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:1",
            source_kind="passion",
            weight=-0.3,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    raw = (0.5 - 0.3) * seeded_passion.strength  # 0.2 * 0.8 = 0.16
    expected = _sigmoid(raw / SCALE)
    assert active_now(srepo, seeded_facet, _ctx(self_id)) == pytest.approx(expected)


# --------- AC-25.7 source_state resolution ---------------------------------


def test_ac_25_7_personality_facet_remap_to_0_1(srepo, self_id, seeded_facet) -> None:
    # score=3 → (3-1)/4 = 0.5
    assert source_state(srepo, seeded_facet, "personality_facet", _ctx(self_id)) == pytest.approx(
        0.5
    )


def test_ac_25_7_passion_state_is_strength(srepo, self_id, seeded_passion) -> None:
    assert source_state(srepo, seeded_passion.node_id, "passion", _ctx(self_id)) == pytest.approx(
        0.8
    )


def test_ac_25_7_hobby_state_from_recency(srepo, self_id) -> None:
    fresh = Hobby(
        node_id="hobby:1",
        self_id=self_id,
        name="recent",
        description="",
        last_engaged_at=datetime.now(UTC) - timedelta(days=1),
    )
    srepo.insert_hobby(fresh)
    ctx = _ctx(self_id)
    got = source_state(srepo, "hobby:1", "hobby", ctx)
    # 1 day / 14 → 1 - (1/14) ≈ 0.9286
    assert got == pytest.approx(1.0 - 1.0 / HOBBY_RECENCY_DAYS, rel=1e-6)

    stale = Hobby(
        node_id="hobby:2",
        self_id=self_id,
        name="stale",
        description="",
        last_engaged_at=datetime.now(UTC) - timedelta(days=60),
    )
    srepo.insert_hobby(stale)
    assert source_state(srepo, "hobby:2", "hobby", ctx) == 0.0


def test_ac_25_7_interest_state_from_recency(srepo, self_id) -> None:
    fresh = Interest(
        node_id="interest:1",
        self_id=self_id,
        topic="neuro",
        description="",
        last_noticed_at=datetime.now(UTC) - timedelta(days=3),
    )
    srepo.insert_interest(fresh)
    ctx = _ctx(self_id)
    assert source_state(srepo, "interest:1", "interest", ctx) == pytest.approx(
        1.0 - 3.0 / INTEREST_RECENCY_DAYS
    )


def test_ac_25_7_skill_state_is_current_level(srepo, self_id) -> None:
    s = Skill(
        node_id="skill:x",
        self_id=self_id,
        name="x",
        kind=SkillKind.INTELLECTUAL,
        stored_level=1.0,
        last_practiced_at=datetime.now(UTC) - timedelta(days=100),
    )
    srepo.insert_skill(s)
    got = source_state(srepo, "skill:x", "skill", _ctx(self_id))
    assert got == pytest.approx(1.0)


def test_ac_25_7_mood_state_is_normalized_valence(srepo, self_id, seeded_mood) -> None:
    ctx = _ctx(self_id)
    got = source_state(srepo, "mood", "mood", ctx)
    # valence 0.6 → (0.6+1)/2 = 0.8
    assert got == pytest.approx(0.8)


def test_ac_25_7_rule_state_is_one(srepo, self_id) -> None:
    assert source_state(srepo, "any-rule-id", "rule", _ctx(self_id)) == 1.0


def test_ac_25_7_retrieval_state_uses_similarity(srepo, self_id) -> None:
    ctx = _ctx(self_id, retrieval={"mem:42": 0.77})
    assert source_state(srepo, "mem:42", "retrieval", ctx) == pytest.approx(0.77)


def test_ac_25_7_unknown_source_kind_raises(srepo, self_id) -> None:
    with pytest.raises(ValueError, match="unknown source_kind"):
        source_state(srepo, "whatever", "grimoire", _ctx(self_id))


# --------- AC-25.8 deterministic -------------------------------------------


def test_ac_25_8_deterministic_under_same_clock(
    srepo, self_id, seeded_facet, seeded_passion
) -> None:
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id=seeded_passion.node_id,
            source_kind="passion",
            weight=0.5,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    ctx = _ctx(self_id)
    got1 = active_now(srepo, seeded_facet, ctx)
    got2 = active_now(srepo, seeded_facet, ctx)
    assert got1 == got2


# --------- AC-25.12 expired retrieval contributors -------------------------


def test_ac_25_12_expired_retrieval_contributors_ignored(srepo, self_id, seeded_facet) -> None:
    past_expiry = datetime.now(UTC) - timedelta(seconds=1)
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c-retr",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="mem:99",
            source_kind="retrieval",
            weight=0.9,
            origin=ContributorOrigin.RETRIEVAL,
            rationale="",
            expires_at=past_expiry,
        )
    )
    assert active_now(srepo, seeded_facet, _ctx(self_id)) == pytest.approx(0.5)


# --------- AC-25.15 retracted contributors ignored -------------------------


def test_ac_25_15_retracted_contributor_does_not_contribute(
    srepo, self_id, seeded_facet, seeded_passion
) -> None:
    srepo.insert_contributor(
        ActivationContributor(
            node_id="retractable",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id=seeded_passion.node_id,
            source_kind="passion",
            weight=0.9,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    srepo.mark_contributor_retracted("retractable", retracted_by="self")
    assert active_now(srepo, seeded_facet, _ctx(self_id)) == pytest.approx(0.5)


# --------- AC-25.21 polarity property test ---------------------------------


def test_ac_25_21_only_positive_contributors_exceed_baseline(
    srepo, self_id, seeded_facet, seeded_passion
) -> None:
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id=seeded_passion.node_id,
            source_kind="passion",
            weight=0.5,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    assert active_now(srepo, seeded_facet, _ctx(self_id)) > 0.5


def test_ac_25_21_only_negative_contributors_below_baseline(
    srepo, self_id, seeded_facet, seeded_passion
) -> None:
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id=seeded_passion.node_id,
            source_kind="passion",
            weight=-0.5,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    assert active_now(srepo, seeded_facet, _ctx(self_id)) < 0.5


# --------- AC-25.22 sigmoid saturation --------------------------------------


def test_ac_25_22_dominant_sum_saturates_below_one(srepo, self_id, seeded_facet) -> None:
    # Create 5 passions at full strength each contributing +1.0 (raw sum = 5).
    for i in range(5):
        pid = f"passion:{i}"
        srepo.insert_passion(
            Passion(
                node_id=pid,
                self_id=self_id,
                text=f"p{i}",
                strength=1.0,
                rank=i,
                first_noticed_at=datetime.now(UTC),
            )
        )
        srepo.insert_contributor(
            ActivationContributor(
                node_id=f"c{i}",
                self_id=self_id,
                target_node_id=seeded_facet,
                target_kind=NodeKind.PERSONALITY_FACET,
                source_id=pid,
                source_kind="passion",
                weight=1.0,
                origin=ContributorOrigin.SELF,
                rationale="",
            )
        )
    # sigmoid(5/2) ≈ 0.924; strictly < 1.
    got = active_now(srepo, seeded_facet, _ctx(self_id))
    assert 0.9 < got < 1.0


# --------- AC-25.23 dangling source treated as weight-0 --------------------


def test_ac_25_23_dangling_source_does_not_raise(srepo, self_id, seeded_facet) -> None:
    srepo.insert_contributor(
        ActivationContributor(
            node_id="cdangle",
            self_id=self_id,
            target_node_id=seeded_facet,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:ghost",
            source_kind="passion",
            weight=0.9,
            origin=ContributorOrigin.SELF,
            rationale="",
        )
    )
    # Dangling source → skipped; no other contributors → neutral.
    assert active_now(srepo, seeded_facet, _ctx(self_id)) == pytest.approx(0.5)


# --------- _recency_state helper --------------------------------------------


def test_recency_state_linear_between_zero_and_window() -> None:
    now = datetime.now(UTC)
    half = now - timedelta(days=7)
    assert _recency_state(half, now, 14.0) == pytest.approx(0.5)


def test_recency_state_none_is_zero() -> None:
    assert _recency_state(None, datetime.now(UTC), 14.0) == 0.0
