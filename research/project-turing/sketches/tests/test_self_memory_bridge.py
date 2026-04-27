"""Tests for specs/memory-mirroring.md: AC-32.1..16."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.repo import Repo
from turing.self_memory_bridge import (
    INTENT_AT_TIME_MAX,
    MIRROR_CONTENT_MAX,
    MirrorContentTooLong,
    MirrorIntentTooLong,
    _request_hash_var,
    _perception_tool_call_id_var,
    mirror_affirmation,
    mirror_lesson,
    mirror_observation,
    mirror_opinion,
    mirror_regret,
    set_mirror_perception_tool_call_id,
    set_mirror_request_hash,
)
from turing.self_model import (
    ALL_FACETS,
    Mood,
    Passion,
    PersonalityAnswer,
    PersonalityFacet,
    PersonalityItem,
    facet_node_id,
)
from turing.self_repo import SelfRepo
from turing.self_identity import bootstrap_self_id
from turing.types import MemoryTier, SourceKind


def _bootstrap(srepo: SelfRepo, self_id: str, new_id) -> None:
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
        facet_names = [f for _, f in ALL_FACETS]
        facet = facet_names[i % len(facet_names)]
        item_id = f"item:{i + 1}"
        srepo.insert_item(
            PersonalityItem(
                node_id=item_id,
                self_id=self_id,
                item_number=i + 1,
                prompt_text=f"Q{i + 1}",
                keyed_facet=facet,
                reverse_scored=False,
            )
        )
        srepo.insert_answer(
            PersonalityAnswer(
                node_id=f"ans:{i + 1}",
                self_id=self_id,
                item_id=item_id,
                revision_id=None,
                answer_1_5=3,
                justification_text="",
                asked_at=now,
            )
        )
    srepo.insert_mood(Mood(self_id=self_id, valence=0.0, arousal=0.3, focus=0.5, last_tick_at=now))


@pytest.fixture
def bridged(repo: Repo, srepo: SelfRepo, new_id) -> tuple[Repo, SelfRepo, str]:
    sid = bootstrap_self_id(repo.conn)
    _bootstrap(srepo, sid, new_id)
    return repo, srepo, sid


# =========================================================================
# AC-32.1  Bridge API — five helpers each return a memory_id
# =========================================================================


class TestBridgeAPI:
    def test_mirror_observation_returns_id(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "I noticed something", "test intent")
        assert mid.startswith("mem:") or len(mid) == 36

    def test_mirror_opinion_returns_id(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_opinion(repo, sid, "I believe X", "test intent")
        assert mid

    def test_mirror_affirmation_returns_id(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_affirmation(repo, sid, "X confirmed", "test intent")
        assert mid

    def test_mirror_lesson_returns_id(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_lesson(repo, sid, "I learned Y", "test intent")
        assert mid

    def test_mirror_regret_returns_id(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_regret(repo, sid, "I regret Z", "test intent")
        assert mid

    def test_mirror_observation_stores_correct_tier(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "obs", "intent")
        m = repo.get(mid)
        assert m is not None
        assert m.tier == MemoryTier.OBSERVATION
        assert m.source == SourceKind.I_DID
        assert m.content == "obs"

    def test_mirror_opinion_stores_correct_tier(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_opinion(repo, sid, "opin", "intent")
        m = repo.get(mid)
        assert m.tier == MemoryTier.OPINION

    def test_mirror_affirmation_stores_correct_tier(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_affirmation(repo, sid, "aff", "intent")
        m = repo.get(mid)
        assert m.tier == MemoryTier.AFFIRMATION

    def test_mirror_lesson_stores_correct_tier(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_lesson(repo, sid, "less", "intent")
        m = repo.get(mid)
        assert m.tier == MemoryTier.LESSON

    def test_mirror_regret_stores_correct_tier(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_regret(repo, sid, "reg", "intent")
        m = repo.get(mid)
        assert m.tier == MemoryTier.REGRET


# =========================================================================
# AC-32.2  Content and intent length validation
# =========================================================================


class TestLengthValidation:
    def test_content_at_max_ok(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "x" * MIRROR_CONTENT_MAX, "ok")
        assert mid

    def test_content_over_max_raises(self, bridged) -> None:
        repo, _, sid = bridged
        with pytest.raises(MirrorContentTooLong):
            mirror_observation(repo, sid, "x" * (MIRROR_CONTENT_MAX + 1), "ok")

    def test_intent_at_max_ok(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "ok", "y" * INTENT_AT_TIME_MAX)
        assert mid

    def test_intent_over_max_raises(self, bridged) -> None:
        repo, _, sid = bridged
        with pytest.raises(MirrorIntentTooLong):
            mirror_observation(repo, sid, "ok", "y" * (INTENT_AT_TIME_MAX + 1))


# =========================================================================
# AC-32.3  Context augmentation — self_id, mirror=True, request_hash
# =========================================================================


class TestContextAugmentation:
    def test_context_has_mirror_true(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "obs", "intent")
        m = repo.get(mid)
        assert m.context.get("mirror") is True

    def test_context_has_self_id(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "obs", "intent")
        m = repo.get(mid)
        assert m.context.get("self_id") == sid

    def test_context_includes_request_hash(self, bridged) -> None:
        repo, _, sid = bridged
        tok = _request_hash_var.set("req-hash-123")
        try:
            mid = mirror_observation(repo, sid, "obs", "intent")
            m = repo.get(mid)
            assert m.context.get("request_hash") == "req-hash-123"
        finally:
            _request_hash_var.reset(tok)

    def test_context_includes_perception_tool_call_id(self, bridged) -> None:
        repo, _, sid = bridged
        tok = _perception_tool_call_id_var.set("ptc-42")
        try:
            mid = mirror_observation(repo, sid, "obs", "intent")
            m = repo.get(mid)
            assert m.context.get("perception_tool_call_id") == "ptc-42"
        finally:
            _perception_tool_call_id_var.reset(tok)

    def test_context_merges_caller_context(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "obs", "intent", context={"extra_key": "extra_val"})
        m = repo.get(mid)
        assert m.context["extra_key"] == "extra_val"
        assert m.context["mirror"] is True

    def test_caller_self_id_not_overwritten(self, bridged) -> None:
        repo, _, sid = bridged
        mid = mirror_observation(repo, sid, "obs", "intent", context={"self_id": "custom"})
        m = repo.get(mid)
        assert m.context["self_id"] == "custom"


# =========================================================================
# AC-32.14  Bridge never mutates existing memories — only inserts
# =========================================================================


class TestInsertOnly:
    @pytest.mark.parametrize(
        "fn",
        [mirror_observation, mirror_opinion, mirror_affirmation, mirror_lesson, mirror_regret],
    )
    def test_bridge_only_inserts(self, bridged, fn) -> None:
        repo, _, sid = bridged
        count_before = sum(1 for _ in repo.find(self_id=sid))
        fn(repo, sid, "content", "intent")
        count_after = sum(1 for _ in repo.find(self_id=sid))
        assert count_after == count_before + 1
