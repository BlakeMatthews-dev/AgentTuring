"""Coverage gap filler for turing/self_activation.py, turing/self_surface.py,
and turing/runtime/actor.py.

Spec: Cover source_state for all source kinds, active_now with/without
contributors, _recency_state edge cases, recall_self full path,
render_minimal_block, Actor on_tick and _handle paths.

Acceptance criteria:
- source_state handles personality_facet, passion, preference, hobby,
  interest, skill, mood, memory, rule, retrieval, unknown
- active_now returns 0.5 for no contributors
- _recency_state handles None, zero, in-window, expired
- recall_self raises SelfNotReady when facets incomplete
- render_minimal_block produces valid block
- Actor polls and dispatches to tools on cadence
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from turing.repo import Repo
from turing.self_activation import (
    ActivationContext,
    _recency_state,
    active_now,
    self_id_or_none,
    source_state,
)
from turing.self_model import (
    ALL_FACETS,
    Hobby,
    Interest,
    Mood,
    Passion,
    PersonalityFacet,
    Preference,
    PreferenceKind,
    Skill,
    SkillKind,
    facet_node_id,
)
from turing.self_nodes import (
    note_hobby,
    note_interest,
    note_passion,
    note_preference,
    note_skill,
)
from turing.self_repo import SelfRepo
from turing.self_surface import (
    SelfNotReady,
    _approx_tokens,
    recall_self,
    render_minimal_block,
    trait_phrase_top3,
)
from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _seed_all_facets(srepo: SelfRepo, self_id: str, score: float = 3.0) -> None:
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


class TestSelfIdOrNone:
    def test_returns_string(self) -> None:
        assert self_id_or_none("abc") == "abc"

    def test_returns_empty_for_none(self) -> None:
        assert self_id_or_none(None) == ""


class TestRecencyState:
    def test_none_returns_zero(self) -> None:
        now = datetime.now(UTC)
        assert _recency_state(None, now, 14.0) == 0.0

    def test_zero_days_returns_one(self) -> None:
        now = datetime.now(UTC)
        assert _recency_state(now, now, 14.0) == 1.0

    def test_past_in_window(self) -> None:
        now = datetime.now(UTC)
        past = now - timedelta(days=7)
        result = _recency_state(past, now, 14.0)
        assert 0.0 < result < 1.0

    def test_expired(self) -> None:
        now = datetime.now(UTC)
        old = now - timedelta(days=30)
        assert _recency_state(old, now, 14.0) == 0.0


class TestSourceState:
    def test_personality_facet(self, srepo, self_id) -> None:
        _seed_all_facets(srepo, self_id, score=3.0)
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        fid = facet_node_id(list(ALL_FACETS)[0][0], list(ALL_FACETS)[0][1])
        result = source_state(srepo, fid, "personality_facet", ctx)
        assert 0.0 <= result <= 1.0

    def test_passion(self, srepo, self_id, new_id) -> None:
        p = note_passion(srepo, self_id, "music", 0.8, new_id)
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, p.node_id, "passion", ctx)
        assert result == 0.8

    def test_preference(self, srepo, self_id, new_id) -> None:
        p = note_preference(srepo, self_id, PreferenceKind.LIKE, "tea", 0.7, "warm", new_id)
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, p.node_id, "preference", ctx)
        assert result == 0.7

    def test_hobby(self, srepo, self_id, new_id) -> None:
        h = note_hobby(srepo, self_id, "Reading", "philosophy", new_id)
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, h.node_id, "hobby", ctx)
        assert result == 0.0

    def test_interest(self, srepo, self_id, new_id) -> None:
        i = note_interest(srepo, self_id, "Neuroscience", "brain", new_id)
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, i.node_id, "interest", ctx)
        assert result == 0.0

    def test_skill(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, s.node_id, "skill", ctx)
        assert 0.0 <= result <= 1.0

    def test_mood(self, srepo, self_id) -> None:
        srepo.insert_mood(
            Mood(
                self_id=self_id, valence=0.5, arousal=0.3, focus=0.7, last_tick_at=datetime.now(UTC)
            )
        )
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, "mood:1", "mood", ctx)
        assert 0.0 <= result <= 1.0

    def test_memory(self, srepo, self_id) -> None:
        r = Repo(None)
        from turing.self_identity import bootstrap_self_id as bsid

        sid = bsid(r.conn)
        m = EpisodicMemory(
            memory_id="mem:1",
            self_id=sid,
            tier=MemoryTier.OBSERVATION,
            source=SourceKind.I_DID,
            content="test",
            weight=0.5,
        )
        r.insert(m)
        sr = SelfRepo(r.conn)
        ctx = ActivationContext(self_id=sid, now=datetime.now(UTC))
        result = source_state(sr, "mem:1", "memory", ctx)
        assert 0.0 <= result <= 1.0
        r.close()

    def test_memory_not_found(self, srepo, self_id) -> None:
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, "nonexistent", "memory", ctx)
        assert result == 0.0

    def test_rule(self, srepo, self_id) -> None:
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, "rule:1", "rule", ctx)
        assert result == 1.0

    def test_retrieval(self, srepo, self_id) -> None:
        ctx = ActivationContext(
            self_id=self_id,
            now=datetime.now(UTC),
            retrieval_similarity={"ret:1": 0.7},
        )
        result = source_state(srepo, "ret:1", "retrieval", ctx)
        assert result == 0.7

    def test_retrieval_missing(self, srepo, self_id) -> None:
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = source_state(srepo, "ret:1", "retrieval", ctx)
        assert result == 0.0

    def test_unknown_raises(self, srepo, self_id) -> None:
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        with pytest.raises(ValueError, match="unknown source_kind"):
            source_state(srepo, "x", "bogus", ctx)


class TestActiveNow:
    def test_no_contributors_returns_neutral(self, srepo, self_id) -> None:
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        result = active_now(srepo, "facet:unknown", ctx)
        assert result == 0.5


class TestRecallSelf:
    def test_raises_self_not_ready(self, srepo, self_id) -> None:
        with pytest.raises(SelfNotReady):
            recall_self(srepo, self_id)

    def test_full_recall(self, srepo, self_id, new_id) -> None:
        _seed_all_facets(srepo, self_id)
        note_passion(srepo, self_id, "music", 0.8, new_id)
        note_hobby(srepo, self_id, "Reading", "books", new_id)
        note_interest(srepo, self_id, "Neuroscience", "brain", new_id)
        note_skill(srepo, self_id, "python", 0.7, SkillKind.INTELLECTUAL, new_id)
        note_preference(srepo, self_id, PreferenceKind.LIKE, "tea", 0.9, "warm", new_id)
        srepo.insert_mood(
            Mood(
                self_id=self_id, valence=0.5, arousal=0.3, focus=0.7, last_tick_at=datetime.now(UTC)
            )
        )
        result = recall_self(srepo, self_id)
        assert result["self_id"] == self_id
        assert len(result["personality"]) == 24
        assert len(result["passions"]) == 1
        assert len(result["hobbies"]) == 1
        assert len(result["interests"]) == 1
        assert len(result["skills"]) == 1
        assert len(result["preferences"]) == 1
        assert result["mood"]["valence"] == 0.5


class TestTraitPhrase:
    def test_top3(self, srepo, self_id) -> None:
        _seed_all_facets(srepo, self_id)
        ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
        phrase = trait_phrase_top3(srepo, self_id, ctx)
        assert len(phrase) > 0


class TestRenderMinimalBlock:
    def test_raises_self_not_ready(self, srepo, self_id) -> None:
        with pytest.raises(SelfNotReady):
            render_minimal_block(srepo, self_id)

    def test_produces_block(self, srepo, self_id, new_id) -> None:
        _seed_all_facets(srepo, self_id)
        srepo.insert_mood(
            Mood(
                self_id=self_id, valence=0.5, arousal=0.3, focus=0.7, last_tick_at=datetime.now(UTC)
            )
        )
        block = render_minimal_block(srepo, self_id)
        assert "I am" in block
        assert "Right now" in block


class TestApproxTokens:
    def test_counts_words(self) -> None:
        assert _approx_tokens("hello world foo") == 3

    def test_empty_string(self) -> None:
        assert _approx_tokens("") == 0
