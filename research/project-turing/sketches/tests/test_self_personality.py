"""Tests for specs/personality.md: AC-23.*."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import pytest

from turing.self_model import (
    ALL_FACETS,
    CANONICAL_FACETS,
    FACET_TO_TRAIT,
    PersonalityFacet,
    PersonalityItem,
    Trait,
    facet_node_id,
)
from turing.self_personality import (
    FACET_DIVERSITY_FLOOR,
    RETEST_SAMPLE_SIZE,
    RETEST_WEIGHT,
    apply_retest,
    compute_facet_deltas,
    draw_bootstrap_profile,
    narrative_weight,
    sample_retest_items,
)
from turing.self_repo import SelfRepo


def _seed_facets(srepo: SelfRepo, self_id: str, score: float = 3.0) -> None:
    now = datetime.now(UTC)
    for trait, facet in ALL_FACETS:
        srepo.insert_facet(
            PersonalityFacet(
                node_id=facet_node_id(trait, facet),
                self_id=self_id,
                trait=trait,
                facet_id=facet,
                score=score,
                last_revised_at=now,
            )
        )


def _seed_items(srepo: SelfRepo, self_id: str) -> list[PersonalityItem]:
    """Seed one-per-facet × 10 = 240 items? Keep simple: one per facet = 24.
    For retest sampling we need >=20 items with good facet coverage."""
    items: list[PersonalityItem] = []
    n = 0
    for trait, facet in ALL_FACETS:
        for k in range(9):  # 9 per facet -> 216 items; close enough to 200
            if n >= 200:
                break
            n += 1
            it = PersonalityItem(
                node_id=f"item:{n}",
                self_id=self_id,
                item_number=n,
                prompt_text=f"I am {facet}.",
                keyed_facet=facet,
                reverse_scored=(k % 3 == 0),
            )
            srepo.insert_item(it)
            items.append(it)
        if n >= 200:
            break
    return items


# --------- AC-23.1 / AC-23.2: canonical 24 facets ------------------------


def test_ac_23_1_exactly_24_facets() -> None:
    assert len(ALL_FACETS) == 24
    facet_names = [f for _, f in ALL_FACETS]
    assert len(set(facet_names)) == 24


def test_ac_23_2_each_facet_maps_to_one_trait() -> None:
    # Inverse of CANONICAL_FACETS must be single-valued.
    seen: dict[str, Trait] = {}
    for trait, facets in CANONICAL_FACETS.items():
        for facet in facets:
            assert facet not in seen, f"{facet} appears under two traits"
            seen[facet] = trait
    assert seen == FACET_TO_TRAIT


# --------- AC-23.6 reverse scoring ---------------------------------------


def test_ac_23_6_reverse_scored_inverts_answer() -> None:
    """For reverse-scored items, 6 - raw is used (5->1, 4->2, 3->3, 2->4, 1->5)."""
    for raw, expected in [(1, 5), (2, 4), (3, 3), (4, 2), (5, 1)]:
        sampled = [
            PersonalityItem(
                node_id="i1",
                self_id="s",
                item_number=1,
                prompt_text="",
                keyed_facet="inquisitiveness",
                reverse_scored=True,
            )
        ]
        deltas = compute_facet_deltas(sampled, [raw], {"inquisitiveness": float(expected)})
        # Delta should be zero because retest mean == current.
        assert deltas["inquisitiveness"][0] == pytest.approx(expected)
        assert deltas["inquisitiveness"][1] == pytest.approx(0.0)


# --------- AC-23.7 bootstrap draw determinism ----------------------------


def test_ac_23_7_bootstrap_draw_deterministic_under_seed() -> None:
    r1 = random.Random(42)
    r2 = random.Random(42)
    assert draw_bootstrap_profile(r1) == draw_bootstrap_profile(r2)


def test_ac_23_7_bootstrap_draw_range() -> None:
    rng = random.Random(7)
    profile = draw_bootstrap_profile(rng)
    assert len(profile) == 24
    for v in profile.values():
        assert 1.0 <= v <= 5.0


# --------- AC-23.12 sampling --------------------------------------------


def test_ac_23_12_retest_sample_is_exactly_20(srepo, self_id) -> None:
    items = _seed_items(srepo, self_id)
    rng = random.Random(3)
    sample = sample_retest_items(
        items=items,
        last_asked={},
        rng=rng,
        now=datetime.now(UTC),
    )
    assert len(sample) == RETEST_SAMPLE_SIZE


def test_ac_23_12_retest_sample_facet_diversity(srepo, self_id) -> None:
    items = _seed_items(srepo, self_id)
    rng = random.Random(3)
    sample = sample_retest_items(
        items=items,
        last_asked={},
        rng=rng,
        now=datetime.now(UTC),
    )
    distinct_facets = {s.keyed_facet for s in sample}
    assert len(distinct_facets) >= FACET_DIVERSITY_FLOOR


def test_ac_23_12_recency_weighted_never_asked_dominates(srepo, self_id) -> None:
    items = _seed_items(srepo, self_id)
    # Mark a small prefix (covering one facet, so facet-diversity still holds
    # for the never-asked pool) as just-asked.
    first_facet = items[0].keyed_facet
    just_asked_ids = {it.node_id for it in items if it.keyed_facet == first_facet}
    very_recent = {nid: datetime.now(UTC) for nid in just_asked_ids}
    rng = random.Random(5)
    sample = sample_retest_items(
        items=items,
        last_asked=very_recent,
        rng=rng,
        now=datetime.now(UTC),
    )
    # The never-asked pool covers >=12 facets (all except first_facet), so the
    # weighted sample's diversity check passes on the first attempt. Expect
    # ~0 picks from the just-asked set given the 10-million-to-one weight ratio.
    hit_recent = sum(1 for s in sample if s.node_id in just_asked_ids)
    assert hit_recent == 0


# --------- AC-23.15..16 retest deltas ------------------------------------


def test_ac_23_15_touched_facets_get_mean(srepo, self_id) -> None:
    items = [
        PersonalityItem(
            node_id=f"item:{i}",
            self_id=self_id,
            item_number=i,
            prompt_text="",
            keyed_facet="inquisitiveness",
            reverse_scored=False,
        )
        for i in range(1, 5)
    ]
    deltas = compute_facet_deltas(items, [1, 2, 3, 4], {"inquisitiveness": 3.0})
    # Mean retest = 2.5. Delta = 0.25 * (2.5 - 3.0) = -0.125.
    assert deltas["inquisitiveness"][0] == pytest.approx(2.5)
    assert deltas["inquisitiveness"][1] == pytest.approx(-0.125)


def test_ac_23_15_untouched_facets_absent(srepo, self_id) -> None:
    items = [
        PersonalityItem(
            node_id="item:1",
            self_id=self_id,
            item_number=1,
            prompt_text="",
            keyed_facet="inquisitiveness",
            reverse_scored=False,
        )
    ]
    deltas = compute_facet_deltas(items, [4], {"inquisitiveness": 3.0, "sincerity": 3.0})
    assert "sincerity" not in deltas


def test_ac_23_16_delta_applies_retest_weight() -> None:
    # Single facet, current=2.0, raw=5.
    items = [
        PersonalityItem(
            node_id="item:1",
            self_id="s",
            item_number=1,
            prompt_text="",
            keyed_facet="creativity",
            reverse_scored=False,
        )
    ]
    deltas = compute_facet_deltas(items, [5], {"creativity": 2.0})
    assert deltas["creativity"][1] == pytest.approx(RETEST_WEIGHT * (5 - 2.0))


# --------- AC-23.14 atomicity: invalid answer aborts ---------------------


def test_ac_23_14_invalid_answer_aborts_before_mutation(srepo, self_id, new_id) -> None:
    _seed_facets(srepo, self_id, score=3.0)
    items = _seed_items(srepo, self_id)
    sampled = items[:20]

    # This ask_self returns a bad answer on the 5th call.
    def bad_ask(it: PersonalityItem) -> tuple[int, str]:
        bad_ask.n += 1
        if bad_ask.n == 5:
            return (9, "out of range")
        return (3, "meh")

    bad_ask.n = 0

    score_before = srepo.get_facet_score(self_id, "inquisitiveness")
    with pytest.raises(ValueError, match="invalid retest answer"):
        apply_retest(
            repo=srepo,
            self_id=self_id,
            sampled=sampled,
            ask_self=bad_ask,
            now=datetime.now(UTC),
            new_id=new_id,
        )
    score_after = srepo.get_facet_score(self_id, "inquisitiveness")
    assert score_before == score_after
    # No revision row inserted either.
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM self_personality_revisions WHERE self_id = ?",
        (self_id,),
    ).fetchone()
    assert rows[0] == 0


# --------- AC-23.16 apply_retest moves scores by 25% ---------------------


def test_ac_23_16_apply_retest_moves_score_by_25_pct(srepo, self_id, new_id) -> None:
    # Seed facets at a known score; rig ask_self to return constant 5 for every item.
    _seed_facets(srepo, self_id, score=3.0)
    items = _seed_items(srepo, self_id)
    sampled = items[:20]

    # All items answered "5". Reverse-scored items get their effective score as 1.
    def ask(it: PersonalityItem) -> tuple[int, str]:
        return (5, "")

    apply_retest(
        repo=srepo,
        self_id=self_id,
        sampled=sampled,
        ask_self=ask,
        now=datetime.now(UTC),
        new_id=new_id,
    )

    # For each touched facet, compute expected delta: mean(scored) where
    # scored = 6-5 = 1 for reverse-scored and 5 otherwise.
    from collections import defaultdict

    by_facet: dict[str, list[int]] = defaultdict(list)
    for it in sampled:
        by_facet[it.keyed_facet].append(1 if it.reverse_scored else 5)
    for facet, vals in by_facet.items():
        retest_mean = sum(vals) / len(vals)
        expected = 3.0 + RETEST_WEIGHT * (retest_mean - 3.0)
        assert srepo.get_facet_score(self_id, facet) == pytest.approx(expected)


# --------- AC-23.18 revision row written --------------------------------


def test_ac_23_18_apply_retest_persists_revision(srepo, self_id, new_id) -> None:
    _seed_facets(srepo, self_id, score=3.0)
    items = _seed_items(srepo, self_id)
    sampled = items[:20]

    def ask(it: PersonalityItem) -> tuple[int, str]:
        return (3, "")

    apply_retest(
        repo=srepo,
        self_id=self_id,
        sampled=sampled,
        ask_self=ask,
        now=datetime.now(UTC),
        new_id=new_id,
    )
    revs = srepo.conn.execute(
        "SELECT COUNT(*) FROM self_personality_revisions WHERE self_id = ?",
        (self_id,),
    ).fetchone()
    assert revs[0] == 1


# --------- narrative_weight ---------------------------------------------


def test_narrative_weight_floor_and_ceiling() -> None:
    # Empty evidence → floor = 0.1.
    assert narrative_weight("", "claim") == pytest.approx(0.1)
    # Very long evidence → ceiling = 0.4.
    assert narrative_weight("x" * 2000, "claim") == pytest.approx(0.4)
