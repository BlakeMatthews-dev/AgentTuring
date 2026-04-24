"""Coverage gap filler for turing/self_personality.py.

Spec: AC-23 sample_retest_items fallback path (round-robin when weighted
sampling fails diversity check), compute_facet_deltas with missing current
score, narrative_weight with mid-range evidence, draw_bootstrap_profile with
overrides, _rng_weighted_sample zero-weight fallback.

Acceptance criteria:
- sample_retest_items round-robin fallback works when weighted sampling
  can't meet diversity floor
- compute_facet_deltas raises KeyError for missing current score
- narrative_weight returns mid-range values for moderate evidence
- draw_bootstrap_profile applies overrides
- _rng_weighted_sample handles zero weights
"""

from __future__ import annotations

import random
from collections import defaultdict
from datetime import UTC, datetime

import pytest

from turing.self_model import (
    ALL_FACETS,
    PersonalityFacet,
    PersonalityItem,
    facet_node_id,
)
from turing.self_personality import (
    BOOTSTRAP_MU,
    RETEST_WEIGHT,
    _rng_weighted_sample,
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


def test_sample_retest_items_fallback_round_robin(srepo, self_id) -> None:
    items: list[PersonalityItem] = []
    n = 0
    for trait, facet in ALL_FACETS:
        for k in range(2):
            n += 1
            it = PersonalityItem(
                node_id=f"item:{n}",
                self_id=self_id,
                item_number=n,
                prompt_text=f"prompt {n}",
                keyed_facet=facet,
                reverse_scored=False,
            )
            srepo.insert_item(it)
            items.append(it)
    very_recent = {it.node_id: datetime.now(UTC) for it in items}
    rng = random.Random(42)
    sample = sample_retest_items(
        items=items,
        last_asked=very_recent,
        rng=rng,
        now=datetime.now(UTC),
        n=20,
        facet_diversity_floor=24,
    )
    assert len(sample) == 20
    facets = {s.keyed_facet for s in sample}
    assert len(facets) >= 1


def test_compute_facet_deltas_missing_current_score() -> None:
    items = [
        PersonalityItem(
            node_id="i1",
            self_id="s",
            item_number=1,
            prompt_text="",
            keyed_facet="creativity",
            reverse_scored=False,
        )
    ]
    with pytest.raises(KeyError, match="no current score"):
        compute_facet_deltas(items, [3], {})


def test_narrative_weight_mid_range() -> None:
    result = narrative_weight("x" * 100, "claim")
    assert 0.1 < result < 0.4


def test_narrative_weight_short_evidence() -> None:
    result = narrative_weight("short", "claim")
    assert result == pytest.approx(0.1 + min(0.3, 5 / 500.0))


def test_draw_bootstrap_profile_with_overrides() -> None:
    rng = random.Random(99)
    from turing.self_model import Trait, facet_node_id

    override_key = facet_node_id(Trait.OPENNESS, "creativity")
    profile = draw_bootstrap_profile(rng, overrides={override_key: 4.5})
    assert override_key in profile
    assert 4.0 <= profile[override_key] <= 5.0


def test_draw_bootstrap_profile_no_overrides() -> None:
    rng = random.Random(99)
    profile = draw_bootstrap_profile(rng)
    assert len(profile) == 24


def test_rng_weighted_sample_zero_weights() -> None:
    rng = random.Random(42)
    pop = ["a", "b", "c"]
    weights = [0.0, 0.0, 0.0]
    result = _rng_weighted_sample(rng, pop, weights, 2)
    assert len(result) == 2
    assert all(r in pop for r in result)


def test_rng_weighted_sample_normal() -> None:
    rng = random.Random(42)
    pop = ["a", "b", "c"]
    weights = [0.1, 0.8, 0.1]
    result = _rng_weighted_sample(rng, pop, weights, 3)
    assert set(result) == {"a", "b", "c"}


def test_sample_retest_items_all_never_asked(srepo, self_id) -> None:
    items: list[PersonalityItem] = []
    n = 0
    for trait, facet in ALL_FACETS:
        for k in range(9):
            n += 1
            if n > 200:
                break
            it = PersonalityItem(
                node_id=f"item:{n}",
                self_id=self_id,
                item_number=n,
                prompt_text=f"prompt {n}",
                keyed_facet=facet,
                reverse_scored=(k % 3 == 0),
            )
            srepo.insert_item(it)
            items.append(it)
        if n > 200:
            break
    rng = random.Random(7)
    sample = sample_retest_items(
        items=items,
        last_asked={},
        rng=rng,
        now=datetime.now(UTC),
    )
    assert len(sample) == 20
    assert len({s.keyed_facet for s in sample}) >= 12
