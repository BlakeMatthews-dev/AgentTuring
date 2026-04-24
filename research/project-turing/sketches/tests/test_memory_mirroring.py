"""Tests for specs/memory-mirroring.md: AC-32.* (spec 69, memory-mirroring bridge).

Each test is marked xfail because the `turing.self_memory_bridge` module does not
yet exist.  When the bridge is implemented these tests should flip to passing.
"""

from __future__ import annotations

import random
from uuid import uuid4

import pytest

from turing.repo import Repo
from turing.self_repo import SelfRepo
from turing.types import MemoryTier

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CONTENT_OK = "The self noted a recurring pattern in how it responds to ambiguity."
_INTENT_OK = "personality bootstrap"


def _content_over() -> str:
    return "x" * 1001


def _intent_over() -> str:
    return "i" * 121


# ---------------------------------------------------------------------------
# AC-32.1  Bridge API — five public helpers, each returns memory_id
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.1: memory-mirroring not implemented")
def test_ac_69_1_mirror_observation_returns_memory_id(repo: Repo, self_id: str) -> None:
    """AC-32.1: mirror_observation returns a created memory_id."""
    mid = mirror_observation(self_id, _CONTENT_OK, _INTENT_OK)
    assert isinstance(mid, str) and len(mid) > 0
    mem = repo.get(mid)
    assert mem is not None
    assert mem.tier == MemoryTier.OBSERVATION


@pytest.mark.xfail(reason="AC-32.1: memory-mirroring not implemented")
def test_ac_69_1_mirror_opinion_returns_memory_id(repo: Repo, self_id: str) -> None:
    """AC-32.1: mirror_opinion returns a created memory_id."""
    mid = mirror_opinion(self_id, _CONTENT_OK, _INTENT_OK)
    assert isinstance(mid, str) and len(mid) > 0
    mem = repo.get(mid)
    assert mem is not None
    assert mem.tier == MemoryTier.OPINION


@pytest.mark.xfail(reason="AC-32.1: memory-mirroring not implemented")
def test_ac_69_1_mirror_affirmation_returns_memory_id(repo: Repo, self_id: str) -> None:
    """AC-32.1: mirror_affirmation returns a created memory_id."""
    mid = mirror_affirmation(self_id, _CONTENT_OK, _INTENT_OK)
    assert isinstance(mid, str) and len(mid) > 0
    mem = repo.get(mid)
    assert mem is not None
    assert mem.tier == MemoryTier.AFFIRMATION


@pytest.mark.xfail(reason="AC-32.1: memory-mirroring not implemented")
def test_ac_69_1_mirror_lesson_returns_memory_id(repo: Repo, self_id: str) -> None:
    """AC-32.1: mirror_lesson returns a created memory_id."""
    mid = mirror_lesson(self_id, _CONTENT_OK, _INTENT_OK)
    assert isinstance(mid, str) and len(mid) > 0
    mem = repo.get(mid)
    assert mem is not None
    assert mem.tier == MemoryTier.LESSON


@pytest.mark.xfail(reason="AC-32.1: memory-mirroring not implemented")
def test_ac_69_1_mirror_regret_returns_memory_id(repo: Repo, self_id: str) -> None:
    """AC-32.1: mirror_regret returns a created memory_id."""
    mid = mirror_regret(self_id, _CONTENT_OK, _INTENT_OK)
    assert isinstance(mid, str) and len(mid) > 0
    mem = repo.get(mid)
    assert mem is not None
    assert mem.tier == MemoryTier.REGRET


# ---------------------------------------------------------------------------
# AC-32.2  Content / intent length validation
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.2: memory-mirroring not implemented")
def test_ac_69_2_over_max_content_raises(repo: Repo, self_id: str) -> None:
    """AC-32.2: content > 1000 chars raises at the bridge boundary."""
    with pytest.raises(ValueError, match="content"):
        mirror_observation(self_id, _content_over(), _INTENT_OK)


@pytest.mark.xfail(reason="AC-32.2: memory-mirroring not implemented")
def test_ac_69_2_over_max_intent_raises(repo: Repo, self_id: str) -> None:
    """AC-32.2: intent_at_time > 120 chars raises at the bridge boundary."""
    with pytest.raises(ValueError, match="intent"):
        mirror_observation(self_id, _CONTENT_OK, _intent_over())


@pytest.mark.xfail(reason="AC-32.2: memory-mirroring not implemented")
def test_ac_69_2_content_exactly_1000_succeeds(repo: Repo, self_id: str) -> None:
    """AC-32.2: content == 1000 chars is accepted without error."""
    mid = mirror_observation(self_id, "a" * 1000, _INTENT_OK)
    assert isinstance(mid, str)


@pytest.mark.xfail(reason="AC-32.2: memory-mirroring not implemented")
def test_ac_69_2_intent_exactly_120_succeeds(repo: Repo, self_id: str) -> None:
    """AC-32.2: intent_at_time == 120 chars is accepted without error."""
    mid = mirror_observation(self_id, _CONTENT_OK, "z" * 120)
    assert isinstance(mid, str)


# ---------------------------------------------------------------------------
# AC-32.3  context always includes self_id and request_hash when available
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.3: memory-mirroring not implemented")
def test_ac_69_3_context_includes_self_id(repo: Repo, self_id: str) -> None:
    """AC-32.3: mirrored memory context contains self_id even when caller omits it."""
    mid = mirror_observation(self_id, _CONTENT_OK, _INTENT_OK, context=None)
    mem = repo.get(mid)
    assert mem is not None
    assert mem.context is not None
    assert mem.context.get("self_id") == self_id


@pytest.mark.xfail(reason="AC-32.3: memory-mirroring not implemented")
def test_ac_69_3_context_preserves_caller_keys(repo: Repo, self_id: str) -> None:
    """AC-32.3: bridge merges its keys with caller-supplied context."""
    mid = mirror_observation(
        self_id,
        _CONTENT_OK,
        _INTENT_OK,
        context={"extra_key": "extra_val"},
    )
    mem = repo.get(mid)
    assert mem is not None
    assert mem.context.get("extra_key") == "extra_val"
    assert mem.context.get("self_id") == self_id


# ---------------------------------------------------------------------------
# AC-32.4  Spec 23 AC-23.9 — bootstrap answers mirror as OBSERVATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.4: memory-mirroring not implemented")
def test_ac_69_4_bootstrap_answer_mirrors_observation(
    srepo: SelfRepo, self_id: str, new_id
) -> None:
    """AC-32.4: each bootstrap answer writes an OBSERVATION via mirror_observation."""
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

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'personality bootstrap'",
        (self_id,),
    ).fetchone()
    assert rows[0] == 200


# ---------------------------------------------------------------------------
# AC-32.5  Spec 23 AC-23.17 — retest answers mirror as OBSERVATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.5: memory-mirroring not implemented")
def test_ac_69_5_retest_answer_mirrors_observation(srepo: SelfRepo, self_id: str, new_id) -> None:
    """AC-32.5: each retest answer writes an OBSERVATION via mirror_observation."""
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

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'personality retest'",
        (self_id,),
    ).fetchone()
    assert rows[0] == 20


# ---------------------------------------------------------------------------
# AC-32.6  Spec 23 AC-23.19 — record_personality_claim mirrors as OPINION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.6: memory-mirroring not implemented")
def test_ac_69_6_personality_claim_mirrors_opinion(srepo: SelfRepo, self_id: str, new_id) -> None:
    """AC-32.6: record_personality_claim writes an OPINION via mirror_opinion."""
    from turing.self_personality import record_personality_claim

    record_personality_claim(srepo, self_id, "I am more curious than cautious.", new_id)

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'narrative personality revision'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.7  Spec 24 AC-24.8 — note_engagement mirrors as OBSERVATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.7: memory-mirroring not implemented")
def test_ac_69_7_note_engagement_mirrors_observation(srepo: SelfRepo, self_id: str, new_id) -> None:
    """AC-32.7: note_engagement writes an OBSERVATION via mirror_observation."""
    from turing.self_nodes import note_hobby
    from turing.self_engagement import note_engagement

    hobby = note_hobby(srepo, self_id, "Reading", "books", new_id)
    note_engagement(srepo, self_id, hobby.node_id, "Read three chapters on decision theory")

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'engage hobby'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.8  Spec 24 AC-24.10 — practice_skill mirrors as OBSERVATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.8: memory-mirroring not implemented")
def test_ac_69_8_practice_skill_mirrors_observation(srepo: SelfRepo, self_id: str, new_id) -> None:
    """AC-32.8: practice_skill writes an OBSERVATION via mirror_observation."""
    from turing.self_nodes import note_skill, practice_skill

    note_skill(srepo, self_id, "python", "hard", new_id)
    practice_skill(srepo, self_id, "python", delta=0.1)

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'practice skill'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.9  Spec 25 AC-25.19 — write_contributor(origin=self) mirrors OBSERVATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.9: memory-mirroring not implemented")
def test_ac_69_9_write_contributor_mirrors_observation(
    srepo: SelfRepo, self_id: str, new_id
) -> None:
    """AC-32.9: write_contributor(origin=self) writes an OBSERVATION via mirror_observation."""
    from turing.self_contributors import write_contributor

    write_contributor(
        srepo, self_id, kind="reinforcement", weight=0.2, origin="self", new_id=new_id
    )

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'write contributor'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.10  Spec 26 AC-26.12 — complete_self_todo mirrors as AFFIRMATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.10: memory-mirroring not implemented")
def test_ac_69_10_complete_self_todo_mirrors_affirmation(
    srepo: SelfRepo, self_id: str, new_id
) -> None:
    """AC-32.10: complete_self_todo writes an AFFIRMATION via mirror_affirmation."""
    from turing.self_todos import add_self_todo, complete_self_todo

    todo_id = add_self_todo(srepo, self_id, "Review contributor weights", new_id)
    complete_self_todo(srepo, self_id, todo_id)

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'complete self todo'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.11  Spec 27 AC-27.9 — nudge_mood mirrors as OBSERVATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.11: memory-mirroring not implemented")
def test_ac_69_11_nudge_mood_mirrors_observation(srepo: SelfRepo, self_id: str) -> None:
    """AC-32.11: nudge_mood writes an OBSERVATION with mood context."""
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

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ? AND intent_at_time = 'mood nudge'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.12  Spec 29 AC-29.17 — bootstrap finalize mirrors as LESSON
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.12: memory-mirroring not implemented")
def test_ac_69_12_bootstrap_finalize_mirrors_lesson(srepo: SelfRepo, self_id: str, new_id) -> None:
    """AC-32.12: bootstrap finalize writes a LESSON via mirror_lesson."""
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

    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND intent_at_time = 'self bootstrap complete'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.13  Spec 36 — warden-blocked self-writes mirror as OBSERVATION
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.13: memory-mirroring not implemented")
def test_ac_69_13_warden_blocked_write_mirrors_observation(
    srepo: SelfRepo, self_id: str, new_id
) -> None:
    """AC-32.13: a warden-blocked self write creates an OBSERVATION 'warden blocked self write'."""
    rows = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND content LIKE '%warden blocked self write%'",
        (self_id,),
    ).fetchone()
    assert rows[0] >= 1


# ---------------------------------------------------------------------------
# AC-32.14  Atomicity — mirror + write succeed or both fail
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.14: memory-mirroring not implemented")
def test_ac_69_14_atomic_rollback_on_mirror_failure(repo: Repo, self_id: str) -> None:
    """AC-32.14: a mirror failure after a successful self-model write rolls back the write."""
    from turing.self_memory_bridge import mirror_observation

    before_count = repo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ?", (self_id,)
    ).fetchone()[0]

    with pytest.raises(Exception):
        mirror_observation(
            self_id,
            _CONTENT_OK,
            _INTENT_OK,
            context={"__induce_failure__": True},
        )

    after_count = repo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory WHERE self_id = ?", (self_id,)
    ).fetchone()[0]
    assert after_count == before_count


# ---------------------------------------------------------------------------
# AC-32.15  Bridge never mutates existing memories — only inserts
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.15: memory-mirroring not implemented")
def test_ac_69_15_bridge_never_mutates_existing(repo: Repo, self_id: str) -> None:
    """AC-32.15: all five helpers only insert; existing memories stay unchanged."""
    helpers = [
        (mirror_observation, MemoryTier.OBSERVATION),
        (mirror_opinion, MemoryTier.OPINION),
        (mirror_affirmation, MemoryTier.AFFIRMATION),
        (mirror_lesson, MemoryTier.LESSON),
        (mirror_regret, MemoryTier.REGRET),
    ]
    for fn, _tier in helpers:
        mid = fn(self_id, _CONTENT_OK, _INTENT_OK)
        mem = repo.get(mid)
        assert mem is not None
        snap_content = mem.content
        snap_weight = mem.weight
        fn(self_id, "second call content", _INTENT_OK)
        reloaded = repo.get(mid)
        assert reloaded is not None
        assert reloaded.content == snap_content
        assert reloaded.weight == snap_weight


# ---------------------------------------------------------------------------
# AC-32.16  Every mirrored memory tagged with context.mirror = True
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.16: memory-mirroring not implemented")
def test_ac_69_16_mirror_tag_present(repo: Repo, self_id: str) -> None:
    """AC-32.16: every mirrored memory has context.mirror == True."""
    mids = [
        mirror_observation(self_id, "obs", _INTENT_OK),
        mirror_opinion(self_id, "opi", _INTENT_OK),
        mirror_affirmation(self_id, "aff", _INTENT_OK),
        mirror_lesson(self_id, "les", _INTENT_OK),
        mirror_regret(self_id, "reg", _INTENT_OK),
    ]
    for mid in mids:
        mem = repo.get(mid)
        assert mem is not None
        assert mem.context is not None
        assert mem.context.get("mirror") is True


# ---------------------------------------------------------------------------
# AC-32.17  Integration — total mirror count matches expected formula
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="AC-32.17: memory-mirroring not implemented")
def test_ac_69_17_total_mirror_count_formula(srepo: SelfRepo, self_id: str, new_id) -> None:
    """AC-32.17: mirrors = self-model mutations + 200 (bootstrap answers) + 1 (finalize LESSON)."""
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

    mirrored = srepo.conn.execute(
        "SELECT COUNT(*) FROM episodic_memory "
        "WHERE self_id = ? AND json_extract(context, '$.mirror') = 1",
        (self_id,),
    ).fetchone()[0]

    assert mirrored >= 200 + 1
