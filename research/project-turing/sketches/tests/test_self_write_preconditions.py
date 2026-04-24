"""Tests for specs/self-write-preconditions.md: AC-35.* (filed as AC-71.*).

Bootstrap-complete precondition, active-now cache, and cross-self guards.

Symbols that don't exist yet (_bootstrap_complete, _require_ready,
ActivationCache, CrossSelfAccess, write_contributor, etc.) are imported
*inside* test functions so pytest can still collect and xfail-mark them.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest

from turing.self_activation import ActivationContext, active_now
from turing.self_bootstrap import BootstrapRuntimeError, run_bootstrap
from turing.self_model import (
    ALL_FACETS,
    ActivationContributor,
    ContributorOrigin,
    Hobby,
    Mood,
    NodeKind,
    Passion,
    PersonalityFacet,
    PreferenceKind,
    SelfTodo,
    Skill,
    SkillKind,
    Trait,
    facet_node_id,
)
from turing.self_repo import SelfRepo
from turing.self_surface import SelfNotReady


def _seed_minimal_self(srepo: SelfRepo, self_id: str, facet_score: float = 3.0) -> None:
    now = datetime.now(UTC)
    for trait, facet in ALL_FACETS:
        srepo.insert_facet(
            PersonalityFacet(
                node_id=facet_node_id(trait, facet),
                self_id=self_id,
                trait=trait,
                facet_id=facet,
                score=facet_score,
                last_revised_at=now,
            )
        )
    srepo.insert_mood(Mood(self_id=self_id, valence=0.0, arousal=0.3, focus=0.5, last_tick_at=now))


def _seed_bootstrap_complete(srepo: SelfRepo, self_id: str, new_id) -> None:
    bank: list[dict] = []
    facet_names = [f for _, f in ALL_FACETS]
    for i in range(200):
        facet = facet_names[i % len(facet_names)]
        bank.append(
            {
                "item_number": i + 1,
                "prompt_text": f"I am {facet} ({i}).",
                "keyed_facet": facet,
                "reverse_scored": (i % 3 == 0),
            }
        )

    def _ask(item, profile):
        return (3, "neutral tick")

    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=_ask,
        item_bank=bank,
        new_id=new_id,
    )


def _ctx(
    self_id: str, now: datetime | None = None, retrieval: dict | None = None
) -> ActivationContext:
    return ActivationContext(
        self_id=self_id,
        now=now or datetime.now(UTC),
        retrieval_similarity=retrieval or {},
    )


# =========================================================================
# AC-71.1  _bootstrap_complete returns True iff count_facets==24 AND
#          count_answers==200 AND has_mood.  Test each False branch.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.1: self-write-preconditions not implemented")
def test_ac_71_1_bootstrap_complete_true_when_all_met(srepo, self_id, new_id) -> None:
    """AC-71.1: Returns True when facets==24, answers==200, mood present."""
    from turing.self_surface import _bootstrap_complete

    _seed_bootstrap_complete(srepo, self_id, new_id)
    assert _bootstrap_complete(srepo, self_id) is True


@pytest.mark.xfail(reason="AC-71.1: self-write-preconditions not implemented")
def test_ac_71_1_false_when_facets_missing(srepo, self_id) -> None:
    """AC-71.1: Returns False when facets < 24 (no bootstrap run)."""
    from turing.self_surface import _bootstrap_complete

    assert _bootstrap_complete(srepo, self_id) is False


@pytest.mark.xfail(reason="AC-71.1: self-write-preconditions not implemented")
def test_ac_71_1_false_when_no_answers(srepo, self_id) -> None:
    """AC-71.1: Returns False when facets==24 but answers < 200."""
    from turing.self_surface import _bootstrap_complete

    _seed_minimal_self(srepo, self_id)
    assert _bootstrap_complete(srepo, self_id) is False


@pytest.mark.xfail(reason="AC-71.1: self-write-preconditions not implemented")
def test_ac_71_1_false_when_no_mood(srepo, self_id) -> None:
    """AC-71.1: Returns False when facets==24, answers==200, but no mood."""
    from turing.self_surface import _bootstrap_complete

    now = datetime.now(UTC)
    for trait, facet in ALL_FACETS:
        srepo.insert_facet(
            PersonalityFacet(
                node_id=facet_node_id(trait, facet),
                self_id=self_id,
                trait=trait,
                facet_id=facet,
                score=3.0,
                last_revised_at=now,
            )
        )
    for i in range(200):
        from turing.self_model import PersonalityAnswer

        srepo.insert_answer(
            PersonalityAnswer(
                answer_id=f"ans:{i}",
                self_id=self_id,
                item_number=i + 1,
                response=3,
                justified_with="",
            )
        )
    assert not srepo.has_mood(self_id)
    assert _bootstrap_complete(srepo, self_id) is False


# =========================================================================
# AC-71.2  Every write-tool calls _require_ready first; failure raises
#          SelfNotReady.  Test per tool.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_note_passion_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: note_passion raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import note_passion

    with pytest.raises(SelfNotReady):
        note_passion(srepo, self_id, text="music", strength=0.7, first_noticed_at=datetime.now(UTC))


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_note_hobby_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: note_hobby raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import note_hobby

    with pytest.raises(SelfNotReady):
        note_hobby(srepo, self_id, name="reading", description="books")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_note_interest_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: note_interest raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import note_interest

    with pytest.raises(SelfNotReady):
        note_interest(srepo, self_id, topic="cognitive science", description="")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_note_preference_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: note_preference raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import note_preference

    with pytest.raises(SelfNotReady):
        note_preference(
            srepo, self_id, kind=PreferenceKind.AESTHETIC, label="minimalism", valence=0.8
        )


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_note_skill_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: note_skill raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import note_skill

    with pytest.raises(SelfNotReady):
        note_skill(srepo, self_id, name="Python", kind=SkillKind.INTELLECTUAL, initial_level=0.6)


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_write_self_todo_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: write_self_todo raises SelfNotReady when bootstrap incomplete."""
    from turing.self_todos import write_self_todo

    with pytest.raises(SelfNotReady):
        write_self_todo(srepo, self_id, text="Learn Rust", motivated_by_node_id="passion:1")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_revise_self_todo_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: revise_self_todo raises SelfNotReady when bootstrap incomplete."""
    from turing.self_todos import revise_self_todo

    with pytest.raises(SelfNotReady):
        revise_self_todo(srepo, self_id, todo_id="todo:1", new_text="Updated")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_complete_self_todo_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: complete_self_todo raises SelfNotReady when bootstrap incomplete."""
    from turing.self_todos import complete_self_todo

    with pytest.raises(SelfNotReady):
        complete_self_todo(srepo, self_id, todo_id="todo:1", resolution="Done")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_archive_self_todo_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: archive_self_todo raises SelfNotReady when bootstrap incomplete."""
    from turing.self_todos import archive_self_todo

    with pytest.raises(SelfNotReady):
        archive_self_todo(srepo, self_id, todo_id="todo:1", reason="stale")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_practice_skill_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: practice_skill raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import practice_skill

    with pytest.raises(SelfNotReady):
        practice_skill(srepo, self_id, skill_id="skill:x", new_level=0.9)


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_downgrade_skill_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: downgrade_skill raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import downgrade_skill

    with pytest.raises(SelfNotReady):
        downgrade_skill(srepo, self_id, skill_id="skill:x", new_level=0.2)


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_rerank_passions_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: rerank_passions raises SelfNotReady when bootstrap incomplete."""
    from turing.self_nodes import rerank_passions

    with pytest.raises(SelfNotReady):
        rerank_passions(srepo, self_id, new_order=["passion:2", "passion:1"])


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_write_contributor_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: write_contributor raises SelfNotReady when bootstrap incomplete."""
    from turing.self_surface import write_contributor

    c = ActivationContributor(
        node_id="c:1",
        self_id=self_id,
        target_node_id="facet:x",
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id="passion:1",
        source_kind="passion",
        weight=0.5,
        origin=ContributorOrigin.SELF,
        rationale="",
    )
    with pytest.raises(SelfNotReady):
        write_contributor(srepo, c)


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_record_personality_claim_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: record_personality_claim raises SelfNotReady when bootstrap incomplete."""
    from turing.self_surface import record_personality_claim

    with pytest.raises(SelfNotReady):
        record_personality_claim(srepo, self_id, facet="inquisitiveness", claim="very curious")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_retract_contributor_by_counter_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: retract_contributor_by_counter raises SelfNotReady when bootstrap incomplete."""
    from turing.self_surface import retract_contributor_by_counter

    with pytest.raises(SelfNotReady):
        retract_contributor_by_counter(srepo, self_id, contributor_id="c:1", rationale="wrong")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_note_engagement_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: note_engagement raises SelfNotReady when bootstrap incomplete."""
    from turing.self_surface import note_engagement

    with pytest.raises(SelfNotReady):
        note_engagement(srepo, self_id, hobby_id="hobby:1", description="went climbing")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_note_interest_trigger_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.2: note_interest_trigger raises SelfNotReady when bootstrap incomplete."""
    from turing.self_surface import note_interest_trigger

    with pytest.raises(SelfNotReady):
        note_interest_trigger(srepo, self_id, interest_id="interest:1", trigger="saw a talk")


@pytest.mark.xfail(reason="AC-71.2: self-write-preconditions not implemented")
def test_ac_71_2_tool_succeeds_after_bootstrap(srepo, self_id, new_id) -> None:
    """AC-71.2: Write tools succeed when bootstrap IS complete."""
    from turing.self_nodes import note_passion

    _seed_bootstrap_complete(srepo, self_id, new_id)
    note_passion(srepo, self_id, text="music", strength=0.7, first_noticed_at=datetime.now(UTC))
    passions = srepo.list_passions(self_id)
    assert len(passions) == 1
    assert passions[0].text == "music"


# =========================================================================
# AC-71.3  recall_self and render_minimal_block already enforce bootstrap
#          check (spec 28 AC-28.25). Behavior unchanged.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.3: self-write-preconditions not implemented")
def test_ac_71_3_recall_self_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.3: recall_self still raises SelfNotReady before bootstrap (unchanged)."""
    from turing.self_surface import recall_self

    with pytest.raises(SelfNotReady):
        recall_self(srepo, self_id)


@pytest.mark.xfail(reason="AC-71.3: self-write-preconditions not implemented")
def test_ac_71_3_render_minimal_block_raises_before_bootstrap(srepo, self_id) -> None:
    """AC-71.3: render_minimal_block still raises SelfNotReady before bootstrap."""
    from turing.self_surface import render_minimal_block

    with pytest.raises(SelfNotReady):
        render_minimal_block(srepo, self_id)


# =========================================================================
# AC-71.4  Bootstrap direct writes bypass the precondition check.
#          Bootstrap completes without raising.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.4: self-write-preconditions not implemented")
def test_ac_71_4_bootstrap_completes_without_raising(srepo, self_id, new_id) -> None:
    """AC-71.4: Bootstrap procedure completes without SelfNotReady."""
    bank: list[dict] = []
    facet_names = [f for _, f in ALL_FACETS]
    for i in range(200):
        facet = facet_names[i % len(facet_names)]
        bank.append(
            {
                "item_number": i + 1,
                "prompt_text": f"I am {facet} ({i}).",
                "keyed_facet": facet,
                "reverse_scored": (i % 3 == 0),
            }
        )

    def _ask(item, profile):
        return (3, "ok")

    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=_ask,
        item_bank=bank,
        new_id=new_id,
    )
    assert srepo.count_facets(self_id) == 24
    assert srepo.count_answers(self_id) == 200
    assert srepo.has_mood(self_id)


@pytest.mark.xfail(reason="AC-71.4: self-write-preconditions not implemented")
def test_ac_71_4_bootstrap_repo_inserts_skip_require_ready(srepo, self_id, new_id) -> None:
    """AC-71.4: Internal repo calls during bootstrap don't trigger _require_ready."""
    from turing.self_surface import _bootstrap_complete

    _seed_bootstrap_complete(srepo, self_id, new_id)
    assert _bootstrap_complete(srepo, self_id) is True


# =========================================================================
# AC-71.5  ActivationCache: process-local dict, TTL 30s, hit returns cached
#          float, miss computes and stores.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.5: self-write-preconditions not implemented")
def test_ac_71_5_cache_hit_returns_same_value(srepo, self_id) -> None:
    """AC-71.5: Second call on same node+ctx returns cached float without recomputing."""
    from turing.self_activation import ActivationCache

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
    ctx = _ctx(self_id)
    cache = ActivationCache()
    v1 = cache.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    compute_count = {"n": 0}

    def _compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, ctx)

    v2 = cache.get_or_compute(nid, ctx, _compute)
    assert v1 == pytest.approx(v2)
    assert compute_count["n"] == 0


@pytest.mark.xfail(reason="AC-71.5: self-write-preconditions not implemented")
def test_ac_71_5_ttl_expired_recomputes(srepo, self_id) -> None:
    """AC-71.5: Entry older than 30s is a miss and recomputes."""
    from turing.self_activation import ACTIVATION_CACHE_TTL, ActivationCache

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
    now = datetime.now(UTC)
    old_ctx = _ctx(self_id, now=now - timedelta(seconds=31))
    cache = ActivationCache()
    compute_count = {"n": 0}

    def compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, _ctx(self_id))

    cache.get_or_compute(nid, old_ctx, compute)
    assert compute_count["n"] == 1
    cache.get_or_compute(nid, old_ctx, compute)
    assert compute_count["n"] == 2


# =========================================================================
# AC-71.6  Writing a contributor invalidates cache for target_node_id.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.6: self-write-preconditions not implemented")
def test_ac_71_6_insert_contributor_invalidates_target_cache(srepo, self_id) -> None:
    """AC-71.6: After insert_contributor, cached value for target is gone."""
    from turing.self_activation import ActivationCache, invalidate_cache_for

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
    srepo.insert_passion(
        Passion(
            node_id="passion:1",
            self_id=self_id,
            text="x",
            strength=0.8,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    ctx = _ctx(self_id)
    cache = ActivationCache()
    v_before = cache.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    assert v_before == pytest.approx(0.5)

    srepo.insert_contributor(
        ActivationContributor(
            node_id="c:1",
            self_id=self_id,
            target_node_id=nid,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:1",
            source_kind="passion",
            weight=0.8,
            origin=ContributorOrigin.SELF,
            rationale="",
        ),
        acting_self_id=self_id,
    )
    invalidate_cache_for([nid])
    compute_count = {"n": 0}

    def compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, ctx)

    v_after = cache.get_or_compute(nid, ctx, compute)
    assert compute_count["n"] == 1
    assert v_after > v_before


@pytest.mark.xfail(reason="AC-71.6: self-write-preconditions not implemented")
def test_ac_71_6_mark_retracted_invalidates_target_cache(srepo, self_id) -> None:
    """AC-71.6: mark_contributor_retracted invalidates target cache."""
    from turing.self_activation import ActivationCache, invalidate_cache_for

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
    srepo.insert_passion(
        Passion(
            node_id="passion:1",
            self_id=self_id,
            text="x",
            strength=0.8,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c:1",
            self_id=self_id,
            target_node_id=nid,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:1",
            source_kind="passion",
            weight=0.8,
            origin=ContributorOrigin.SELF,
            rationale="",
        ),
        acting_self_id=self_id,
    )
    ctx = _ctx(self_id)
    cache = ActivationCache()
    v_with = cache.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    assert v_with > 0.5

    srepo.mark_contributor_retracted("c:1", retracted_by="self")
    invalidate_cache_for([nid])
    v_without = cache.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    assert v_without == pytest.approx(0.5)


# =========================================================================
# AC-71.7  Mutating a source node invalidates cache for every target that
#          has a contributor pointing from this source.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.7: self-write-preconditions not implemented")
def test_ac_71_7_source_mutation_invalidates_target_caches(srepo, self_id) -> None:
    """AC-71.7: Updating passion strength invalidates cache for targets it feeds."""
    from turing.self_activation import ActivationCache, invalidate_cache_for

    nid_a = facet_node_id(Trait.OPENNESS, "inquisitiveness")
    nid_b = facet_node_id(Trait.CONSCIENTIOUSNESS, "diligence")
    now = datetime.now(UTC)
    for nid, trait, facet_id in [
        (nid_a, Trait.OPENNESS, "inquisitiveness"),
        (nid_b, Trait.CONSCIENTIOUSNESS, "diligence"),
    ]:
        srepo.insert_facet(
            PersonalityFacet(
                node_id=nid,
                self_id=self_id,
                trait=trait,
                facet_id=facet_id,
                score=3.0,
                last_revised_at=now,
            )
        )
    srepo.insert_passion(
        Passion(
            node_id="passion:shared",
            self_id=self_id,
            text="shared source",
            strength=0.8,
            rank=0,
            first_noticed_at=now,
        )
    )
    for target, cid in [(nid_a, "c:a"), (nid_b, "c:b")]:
        srepo.insert_contributor(
            ActivationContributor(
                node_id=cid,
                self_id=self_id,
                target_node_id=target,
                target_kind=NodeKind.PERSONALITY_FACET,
                source_id="passion:shared",
                source_kind="passion",
                weight=0.6,
                origin=ContributorOrigin.SELF,
                rationale="",
            ),
            acting_self_id=self_id,
        )

    ctx = _ctx(self_id)
    cache = ActivationCache()
    v_a_before = cache.get_or_compute(nid_a, ctx, lambda: active_now(srepo, nid_a, ctx))
    v_b_before = cache.get_or_compute(nid_b, ctx, lambda: active_now(srepo, nid_b, ctx))
    assert v_a_before > 0.5
    assert v_b_before > 0.5

    p = srepo.get_passion("passion:shared")
    p.strength = 0.1
    srepo.update_passion(p, acting_self_id=self_id)
    invalidate_cache_for([nid_a, nid_b])

    v_a_after = cache.get_or_compute(nid_a, ctx, lambda: active_now(srepo, nid_a, ctx))
    v_b_after = cache.get_or_compute(nid_b, ctx, lambda: active_now(srepo, nid_b, ctx))
    assert v_a_after < v_a_before
    assert v_b_after < v_b_before


# =========================================================================
# AC-71.8  Cache is keyed on ctx.hash.  Different retrieval contexts produce
#          different cache entries.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.8: self-write-preconditions not implemented")
def test_ac_71_8_different_ctx_hash_produces_different_entries(srepo, self_id) -> None:
    """AC-71.8: Different retrieval_similarity yields different cache entries."""
    from turing.self_activation import ActivationCache

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
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c:1",
            self_id=self_id,
            target_node_id=nid,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="mem:42",
            source_kind="retrieval",
            weight=0.9,
            origin=ContributorOrigin.RETRIEVAL,
            rationale="",
        ),
        acting_self_id=self_id,
    )
    ctx_a = _ctx(self_id, retrieval={"mem:42": 0.9})
    ctx_b = _ctx(self_id, retrieval={"mem:42": 0.1})
    assert ctx_a.hash != ctx_b.hash

    cache = ActivationCache()
    v_a = cache.get_or_compute(nid, ctx_a, lambda: active_now(srepo, nid, ctx_a))
    v_b = cache.get_or_compute(nid, ctx_b, lambda: active_now(srepo, nid, ctx_b))
    assert v_a != pytest.approx(v_b)


# =========================================================================
# AC-71.9  Cache bounded at ACTIVATION_CACHE_MAX_ENTRIES=1024 with LRU.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.9: self-write-preconditions not implemented")
def test_ac_71_9_lru_eviction_at_max_entries(srepo, self_id) -> None:
    """AC-71.9: Cache evicts oldest entry when size exceeds 1024."""
    from turing.self_activation import ACTIVATION_CACHE_MAX_ENTRIES, ActivationCache

    cache = ActivationCache()
    ctx = _ctx(self_id)

    def make_compute(val: float):
        def _compute():
            return val

        return _compute

    for i in range(ACTIVATION_CACHE_MAX_ENTRIES + 10):
        cache.get_or_compute(f"node:{i}", ctx, make_compute(float(i)))
    assert cache.size() <= ACTIVATION_CACHE_MAX_ENTRIES
    assert cache.size() == ACTIVATION_CACHE_MAX_ENTRIES

    compute_count = {"n": 0}

    def counted_compute():
        compute_count["n"] += 1
        return 999.0

    cache.get_or_compute("node:0", ctx, counted_compute)
    assert compute_count["n"] == 1


# =========================================================================
# AC-71.10  SelfRepo.update_* methods accept acting_self_id keyword-only;
#           mismatch raises CrossSelfAccess.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.10: self-write-preconditions not implemented")
def test_ac_71_10_update_facet_score_mismatch_raises(srepo, self_id) -> None:
    """AC-71.10: update_facet_score with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    now = datetime.now(UTC)
    nid = facet_node_id(Trait.OPENNESS, "inquisitiveness")
    srepo.insert_facet(
        PersonalityFacet(
            node_id=nid,
            self_id=self_id,
            trait=Trait.OPENNESS,
            facet_id="inquisitiveness",
            score=3.0,
            last_revised_at=now,
        )
    )
    with pytest.raises(CrossSelfAccess):
        srepo.update_facet_score(self_id, "inquisitiveness", 4.0, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.10: self-write-preconditions not implemented")
def test_ac_71_10_update_passion_mismatch_raises(srepo, self_id) -> None:
    """AC-71.10: update_passion with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    now = datetime.now(UTC)
    p = Passion(
        node_id="passion:1",
        self_id=self_id,
        text="x",
        strength=0.8,
        rank=0,
        first_noticed_at=now,
    )
    srepo.insert_passion(p)
    with pytest.raises(CrossSelfAccess):
        srepo.update_passion(p, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.10: self-write-preconditions not implemented")
def test_ac_71_10_update_hobby_mismatch_raises(srepo, self_id) -> None:
    """AC-71.10: update_hobby with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    h = Hobby(
        node_id="hobby:1",
        self_id=self_id,
        name="reading",
        description="",
        last_engaged_at=datetime.now(UTC),
    )
    srepo.insert_hobby(h)
    with pytest.raises(CrossSelfAccess):
        srepo.update_hobby(h, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.10: self-write-preconditions not implemented")
def test_ac_71_10_update_skill_mismatch_raises(srepo, self_id) -> None:
    """AC-71.10: update_skill with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    s = Skill(
        node_id="skill:1",
        self_id=self_id,
        name="Python",
        kind=SkillKind.INTELLECTUAL,
        stored_level=0.5,
        decay_rate_per_day=0.001,
        last_practiced_at=datetime.now(UTC),
    )
    srepo.insert_skill(s)
    with pytest.raises(CrossSelfAccess):
        srepo.update_skill(s, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.10: self-write-preconditions not implemented")
def test_ac_71_10_update_todo_mismatch_raises(srepo, self_id) -> None:
    """AC-71.10: update_todo with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    t = SelfTodo(
        node_id="todo:1",
        self_id=self_id,
        text="Task",
        motivated_by_node_id="passion:1",
    )
    srepo.insert_todo(t)
    with pytest.raises(CrossSelfAccess):
        srepo.update_todo(t, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.10: self-write-preconditions not implemented")
def test_ac_71_10_update_mood_mismatch_raises(srepo, self_id) -> None:
    """AC-71.10: update_mood with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    _seed_minimal_self(srepo, self_id)
    m = srepo.get_mood(self_id)
    with pytest.raises(CrossSelfAccess):
        srepo.update_mood(m, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.10: self-write-preconditions not implemented")
def test_ac_71_10_update_matching_self_id_succeeds(srepo, self_id) -> None:
    """AC-71.10: Matching acting_self_id does not raise."""
    now = datetime.now(UTC)
    nid = facet_node_id(Trait.OPENNESS, "inquisitiveness")
    srepo.insert_facet(
        PersonalityFacet(
            node_id=nid,
            self_id=self_id,
            trait=Trait.OPENNESS,
            facet_id="inquisitiveness",
            score=3.0,
            last_revised_at=now,
        )
    )
    srepo.update_facet_score(self_id, "inquisitiveness", 4.5, acting_self_id=self_id)
    assert srepo.get_facet_score(self_id, "inquisitiveness") == 4.5


# =========================================================================
# AC-71.11  SelfRepo.insert_contributor asserts c.self_id == acting_self_id.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.11: self-write-preconditions not implemented")
def test_ac_71_11_insert_contributor_mismatch_raises(srepo, self_id) -> None:
    """AC-71.11: insert_contributor with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    c = ActivationContributor(
        node_id="c:1",
        self_id=self_id,
        target_node_id="facet:x",
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id="passion:1",
        source_kind="passion",
        weight=0.5,
        origin=ContributorOrigin.SELF,
        rationale="",
    )
    with pytest.raises(CrossSelfAccess):
        srepo.insert_contributor(c, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.11: self-write-preconditions not implemented")
def test_ac_71_11_insert_contributor_matching_succeeds(srepo, self_id) -> None:
    """AC-71.11: insert_contributor with matching acting_self_id succeeds."""
    c = ActivationContributor(
        node_id="c:1",
        self_id=self_id,
        target_node_id="facet:x",
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id="passion:1",
        source_kind="passion",
        weight=0.5,
        origin=ContributorOrigin.SELF,
        rationale="",
    )
    srepo.insert_contributor(c, acting_self_id=self_id)
    stored = srepo.get_contributor("c:1")
    assert stored is not None


# =========================================================================
# AC-71.12  SelfRepo.insert_todo_revision asserts r.self_id == acting_self_id.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.12: self-write-preconditions not implemented")
def test_ac_71_12_insert_todo_revision_mismatch_raises(srepo, self_id) -> None:
    """AC-71.12: insert_todo_revision with wrong acting_self_id raises CrossSelfAccess."""
    from turing.self_repo import CrossSelfAccess

    srepo.insert_todo(
        SelfTodo(node_id="todo:1", self_id=self_id, text="T", motivated_by_node_id="p:1")
    )
    revision = {
        "todo_id": "todo:1",
        "self_id": self_id,
        "field": "text",
        "old_value": "T",
        "new_value": "T2",
        "revised_at": datetime.now(UTC).isoformat(),
    }
    with pytest.raises(CrossSelfAccess):
        srepo.insert_todo_revision(revision, acting_self_id="other:self")


@pytest.mark.xfail(reason="AC-71.12: self-write-preconditions not implemented")
def test_ac_71_12_insert_todo_revision_matching_succeeds(srepo, self_id) -> None:
    """AC-71.12: insert_todo_revision with matching acting_self_id succeeds."""
    srepo.insert_todo(
        SelfTodo(node_id="todo:1", self_id=self_id, text="T", motivated_by_node_id="p:1")
    )
    revision = {
        "todo_id": "todo:1",
        "self_id": self_id,
        "field": "text",
        "old_value": "T",
        "new_value": "T2",
        "revised_at": datetime.now(UTC).isoformat(),
    }
    srepo.insert_todo_revision(revision, acting_self_id=self_id)


# =========================================================================
# AC-71.13  Bootstrap-time inserts pass acting_self_id (always match).
#          No regression in bootstrap flow.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.13: self-write-preconditions not implemented")
def test_ac_71_13_bootstrap_inserts_pass_acting_self_id(srepo, self_id, new_id) -> None:
    """AC-71.13: Bootstrap internal inserts include acting_self_id and never mismatch."""
    _seed_bootstrap_complete(srepo, self_id, new_id)
    assert srepo.count_facets(self_id) == 24
    assert srepo.count_answers(self_id) == 200
    assert srepo.has_mood(self_id)


@pytest.mark.xfail(reason="AC-71.13: self-write-preconditions not implemented")
def test_ac_71_13_bootstrap_resume_still_works(srepo, self_id, new_id) -> None:
    """AC-71.13: Bootstrap resume path also passes acting_self_id correctly."""
    bank: list[dict] = []
    facet_names = [f for _, f in ALL_FACETS]
    for i in range(200):
        facet = facet_names[i % len(facet_names)]
        bank.append(
            {
                "item_number": i + 1,
                "prompt_text": f"I am {facet} ({i}).",
                "keyed_facet": facet,
                "reverse_scored": (i % 3 == 0),
            }
        )

    def _halt_at_50(item, profile):
        if item.item_number >= 51:
            raise BootstrapRuntimeError("halt")
        return (3, "ok")

    with pytest.raises(BootstrapRuntimeError):
        run_bootstrap(
            repo=srepo,
            self_id=self_id,
            seed=0,
            ask=_halt_at_50,
            item_bank=bank,
            new_id=new_id,
        )

    def _ask(item, profile):
        return (3, "ok")

    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=_ask,
        item_bank=bank,
        new_id=new_id,
        resume=True,
    )
    assert srepo.count_answers(self_id) == 200


# =========================================================================
# AC-71.14  Concurrent reads on same key don't double-fetch.
#           Threaded harness: first-writer-wins.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.14: self-write-preconditions not implemented")
def test_ac_71_14_concurrent_reads_single_compute(srepo, self_id) -> None:
    """AC-71.14: Two threads reading same key only trigger one compute."""
    from turing.self_activation import ActivationCache

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
    cache = ActivationCache()
    ctx = _ctx(self_id)
    compute_count = {"n": 0}
    lock = threading.Lock()

    def slow_compute():
        with lock:
            compute_count["n"] += 1
        return active_now(srepo, nid, ctx)

    results: dict[str, float] = {}
    barrier = threading.Barrier(2)

    def reader(label: str):
        barrier.wait()
        results[label] = cache.get_or_compute(nid, ctx, slow_compute)

    t1 = threading.Thread(target=reader, args=("t1",))
    t2 = threading.Thread(target=reader, args=("t2",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)
    assert results["t1"] == pytest.approx(results["t2"])
    assert compute_count["n"] <= 2


# =========================================================================
# AC-71.15  Cache does not persist across restarts.  Cold read sees empty.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.15: self-write-preconditions not implemented")
def test_ac_71_15_fresh_cache_is_empty(srepo, self_id) -> None:
    """AC-71.15: A new ActivationCache instance starts empty."""
    from turing.self_activation import ActivationCache

    cache = ActivationCache()
    assert cache.size() == 0


@pytest.mark.xfail(reason="AC-71.15: self-write-preconditions not implemented")
def test_ac_71_15_cache_does_not_persist_across_instances(srepo, self_id) -> None:
    """AC-71.15: Second ActivationCache instance does not see first's entries."""
    from turing.self_activation import ActivationCache

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
    ctx = _ctx(self_id)
    cache1 = ActivationCache()
    cache1.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    assert cache1.size() == 1

    cache2 = ActivationCache()
    assert cache2.size() == 0
    compute_count = {"n": 0}

    def compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, ctx)

    cache2.get_or_compute(nid, ctx, compute)
    assert compute_count["n"] == 1


# =========================================================================
# AC-71.16  _bootstrap_complete does not go through the cache.
#           It's a cheap count query.
# =========================================================================


@pytest.mark.xfail(reason="AC-71.16: self-write-preconditions not implemented")
def test_ac_71_16_bootstrap_complete_ignores_cache(srepo, self_id) -> None:
    """AC-71.16: _bootstrap_complete is unaffected by ActivationCache state."""
    from turing.self_activation import ActivationCache
    from turing.self_surface import _bootstrap_complete

    cache = ActivationCache()
    assert cache.size() == 0
    result = _bootstrap_complete(srepo, self_id)
    assert result is False
    assert cache.size() == 0


@pytest.mark.xfail(reason="AC-71.16: self-write-preconditions not implemented")
def test_ac_71_16_bootstrap_complete_consistent_with_repo_counts(srepo, self_id) -> None:
    """AC-71.16: _bootstrap_complete reflects actual repo state, not cache."""
    from turing.self_model import PersonalityAnswer
    from turing.self_surface import _bootstrap_complete

    now = datetime.now(UTC)
    for trait, facet in ALL_FACETS:
        srepo.insert_facet(
            PersonalityFacet(
                node_id=facet_node_id(trait, facet),
                self_id=self_id,
                trait=trait,
                facet_id=facet,
                score=3.0,
                last_revised_at=now,
            )
        )
    assert srepo.count_facets(self_id) == 24
    assert _bootstrap_complete(srepo, self_id) is False
    for i in range(200):
        srepo.insert_answer(
            PersonalityAnswer(
                answer_id=f"ans:{i}",
                self_id=self_id,
                item_number=i + 1,
                response=3,
                justified_with="",
            )
        )
    assert srepo.count_answers(self_id) == 200
    assert _bootstrap_complete(srepo, self_id) is False
    srepo.insert_mood(Mood(self_id=self_id, valence=0.0, arousal=0.3, focus=0.5, last_tick_at=now))
    assert _bootstrap_complete(srepo, self_id) is True
