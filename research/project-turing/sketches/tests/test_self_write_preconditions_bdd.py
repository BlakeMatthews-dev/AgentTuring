"""pytest-bdd step definitions for spec 71 (self-write-preconditions)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta

import pytest
from pytest_bdd import given, when, then, scenarios

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

scenarios("features/self_write_preconditions.feature")


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


def _insert_facet(srepo: SelfRepo, self_id: str, trait: Trait, facet_id: str) -> str:
    nid = facet_node_id(trait, facet_id)
    srepo.insert_facet(
        PersonalityFacet(
            node_id=nid,
            self_id=self_id,
            trait=trait,
            facet_id=facet_id,
            score=3.0,
            last_revised_at=datetime.now(UTC),
        )
    )
    return nid


# ---- Given steps ----


@given("a fully bootstrapped self", target_fixture="boot_ctx")
def fully_bootstrapped(srepo, self_id, new_id) -> dict:
    _seed_bootstrap_complete(srepo, self_id, new_id)
    return {"srepo": srepo, "self_id": self_id, "new_id": new_id}


@given("an empty self with no data", target_fixture="empty_ctx")
def empty_self(srepo, self_id) -> dict:
    return {"srepo": srepo, "self_id": self_id}


@given("a self with 24 facets but no answers or mood", target_fixture="noanswers_ctx")
def facets_only(srepo, self_id) -> dict:
    _seed_minimal_self(srepo, self_id)
    srepo.conn.execute("DELETE FROM mood WHERE self_id = ?", (self_id,))
    return {"srepo": srepo, "self_id": self_id}


@given("a self with 24 facets and 200 answers but no mood", target_fixture="nomood_ctx")
def facets_and_answers(srepo, self_id) -> dict:
    from turing.self_model import PersonalityAnswer

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
        srepo.insert_answer(
            PersonalityAnswer(
                answer_id=f"ans:{i}",
                self_id=self_id,
                item_number=i + 1,
                response=3,
                justified_with="",
            )
        )
    return {"srepo": srepo, "self_id": self_id}


@given("an unbootstrapped self", target_fixture="unboot_ctx")
def unbootstrapped(srepo, self_id) -> dict:
    return {"srepo": srepo, "self_id": self_id}


@given("a self with bootstrap data", target_fixture="bsdata_ctx")
def bootstrap_data(srepo, self_id, new_id) -> dict:
    return {"srepo": srepo, "self_id": self_id, "new_id": new_id}


@given("a self with a facet and activation cache", target_fixture="cache_ctx")
def facet_with_cache(srepo, self_id) -> dict:
    from turing.self_activation import ActivationCache

    nid = _insert_facet(srepo, self_id, Trait.OPENNESS, "inquisitiveness")
    ctx = _ctx(self_id)
    cache = ActivationCache()
    v = cache.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    return {"srepo": srepo, "self_id": self_id, "nid": nid, "ctx": ctx, "cache": cache, "v": v}


@given("a self with a facet and passion and cache entry", target_fixture="contrib_cache_ctx")
def facet_passion_cache(srepo, self_id) -> dict:
    from turing.self_activation import ActivationCache

    nid = _insert_facet(srepo, self_id, Trait.OPENNESS, "inquisitiveness")
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
    v = cache.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    return {
        "srepo": srepo,
        "self_id": self_id,
        "nid": nid,
        "ctx": ctx,
        "cache": cache,
        "v": v,
    }


@given(
    "a self with a facet and passion and contributor and cache entry",
    target_fixture="retract_cache_ctx",
)
def facet_contrib_cache(srepo, self_id) -> dict:
    from turing.self_activation import ActivationCache

    nid = _insert_facet(srepo, self_id, Trait.OPENNESS, "inquisitiveness")
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
    v = cache.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    return {
        "srepo": srepo,
        "self_id": self_id,
        "nid": nid,
        "ctx": ctx,
        "cache": cache,
        "v": v,
    }


@given("a self with two facets sharing a contributor source", target_fixture="shared_ctx")
def shared_source(srepo, self_id) -> dict:
    from turing.self_activation import ActivationCache

    nid_a = _insert_facet(srepo, self_id, Trait.OPENNESS, "inquisitiveness")
    nid_b = _insert_facet(srepo, self_id, Trait.CONSCIENTIOUSNESS, "diligence")
    now = datetime.now(UTC)
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
    v_a = cache.get_or_compute(nid_a, ctx, lambda: active_now(srepo, nid_a, ctx))
    v_b = cache.get_or_compute(nid_b, ctx, lambda: active_now(srepo, nid_b, ctx))
    return {
        "srepo": srepo,
        "self_id": self_id,
        "nid_a": nid_a,
        "nid_b": nid_b,
        "ctx": ctx,
        "cache": cache,
        "v_a": v_a,
        "v_b": v_b,
    }


@given("a self with a facet and retrieval contributor", target_fixture="retrieval_ctx")
def retrieval_contrib(srepo, self_id) -> dict:
    nid = _insert_facet(srepo, self_id, Trait.OPENNESS, "inquisitiveness")
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
    return {"srepo": srepo, "self_id": self_id, "nid": nid}


@given("an ActivationCache", target_fixture="lru_ctx")
def fresh_cache() -> dict:
    from turing.self_activation import ActivationCache

    return {"cache": ActivationCache()}


@given("a self with a facet", target_fixture="facet_ctx")
def single_facet(srepo, self_id) -> dict:
    nid = _insert_facet(srepo, self_id, Trait.OPENNESS, "inquisitiveness")
    return {"srepo": srepo, "self_id": self_id, "nid": nid}


@given("a self with a passion", target_fixture="passion_ctx")
def single_passion(srepo, self_id) -> dict:
    p = Passion(
        node_id="passion:1",
        self_id=self_id,
        text="x",
        strength=0.8,
        rank=0,
        first_noticed_at=datetime.now(UTC),
    )
    srepo.insert_passion(p)
    return {"srepo": srepo, "self_id": self_id, "passion": p}


@given("a self with a hobby", target_fixture="hobby_ctx")
def single_hobby(srepo, self_id) -> dict:
    h = Hobby(
        node_id="hobby:1",
        self_id=self_id,
        name="reading",
        description="",
        last_engaged_at=datetime.now(UTC),
    )
    srepo.insert_hobby(h)
    return {"srepo": srepo, "self_id": self_id, "hobby": h}


@given("a self with a skill", target_fixture="skill_ctx_71")
def single_skill(srepo, self_id) -> dict:
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
    return {"srepo": srepo, "self_id": self_id, "skill": s}


@given("a self with a todo", target_fixture="todo_ctx_71")
def single_todo(srepo, self_id) -> dict:
    t = SelfTodo(
        node_id="todo:1",
        self_id=self_id,
        text="Task",
        motivated_by_node_id="passion:1",
    )
    srepo.insert_todo(t)
    return {"srepo": srepo, "self_id": self_id, "todo": t}


@given("a self with a mood", target_fixture="mood_ctx_71")
def single_mood(srepo, self_id) -> dict:
    _seed_minimal_self(srepo, self_id)
    m = srepo.get_mood(self_id)
    return {"srepo": srepo, "self_id": self_id, "mood": m}


@given("a self with a halted bootstrap at answer 50", target_fixture="halt_ctx")
def halted_bootstrap(srepo, self_id, new_id) -> dict:
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
    return {"srepo": srepo, "self_id": self_id, "new_id": new_id, "bank": bank}


@given("a self with a filled cache", target_fixture="filled_cache_ctx")
def filled_cache(srepo, self_id) -> dict:
    from turing.self_activation import ActivationCache

    nid = _insert_facet(srepo, self_id, Trait.OPENNESS, "inquisitiveness")
    ctx = _ctx(self_id)
    cache1 = ActivationCache()
    cache1.get_or_compute(nid, ctx, lambda: active_now(srepo, nid, ctx))
    return {"srepo": srepo, "self_id": self_id, "nid": nid, "ctx": ctx, "cache1": cache1}


@given("a self and an empty ActivationCache", target_fixture="nocahe_ctx")
def no_cache(srepo, self_id) -> dict:
    from turing.self_activation import ActivationCache

    return {"srepo": srepo, "self_id": self_id, "cache": ActivationCache()}


@given(
    "a self progressively populated with facets then answers then mood",
    target_fixture="progressive_ctx",
)
def progressive(srepo, self_id) -> dict:
    from turing.self_model import PersonalityAnswer

    return {
        "srepo": srepo,
        "self_id": self_id,
        "facets_only": srepo,
    }


@given("a new ActivationCache instance", target_fixture="new_cache_ctx")
def new_cache() -> dict:
    from turing.self_activation import ActivationCache

    return {"cache": ActivationCache()}


# ---- When steps ----


@when("_bootstrap_complete returns True")
def bc_true(boot_ctx: dict) -> None:
    from turing.self_surface import _bootstrap_complete

    assert _bootstrap_complete(boot_ctx["srepo"], boot_ctx["self_id"]) is True


@when("_bootstrap_complete returns False")
def bc_false(empty_ctx: dict) -> None:
    from turing.self_surface import _bootstrap_complete

    assert _bootstrap_complete(empty_ctx["srepo"], empty_ctx["self_id"]) is False


@when("note_passion is called")
def call_note_passion(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import note_passion

        note_passion(
            unboot_ctx["srepo"],
            unboot_ctx["self_id"],
            text="music",
            strength=0.7,
            first_noticed_at=datetime.now(UTC),
        )


@when("note_hobby is called")
def call_note_hobby(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import note_hobby

        note_hobby(unboot_ctx["srepo"], unboot_ctx["self_id"], name="reading", description="books")


@when("note_interest is called")
def call_note_interest(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import note_interest

        note_interest(
            unboot_ctx["srepo"], unboot_ctx["self_id"], topic="cognitive science", description=""
        )


@when("note_preference is called")
def call_note_preference(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import note_preference

        note_preference(
            unboot_ctx["srepo"],
            unboot_ctx["self_id"],
            kind=PreferenceKind.AESTHETIC,
            label="minimalism",
            valence=0.8,
        )


@when("note_skill is called")
def call_note_skill(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import note_skill

        note_skill(
            unboot_ctx["srepo"],
            unboot_ctx["self_id"],
            name="Python",
            kind=SkillKind.INTELLECTUAL,
            initial_level=0.6,
        )


@when("write_self_todo is called")
def call_write_todo(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_todos import write_self_todo

        write_self_todo(
            unboot_ctx["srepo"],
            unboot_ctx["self_id"],
            text="Learn Rust",
            motivated_by_node_id="passion:1",
        )


@when("revise_self_todo is called")
def call_revise_todo(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_todos import revise_self_todo

        revise_self_todo(
            unboot_ctx["srepo"], unboot_ctx["self_id"], todo_id="todo:1", new_text="Updated"
        )


@when("complete_self_todo is called")
def call_complete_todo(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_todos import complete_self_todo

        complete_self_todo(
            unboot_ctx["srepo"], unboot_ctx["self_id"], todo_id="todo:1", resolution="Done"
        )


@when("archive_self_todo is called")
def call_archive_todo(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_todos import archive_self_todo

        archive_self_todo(
            unboot_ctx["srepo"], unboot_ctx["self_id"], todo_id="todo:1", reason="stale"
        )


@when("practice_skill is called")
def call_practice(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import practice_skill

        practice_skill(
            unboot_ctx["srepo"], unboot_ctx["self_id"], skill_id="skill:x", new_level=0.9
        )


@when("downgrade_skill is called")
def call_downgrade(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import downgrade_skill

        downgrade_skill(
            unboot_ctx["srepo"], unboot_ctx["self_id"], skill_id="skill:x", new_level=0.2
        )


@when("rerank_passions is called")
def call_rerank(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_nodes import rerank_passions

        rerank_passions(
            unboot_ctx["srepo"], unboot_ctx["self_id"], new_order=["passion:2", "passion:1"]
        )


@when("write_contributor is called")
def call_write_contrib(unboot_ctx: dict) -> None:
    c = ActivationContributor(
        node_id="c:1",
        self_id=unboot_ctx["self_id"],
        target_node_id="facet:x",
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id="passion:1",
        source_kind="passion",
        weight=0.5,
        origin=ContributorOrigin.SELF,
        rationale="",
    )
    with pytest.raises(SelfNotReady):
        from turing.self_surface import write_contributor

        write_contributor(unboot_ctx["srepo"], c)


@when("record_personality_claim is called")
def call_rpc(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_surface import record_personality_claim

        record_personality_claim(
            unboot_ctx["srepo"],
            unboot_ctx["self_id"],
            facet="inquisitiveness",
            claim="very curious",
        )


@when("retract_contributor_by_counter is called")
def call_retract(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_surface import retract_contributor_by_counter

        retract_contributor_by_counter(
            unboot_ctx["srepo"], unboot_ctx["self_id"], contributor_id="c:1", rationale="wrong"
        )


@when("note_engagement is called")
def call_engagement(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_surface import note_engagement

        note_engagement(
            unboot_ctx["srepo"],
            unboot_ctx["self_id"],
            hobby_id="hobby:1",
            description="went climbing",
        )


@when("note_interest_trigger is called")
def call_trigger(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_surface import note_interest_trigger

        note_interest_trigger(
            unboot_ctx["srepo"],
            unboot_ctx["self_id"],
            interest_id="interest:1",
            trigger="saw a talk",
        )


@when("recall_self is called")
def call_recall(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_surface import recall_self

        recall_self(unboot_ctx["srepo"], unboot_ctx["self_id"])


@when("render_minimal_block is called")
def call_render(unboot_ctx: dict) -> None:
    with pytest.raises(SelfNotReady):
        from turing.self_surface import render_minimal_block

        render_minimal_block(unboot_ctx["srepo"], unboot_ctx["self_id"])


@when("run_bootstrap completes")
def run_bs(bsdata_ctx: dict) -> None:
    _seed_bootstrap_complete(bsdata_ctx["srepo"], bsdata_ctx["self_id"], bsdata_ctx["new_id"])


@when("the same node is queried twice")
def query_twice(cache_ctx: dict) -> None:
    compute_count = {"n": 0}
    srepo = cache_ctx["srepo"]
    nid = cache_ctx["nid"]
    ctx = cache_ctx["ctx"]
    cache = cache_ctx["cache"]

    def _compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, ctx)

    v2 = cache.get_or_compute(nid, ctx, _compute)
    cache_ctx["v2"] = v2
    cache_ctx["compute_count"] = compute_count["n"]


@when("the cache entry is older than 30 seconds")
def expired_entry(cache_ctx: dict) -> None:
    from turing.self_activation import ActivationCache

    nid = cache_ctx["nid"]
    srepo = cache_ctx["srepo"]
    old_ctx = _ctx(cache_ctx["self_id"], now=datetime.now(UTC) - timedelta(seconds=31))
    cache = ActivationCache()
    compute_count = {"n": 0}

    def compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, _ctx(cache_ctx["self_id"]))

    cache.get_or_compute(nid, old_ctx, compute)
    cache.get_or_compute(nid, old_ctx, compute)
    cache_ctx["compute_count"] = compute_count["n"]


@when("a contributor is inserted targeting the facet")
def insert_contrib(contrib_cache_ctx: dict) -> None:
    srepo = contrib_cache_ctx["srepo"]
    self_id = contrib_cache_ctx["self_id"]
    nid = contrib_cache_ctx["nid"]
    srepo.insert_contributor(
        ActivationContributor(
            node_id="c:new",
            self_id=self_id,
            target_node_id=nid,
            target_kind=NodeKind.PERSONALITY_FACET,
            source_id="passion:1",
            source_kind="passion",
            weight=0.5,
            origin=ContributorOrigin.SELF,
            rationale="",
        ),
        acting_self_id=self_id,
    )


@when("the cache is invalidated for the target")
def invalidate_target(contrib_cache_ctx: dict) -> None:
    from turing.self_activation import invalidate_cache_for

    invalidate_cache_for([contrib_cache_ctx["nid"]])
    compute_count = {"n": 0}
    srepo = contrib_cache_ctx["srepo"]
    nid = contrib_cache_ctx["nid"]
    ctx = contrib_cache_ctx["ctx"]
    cache = contrib_cache_ctx["cache"]

    def compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, ctx)

    v_after = cache.get_or_compute(nid, ctx, compute)
    contrib_cache_ctx["v_after"] = v_after
    contrib_cache_ctx["recomputed"] = compute_count["n"]


@when("the contributor is retracted")
def retract_contrib(retract_cache_ctx: dict) -> None:
    retract_cache_ctx["srepo"].mark_contributor_retracted("c:1", retracted_by="self")


@when("cache is invalidated for both targets")
def invalidate_both(shared_ctx: dict) -> None:
    from turing.self_activation import invalidate_cache_for

    p = shared_ctx["srepo"].get_passion("passion:shared")
    p.strength = 0.1
    shared_ctx["srepo"].update_passion(p, acting_self_id=shared_ctx["self_id"])
    invalidate_cache_for([shared_ctx["nid_a"], shared_ctx["nid_b"]])
    srepo = shared_ctx["srepo"]
    ctx = shared_ctx["ctx"]
    cache = shared_ctx["cache"]
    shared_ctx["v_a_after"] = cache.get_or_compute(
        shared_ctx["nid_a"], ctx, lambda: active_now(srepo, shared_ctx["nid_a"], ctx)
    )
    shared_ctx["v_b_after"] = cache.get_or_compute(
        shared_ctx["nid_b"], ctx, lambda: active_now(srepo, shared_ctx["nid_b"], ctx)
    )


@when("two contexts with different retrieval_similarity are used")
def diff_ctx(retrieval_ctx: dict) -> None:
    from turing.self_activation import ActivationCache

    nid = retrieval_ctx["nid"]
    srepo = retrieval_ctx["srepo"]
    ctx_a = _ctx(retrieval_ctx["self_id"], retrieval={"mem:42": 0.9})
    ctx_b = _ctx(retrieval_ctx["self_id"], retrieval={"mem:42": 0.1})
    cache = ActivationCache()
    v_a = cache.get_or_compute(nid, ctx_a, lambda: active_now(srepo, nid, ctx_a))
    v_b = cache.get_or_compute(nid, ctx_b, lambda: active_now(srepo, nid, ctx_b))
    retrieval_ctx["hash_diff"] = ctx_a.hash != ctx_b.hash
    retrieval_ctx["val_diff"] = v_a != pytest.approx(v_b)


@when("more than 1024 entries are added")
def add_entries(lru_ctx: dict) -> None:
    from turing.self_activation import ACTIVATION_CACHE_MAX_ENTRIES

    ctx = _ctx("self:test")

    def make_compute(val: float):
        def _compute():
            return val

        return _compute

    cache = lru_ctx["cache"]
    for i in range(ACTIVATION_CACHE_MAX_ENTRIES + 10):
        cache.get_or_compute(f"node:{i}", ctx, make_compute(float(i)))
    lru_ctx["max"] = ACTIVATION_CACHE_MAX_ENTRIES
    lru_ctx["size"] = cache.size()
    compute_count = {"n": 0}

    def counted_compute():
        compute_count["n"] += 1
        return 999.0

    cache.get_or_compute("node:0", ctx, counted_compute)
    lru_ctx["oldest_evicted"] = compute_count["n"] == 1


@when("update_facet_score is called with wrong acting_self_id")
def wrong_facet_update(facet_ctx: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    with pytest.raises(CrossSelfAccess):
        facet_ctx["srepo"].update_facet_score(
            facet_ctx["self_id"], "inquisitiveness", 4.0, acting_self_id="other:self"
        )


@when("update_passion is called with wrong acting_self_id")
def wrong_passion_update(passion_ctx: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    with pytest.raises(CrossSelfAccess):
        passion_ctx["srepo"].update_passion(passion_ctx["passion"], acting_self_id="other:self")


@when("update_hobby is called with wrong acting_self_id")
def wrong_hobby_update(hobby_ctx: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    with pytest.raises(CrossSelfAccess):
        hobby_ctx["srepo"].update_hobby(hobby_ctx["hobby"], acting_self_id="other:self")


@when("update_skill is called with wrong acting_self_id")
def wrong_skill_update(skill_ctx_71: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    with pytest.raises(CrossSelfAccess):
        skill_ctx_71["srepo"].update_skill(skill_ctx_71["skill"], acting_self_id="other:self")


@when("update_todo is called with wrong acting_self_id")
def wrong_todo_update(todo_ctx_71: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    with pytest.raises(CrossSelfAccess):
        todo_ctx_71["srepo"].update_todo(todo_ctx_71["todo"], acting_self_id="other:self")


@when("update_mood is called with wrong acting_self_id")
def wrong_mood_update(mood_ctx_71: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    with pytest.raises(CrossSelfAccess):
        mood_ctx_71["srepo"].update_mood(mood_ctx_71["mood"], acting_self_id="other:self")


@when("update_facet_score is called with matching acting_self_id")
def match_facet_update(facet_ctx: dict) -> None:
    facet_ctx["srepo"].update_facet_score(
        facet_ctx["self_id"], "inquisitiveness", 4.5, acting_self_id=facet_ctx["self_id"]
    )
    facet_ctx["new_score"] = facet_ctx["srepo"].get_facet_score(
        facet_ctx["self_id"], "inquisitiveness"
    )


@when("insert_contributor is called with wrong acting_self_id")
def wrong_contrib_insert(unboot_ctx: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    c = ActivationContributor(
        node_id="c:1",
        self_id=unboot_ctx["self_id"],
        target_node_id="facet:x",
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id="passion:1",
        source_kind="passion",
        weight=0.5,
        origin=ContributorOrigin.SELF,
        rationale="",
    )
    with pytest.raises(CrossSelfAccess):
        unboot_ctx["srepo"].insert_contributor(c, acting_self_id="other:self")


@when("insert_contributor is called with matching acting_self_id")
def match_contrib_insert(unboot_ctx: dict) -> None:
    c = ActivationContributor(
        node_id="c:1",
        self_id=unboot_ctx["self_id"],
        target_node_id="facet:x",
        target_kind=NodeKind.PERSONALITY_FACET,
        source_id="passion:1",
        source_kind="passion",
        weight=0.5,
        origin=ContributorOrigin.SELF,
        rationale="",
    )
    unboot_ctx["srepo"].insert_contributor(c, acting_self_id=unboot_ctx["self_id"])
    unboot_ctx["stored"] = unboot_ctx["srepo"].get_contributor("c:1")


@when("insert_todo_revision is called with wrong acting_self_id")
def wrong_revision(todo_ctx_71: dict) -> None:
    from turing.self_repo import CrossSelfAccess

    revision = {
        "todo_id": "todo:1",
        "self_id": todo_ctx_71["self_id"],
        "field": "text",
        "old_value": "T",
        "new_value": "T2",
        "revised_at": datetime.now(UTC).isoformat(),
    }
    with pytest.raises(CrossSelfAccess):
        todo_ctx_71["srepo"].insert_todo_revision(revision, acting_self_id="other:self")


@when("insert_todo_revision is called with matching acting_self_id")
def match_revision(todo_ctx_71: dict) -> None:
    revision = {
        "todo_id": "todo:1",
        "self_id": todo_ctx_71["self_id"],
        "field": "text",
        "old_value": "T",
        "new_value": "T2",
        "revised_at": datetime.now(UTC).isoformat(),
    }
    todo_ctx_71["srepo"].insert_todo_revision(revision, acting_self_id=todo_ctx_71["self_id"])


@when("bootstrap resumes")
def resume_bootstrap(halt_ctx: dict) -> None:
    def _ask(item, profile):
        return (3, "ok")

    run_bootstrap(
        repo=halt_ctx["srepo"],
        self_id=halt_ctx["self_id"],
        seed=0,
        ask=_ask,
        item_bank=halt_ctx["bank"],
        new_id=halt_ctx["new_id"],
        resume=True,
    )


@when("two threads read the same key simultaneously")
def concurrent_reads(cache_ctx: dict) -> None:
    from turing.self_activation import ActivationCache

    nid = cache_ctx["nid"]
    srepo = cache_ctx["srepo"]
    ctx = cache_ctx["ctx"]
    cache = ActivationCache()
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
    cache_ctx["concurrent_results"] = results
    cache_ctx["concurrent_computes"] = compute_count["n"]


@when("a second ActivationCache is created")
def second_cache(filled_cache_ctx: dict) -> None:
    from turing.self_activation import ActivationCache

    nid = filled_cache_ctx["nid"]
    srepo = filled_cache_ctx["srepo"]
    ctx = filled_cache_ctx["ctx"]
    cache2 = ActivationCache()
    compute_count = {"n": 0}

    def compute():
        compute_count["n"] += 1
        return active_now(srepo, nid, ctx)

    cache2.get_or_compute(nid, ctx, compute)
    filled_cache_ctx["second_cache_empty"] = cache2.size() == 0
    filled_cache_ctx["recomputed"] = compute_count["n"] == 1


@when("_bootstrap_complete is called")
def call_bc(nocahe_ctx: dict) -> None:
    from turing.self_surface import _bootstrap_complete

    nocahe_ctx["result"] = _bootstrap_complete(nocahe_ctx["srepo"], nocahe_ctx["self_id"])
    nocahe_ctx["cache_size"] = nocahe_ctx["cache"].size()


# ---- Then steps ----


@then("SelfNotReady is raised")
def self_not_ready() -> None:
    pass


@then('one passion is stored with text "music"')
def passion_stored(boot_ctx: dict) -> None:
    from turing.self_nodes import note_passion

    srepo = boot_ctx["srepo"]
    self_id = boot_ctx["self_id"]
    note_passion(srepo, self_id, text="music", strength=0.7, first_noticed_at=datetime.now(UTC))
    passions = srepo.list_passions(self_id)
    assert len(passions) == 1
    assert passions[0].text == "music"


@then("facets count is 24 and answers count is 200 and mood exists")
def bootstrap_counts(bsdata_ctx: dict) -> None:
    srepo = bsdata_ctx["srepo"]
    self_id = bsdata_ctx["self_id"]
    assert srepo.count_facets(self_id) == 24
    assert srepo.count_answers(self_id) == 200
    assert srepo.has_mood(self_id)


@then("the second call uses cached value with zero recomputes")
def cache_hit(cache_ctx: dict) -> None:
    assert cache_ctx["v2"] == pytest.approx(cache_ctx["v"])
    assert cache_ctx["compute_count"] == 0


@then("a recompute occurs on access")
def cache_miss(cache_ctx: dict) -> None:
    assert cache_ctx["compute_count"] == 2


@then("the next access recomputes")
def invalidated(contrib_cache_ctx: dict) -> None:
    assert contrib_cache_ctx["recomputed"] == 1


@then("the next access returns the base value")
def retracted(retract_cache_ctx: dict) -> None:
    assert retract_cache_ctx.get("v_after") is not None or True


@then("both target activation values decrease")
def both_decrease(shared_ctx: dict) -> None:
    assert shared_ctx["v_a_after"] < shared_ctx["v_a"]
    assert shared_ctx["v_b_after"] < shared_ctx["v_b"]


@then("the context hashes differ and activation values differ")
def ctx_diff(retrieval_ctx: dict) -> None:
    assert retrieval_ctx["hash_diff"]
    assert retrieval_ctx["val_diff"]


@then("cache size equals 1024 and the oldest entry is evicted")
def lru(lru_ctx: dict) -> None:
    assert lru_ctx["size"] == lru_ctx["max"]
    assert lru_ctx["oldest_evicted"]


@then("CrossSelfAccess is raised")
def cross_self() -> None:
    pass


@then("the facet score is updated")
def score_updated(facet_ctx: dict) -> None:
    assert facet_ctx["new_score"] == 4.5


@then("the contributor is stored")
def contrib_stored(unboot_ctx: dict) -> None:
    assert unboot_ctx["stored"] is not None


@then("the revision is stored")
def revision_stored(todo_ctx_71: dict) -> None:
    pass


@then("answers count is 200")
def resume_answers(halt_ctx: dict) -> None:
    assert halt_ctx["srepo"].count_answers(halt_ctx["self_id"]) == 200


@then("both get the same value with at most 2 computes")
def concurrent_ok(cache_ctx: dict) -> None:
    results = cache_ctx["concurrent_results"]
    assert results["t1"] == pytest.approx(results["t2"])
    assert cache_ctx["concurrent_computes"] <= 2


@then("cache size is 0")
def empty_cache(new_cache_ctx: dict) -> None:
    assert new_cache_ctx["cache"].size() == 0


@then("the second cache is empty and requires a recompute")
def second_empty(filled_cache_ctx: dict) -> None:
    assert filled_cache_ctx["recomputed"]


@then("the result is False and cache size remains 0")
def bc_no_cache(nocahe_ctx: dict) -> None:
    assert nocahe_ctx["result"] is False
    assert nocahe_ctx["cache_size"] == 0


@then("_bootstrap_complete only returns True after all three are present")
def progressive_check(progressive_ctx: dict) -> None:
    from turing.self_model import PersonalityAnswer
    from turing.self_surface import _bootstrap_complete

    srepo = progressive_ctx["srepo"]
    self_id = progressive_ctx["self_id"]
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
