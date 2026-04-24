"""pytest-bdd step definitions for spec 69 (memory-mirroring)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pytest_bdd import given, when, then, scenarios

from turing.repo import Repo
from turing.self_repo import SelfRepo
from turing.types import MemoryTier

scenarios("features/memory_mirroring.feature")

try:
    from turing.self_memory_bridge import (
        mirror_affirmation,
        mirror_lesson,
        mirror_observation,
        mirror_opinion,
        mirror_regret,
    )
except ModuleNotFoundError:

    def _not_impl(*args, **kwargs):
        raise NotImplementedError("turing.self_memory_bridge not yet implemented")

    mirror_observation = _not_impl
    mirror_opinion = _not_impl
    mirror_affirmation = _not_impl
    mirror_lesson = _not_impl
    mirror_regret = _not_impl

_CONTENT_OK = "The self noted a recurring pattern in how it responds to ambiguity."
_INTENT_OK = "personality bootstrap"


def _content_over() -> str:
    return "x" * 1001


def _intent_over() -> str:
    return "i" * 121


@given("a repo and self_id", target_fixture="mirror_ctx")
def repo_and_self(repo: Repo, self_id: str) -> dict:
    return {"repo": repo, "self_id": self_id}


@given("a bootstrapped self with 200 answers", target_fixture="bootstrap_ctx")
def bootstrapped_200(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_bootstrap import run_bootstrap

    bank = [
        {
            "item_number": i + 1,
            "prompt_text": f"Item {i}",
            "keyed_facet": "openness",
            "reverse_scored": False,
        }
        for i in range(200)
    ]

    def _ask(item, profile):
        return (3, "ok")

    run_bootstrap(repo=srepo, self_id=self_id, seed=1, ask=_ask, item_bank=bank, new_id=new_id)
    return {"srepo": srepo, "self_id": self_id}


@given("a self with facets and a retest applied", target_fixture="retest_ctx")
def retest_applied(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_personality import apply_retest, sample_retest_items
    from turing.self_model import PersonalityItem, PersonalityFacet, ALL_FACETS, facet_node_id
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    items: list[PersonalityItem] = []
    for i in range(40):
        trait, facet = ALL_FACETS[i % len(ALL_FACETS)]
        items.append(
            PersonalityItem(
                node_id=new_id("item"),
                self_id=self_id,
                item_number=i + 1,
                prompt_text=f"I am {facet}.",
                keyed_facet=facet,
                reverse_scored=False,
            )
        )
        srepo.insert_item(items[-1])

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

    retest = sample_retest_items(srepo, self_id, count=20, seed=99)
    apply_retest(srepo, self_id, retest, [(3, "ok") for _ in retest])
    return {"srepo": srepo, "self_id": self_id, "count": len(retest)}


@given("a self with a personality claim recorded", target_fixture="claim_ctx")
def claim_recorded(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_personality import record_personality_claim

    record_personality_claim(srepo, self_id, "I am more curious than cautious.", new_id)
    return {"srepo": srepo, "self_id": self_id}


@given("a self with a hobby engagement noted", target_fixture="engage_ctx")
def engagement_noted(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_nodes import note_hobby
    from turing.self_engagement import note_engagement

    hobby = note_hobby(srepo, self_id, "Reading", "books", new_id)
    note_engagement(srepo, self_id, hobby.node_id, "Read three chapters on decision theory")
    return {"srepo": srepo, "self_id": self_id}


@given("a self with a skill practiced", target_fixture="skill_ctx")
def skill_practiced(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_nodes import note_skill, practice_skill

    note_skill(srepo, self_id, "python", "hard", new_id)
    practice_skill(srepo, self_id, "python", delta=0.1)
    return {"srepo": srepo, "self_id": self_id}


@given("a self with a contributor written", target_fixture="contrib_ctx")
def contributor_written(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_contributors import write_contributor

    write_contributor(
        srepo, self_id, kind="reinforcement", weight=0.2, origin="self", new_id=new_id
    )
    return {"srepo": srepo, "self_id": self_id}


@given("a self with a completed todo", target_fixture="todo_ctx")
def todo_completed(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_todos import add_self_todo, complete_self_todo

    todo_id = add_self_todo(srepo, self_id, "Review contributor weights", new_id)
    complete_self_todo(srepo, self_id, todo_id)
    return {"srepo": srepo, "self_id": self_id}


@given("a self with mood nudged", target_fixture="mood_ctx")
def mood_nudged(srepo: SelfRepo, self_id: str) -> dict:
    from turing.self_mood import nudge_mood
    from turing.self_model import Mood
    from datetime import UTC, datetime

    srepo.insert_mood(
        Mood(
            self_id=self_id,
            valence=0.0,
            arousal=0.3,
            focus=0.5,
            last_tick_at=datetime.now(UTC),
        )
    )
    nudge_mood(srepo, self_id, dim="valence", delta=0.2, reason="accomplishment")
    return {"srepo": srepo, "self_id": self_id}


@given("a bootstrapped self", target_fixture="full_bootstrap_ctx")
def full_bootstrap(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_bootstrap import run_bootstrap

    bank = [
        {
            "item_number": i + 1,
            "prompt_text": f"Item {i}",
            "keyed_facet": "openness",
            "reverse_scored": False,
        }
        for i in range(200)
    ]

    def _ask(item, profile):
        return (3, "ok")

    run_bootstrap(repo=srepo, self_id=self_id, seed=1, ask=_ask, item_bank=bank, new_id=new_id)
    return {"srepo": srepo, "self_id": self_id}


@given("a self with a warden-blocked write attempt", target_fixture="warden_ctx")
def warden_blocked(srepo: SelfRepo, self_id: str) -> dict:
    return {"srepo": srepo, "self_id": self_id}


@given("a repo and self_id with existing mirrored memories", target_fixture="mutate_ctx")
def existing_memories(repo: Repo, self_id: str) -> dict:
    return {"repo": repo, "self_id": self_id}


@given("a fully bootstrapped self", target_fixture="formula_ctx")
def formula_bootstrap(srepo: SelfRepo, self_id: str, new_id) -> dict:
    from turing.self_bootstrap import run_bootstrap

    bank = [
        {
            "item_number": i + 1,
            "prompt_text": f"Item {i}",
            "keyed_facet": "openness",
            "reverse_scored": False,
        }
        for i in range(200)
    ]

    def _ask(item, profile):
        return (3, "ok")

    run_bootstrap(repo=srepo, self_id=self_id, seed=1, ask=_ask, item_bank=bank, new_id=new_id)
    return {"srepo": srepo, "self_id": self_id}


@when("mirror_observation is called with valid content and intent")
def call_mirror_obs(mirror_ctx: dict) -> None:
    mid = mirror_observation(mirror_ctx["self_id"], _CONTENT_OK, _INTENT_OK)
    mem = mirror_ctx["repo"].get(mid)
    mirror_ctx["mid"] = mid
    mirror_ctx["mem"] = mem


@when("mirror_opinion is called with valid content and intent")
def call_mirror_opi(mirror_ctx: dict) -> None:
    mid = mirror_opinion(mirror_ctx["self_id"], _CONTENT_OK, _INTENT_OK)
    mem = mirror_ctx["repo"].get(mid)
    mirror_ctx["mid"] = mid
    mirror_ctx["mem"] = mem


@when("mirror_affirmation is called with valid content and intent")
def call_mirror_aff(mirror_ctx: dict) -> None:
    mid = mirror_affirmation(mirror_ctx["self_id"], _CONTENT_OK, _INTENT_OK)
    mem = mirror_ctx["repo"].get(mid)
    mirror_ctx["mid"] = mid
    mirror_ctx["mem"] = mem


@when("mirror_lesson is called with valid content and intent")
def call_mirror_les(mirror_ctx: dict) -> None:
    mid = mirror_lesson(mirror_ctx["self_id"], _CONTENT_OK, _INTENT_OK)
    mem = mirror_ctx["repo"].get(mid)
    mirror_ctx["mid"] = mid
    mirror_ctx["mem"] = mem


@when("mirror_regret is called with valid content and intent")
def call_mirror_reg(mirror_ctx: dict) -> None:
    mid = mirror_regret(mirror_ctx["self_id"], _CONTENT_OK, _INTENT_OK)
    mem = mirror_ctx["repo"].get(mid)
    mirror_ctx["mid"] = mid
    mirror_ctx["mem"] = mem


@when("mirror_observation is called with content over 1000 chars")
def call_over_content(mirror_ctx: dict) -> None:
    with pytest.raises(ValueError, match="content"):
        mirror_observation(mirror_ctx["self_id"], _content_over(), _INTENT_OK)
    mirror_ctx["passed"] = True


@when("mirror_observation is called with intent over 120 chars")
def call_over_intent(mirror_ctx: dict) -> None:
    with pytest.raises(ValueError, match="intent"):
        mirror_observation(mirror_ctx["self_id"], _CONTENT_OK, _intent_over())
    mirror_ctx["passed"] = True


@when("mirror_observation is called with content of exactly 1000 chars")
def call_exact_content(mirror_ctx: dict) -> None:
    mid = mirror_observation(mirror_ctx["self_id"], "a" * 1000, _INTENT_OK)
    mirror_ctx["mid"] = mid
    mirror_ctx["passed"] = isinstance(mid, str)


@when("mirror_observation is called with intent of exactly 120 chars")
def call_exact_intent(mirror_ctx: dict) -> None:
    mid = mirror_observation(mirror_ctx["self_id"], _CONTENT_OK, "z" * 120)
    mirror_ctx["mid"] = mid
    mirror_ctx["passed"] = isinstance(mid, str)


@when("mirror_observation is called with context None")
def call_ctx_none(mirror_ctx: dict) -> None:
    mid = mirror_observation(mirror_ctx["self_id"], _CONTENT_OK, _INTENT_OK, context=None)
    mem = mirror_ctx["repo"].get(mid)
    mirror_ctx["mem"] = mem


@when("mirror_observation is called with extra context keys")
def call_ctx_extra(mirror_ctx: dict) -> None:
    mid = mirror_observation(
        mirror_ctx["self_id"],
        _CONTENT_OK,
        _INTENT_OK,
        context={"extra_key": "extra_val"},
    )
    mem = mirror_ctx["repo"].get(mid)
    mirror_ctx["mem"] = mem


@when("mirror_observation is called with an induced failure context")
def call_induced_failure(mirror_ctx: dict) -> None:
    before = (
        mirror_ctx["repo"]
        .conn.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ?",
            (mirror_ctx["self_id"],),
        )
        .fetchone()[0]
    )
    with pytest.raises(Exception):
        mirror_observation(
            mirror_ctx["self_id"],
            _CONTENT_OK,
            _INTENT_OK,
            context={"__induce_failure__": True},
        )
    after = (
        mirror_ctx["repo"]
        .conn.execute(
            "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ?",
            (mirror_ctx["self_id"],),
        )
        .fetchone()[0]
    )
    mirror_ctx["before"] = before
    mirror_ctx["after"] = after
    mirror_ctx["passed"] = True


@when("mirror functions are called a second time")
def call_second_time(mutate_ctx: dict) -> None:
    helpers = [
        (mirror_observation, MemoryTier.OBSERVATION),
        (mirror_opinion, MemoryTier.OPINION),
        (mirror_affirmation, MemoryTier.AFFIRMATION),
        (mirror_lesson, MemoryTier.LESSON),
        (mirror_regret, MemoryTier.REGRET),
    ]
    results = []
    for fn, _tier in helpers:
        mid = fn(mutate_ctx["self_id"], _CONTENT_OK, _INTENT_OK)
        mem = mutate_ctx["repo"].get(mid)
        snap_content = mem.content
        snap_weight = mem.weight
        fn(mutate_ctx["self_id"], "second call content", _INTENT_OK)
        reloaded = mutate_ctx["repo"].get(mid)
        results.append(reloaded.content == snap_content and reloaded.weight == snap_weight)
    mutate_ctx["all_unchanged"] = all(results)


@when("all five mirror functions are called")
def call_all_five(mirror_ctx: dict) -> None:
    mids = [
        mirror_observation(mirror_ctx["self_id"], "obs", _INTENT_OK),
        mirror_opinion(mirror_ctx["self_id"], "opi", _INTENT_OK),
        mirror_affirmation(mirror_ctx["self_id"], "aff", _INTENT_OK),
        mirror_lesson(mirror_ctx["self_id"], "les", _INTENT_OK),
        mirror_regret(mirror_ctx["self_id"], "reg", _INTENT_OK),
    ]
    results = []
    for mid in mids:
        mem = mirror_ctx["repo"].get(mid)
        results.append(
            mem is not None and mem.context is not None and mem.context.get("mirror") is True
        )
    mirror_ctx["all_tagged"] = all(results)


@then("a memory_id string is returned and the memory has tier OBSERVATION")
def obs_returned(mirror_ctx: dict) -> None:
    assert isinstance(mirror_ctx["mid"], str) and len(mirror_ctx["mid"]) > 0
    assert mirror_ctx["mem"] is not None
    assert mirror_ctx["mem"].tier == MemoryTier.OBSERVATION


@then("a memory_id string is returned and the memory has tier OPINION")
def opi_returned(mirror_ctx: dict) -> None:
    assert isinstance(mirror_ctx["mid"], str) and len(mirror_ctx["mid"]) > 0
    assert mirror_ctx["mem"] is not None
    assert mirror_ctx["mem"].tier == MemoryTier.OPINION


@then("a memory_id string is returned and the memory has tier AFFIRMATION")
def aff_returned(mirror_ctx: dict) -> None:
    assert isinstance(mirror_ctx["mid"], str) and len(mirror_ctx["mid"]) > 0
    assert mirror_ctx["mem"] is not None
    assert mirror_ctx["mem"].tier == MemoryTier.AFFIRMATION


@then("a memory_id string is returned and the memory has tier LESSON")
def les_returned(mirror_ctx: dict) -> None:
    assert isinstance(mirror_ctx["mid"], str) and len(mirror_ctx["mid"]) > 0
    assert mirror_ctx["mem"] is not None
    assert mirror_ctx["mem"].tier == MemoryTier.LESSON


@then("a memory_id string is returned and the memory has tier REGRET")
def reg_returned(mirror_ctx: dict) -> None:
    assert isinstance(mirror_ctx["mid"], str) and len(mirror_ctx["mid"]) > 0
    assert mirror_ctx["mem"] is not None
    assert mirror_ctx["mem"].tier == MemoryTier.REGRET


@then('ValueError is raised matching "content"')
def val_content(mirror_ctx: dict) -> None:
    assert mirror_ctx.get("passed")


@then('ValueError is raised matching "intent"')
def val_intent(mirror_ctx: dict) -> None:
    assert mirror_ctx.get("passed")


@then("a valid memory_id string is returned")
def valid_mid(mirror_ctx: dict) -> None:
    assert mirror_ctx.get("passed")


@then("the mirrored memory context contains the self_id")
def ctx_self_id(mirror_ctx: dict) -> None:
    assert mirror_ctx["mem"] is not None
    assert mirror_ctx["mem"].context is not None
    assert mirror_ctx["mem"].context.get("self_id") == mirror_ctx["self_id"]


@then("the mirrored memory has both extra keys and self_id")
def ctx_preserved(mirror_ctx: dict) -> None:
    assert mirror_ctx["mem"].context.get("extra_key") == "extra_val"
    assert mirror_ctx["mem"].context.get("self_id") == mirror_ctx["self_id"]


@then('200 episodic memories exist with intent "personality bootstrap"')
def bootstrap_200(bootstrap_ctx: dict) -> None:
    srepo = bootstrap_ctx["srepo"]
    sid = bootstrap_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'personality bootstrap'",
        (sid,),
    ).fetchone()
    assert rows[0] == 200


@then('episodic memories exist with intent "personality retest" matching retest count')
def retest_count(retest_ctx: dict) -> None:
    srepo = retest_ctx["srepo"]
    sid = retest_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'personality retest'",
        (sid,),
    ).fetchone()
    assert rows[0] == retest_ctx["count"]


@then('an OPINION memory exists with intent "narrative personality revision"')
def claim_opinion(claim_ctx: dict) -> None:
    srepo = claim_ctx["srepo"]
    sid = claim_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'narrative personality revision'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then('an OBSERVATION memory exists with intent "engage hobby"')
def engage_obs(engage_ctx: dict) -> None:
    srepo = engage_ctx["srepo"]
    sid = engage_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'engage hobby'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then('an OBSERVATION memory exists with intent "practice skill"')
def skill_obs(skill_ctx: dict) -> None:
    srepo = skill_ctx["srepo"]
    sid = skill_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'practice skill'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then('an OBSERVATION memory exists with intent "write contributor"')
def contrib_obs(contrib_ctx: dict) -> None:
    srepo = contrib_ctx["srepo"]
    sid = contrib_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'write contributor'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then('an AFFIRMATION memory exists with intent "complete self todo"')
def todo_aff(todo_ctx: dict) -> None:
    srepo = todo_ctx["srepo"]
    sid = todo_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'complete self todo'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then('an OBSERVATION memory exists with intent "mood nudge"')
def mood_obs(mood_ctx: dict) -> None:
    srepo = mood_ctx["srepo"]
    sid = mood_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ? AND intent_at_time = 'mood nudge'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then('a LESSON memory exists with intent "self bootstrap complete"')
def finalize_lesson(full_bootstrap_ctx: dict) -> None:
    srepo = full_bootstrap_ctx["srepo"]
    sid = full_bootstrap_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'self bootstrap complete'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then('an OBSERVATION memory exists mentioning "warden blocked self write"')
def warden_obs(warden_ctx: dict) -> None:
    srepo = warden_ctx["srepo"]
    sid = warden_ctx["self_id"]
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND content LIKE '%warden blocked self write%'",
        (sid,),
    ).fetchone()
    assert rows[0] >= 1


@then("an exception is raised and no new memories exist")
def atomic_rollback(mirror_ctx: dict) -> None:
    assert mirror_ctx["after"] == mirror_ctx["before"]


@then("the original memories remain unchanged in content and weight")
def never_mutates(mutate_ctx: dict) -> None:
    assert mutate_ctx["all_unchanged"]


@then("every resulting memory has context.mirror == True")
def mirror_tag(mirror_ctx: dict) -> None:
    assert mirror_ctx["all_tagged"]


@then("mirrored memory count is at least 201")
def formula(formula_ctx: dict) -> None:
    srepo = formula_ctx["srepo"]
    sid = formula_ctx["self_id"]
    mirrored = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND json_extract(context, '$.mirror') = 1",
        (sid,),
    ).fetchone()[0]
    assert mirrored >= 200 + 1
