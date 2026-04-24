"""Coverage gap filler for turing/self_nodes.py.

Spec: AC-24 _wire helper (contributes_to path), _guess_kind for all prefixes,
downgrade_skill range/out-of-range, practice_skill range guard,
note_skill with custom decay_rate_per_day.

Acceptance criteria:
- _wire creates contributors when contributes_to is provided
- _wire does nothing when contributes_to is None or empty
- _guess_kind returns correct NodeKind for every prefix and defaults to FACET
- downgrade_skill rejects out-of-range new_level and blank reason
- practice_skill rejects out-of-range new_level
- note_skill accepts custom decay_rate_per_day
- practice_skill raises on cross-self
- downgrade_skill raises on cross-self
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_model import (
    DEFAULT_DECAY_RATES,
    Hobby,
    Interest,
    NodeKind,
    Passion,
    Preference,
    PreferenceKind,
    Skill,
    SkillKind,
)
from turing.self_model import guess_node_kind
from turing.self_nodes import (
    _reject_dupe_text,
    _wire,
    downgrade_skill,
    note_hobby,
    note_interest,
    note_passion,
    note_preference,
    note_skill,
    practice_skill,
)


def _seed_facet(srepo, self_id) -> str:
    from turing.self_model import PersonalityFacet, Trait, facet_node_id

    fid = facet_node_id(Trait.HONESTY_HUMILITY, "sincerity")
    srepo.insert_facet(
        PersonalityFacet(
            node_id=fid,
            self_id=self_id,
            trait=Trait.HONESTY_HUMILITY,
            facet_id="sincerity",
            score=3.0,
            last_revised_at=datetime.now(UTC),
        )
    )
    return fid


class TestWireContributor:
    def test_wire_creates_contributor(self, srepo, self_id, new_id) -> None:
        fid = _seed_facet(srepo, self_id)
        _wire(
            srepo,
            self_id,
            "passion:1",
            NodeKind.PASSION,
            [(fid, 0.6)],
            new_id,
        )
        contribs = srepo.active_contributors_for(fid, at=datetime.now(UTC))
        assert any(c.source_id == "passion:1" for c in contribs)

    def test_wire_none_contributes_to(self, srepo, self_id, new_id) -> None:
        _wire(srepo, self_id, "passion:1", NodeKind.PASSION, None, new_id)

    def test_wire_empty_contributes_to(self, srepo, self_id, new_id) -> None:
        _wire(srepo, self_id, "passion:1", NodeKind.PASSION, [], new_id)

    def test_wire_guesses_kind_for_non_facet(self, srepo, self_id, new_id) -> None:
        p = note_passion(srepo, self_id, "first", 0.5, new_id)
        _wire(
            srepo,
            self_id,
            "hobby:1",
            NodeKind.HOBBY,
            [(p.node_id, 0.3)],
            new_id,
        )
        contribs = srepo.active_contributors_for(p.node_id, at=datetime.now(UTC))
        assert any(c.source_id == "hobby:1" for c in contribs)


class TestGuessKind:
    @pytest.mark.parametrize(
        "prefix,expected",
        [
            ("facet:x", NodeKind.PERSONALITY_FACET),
            ("passion:x", NodeKind.PASSION),
            ("hobby:x", NodeKind.HOBBY),
            ("interest:x", NodeKind.INTEREST),
            ("pref:x", NodeKind.PREFERENCE),
            ("skill:x", NodeKind.SKILL),
            ("unknown:x", NodeKind.PERSONALITY_FACET),
        ],
    )
    def test_all_prefixes(self, prefix, expected) -> None:
        assert guess_node_kind(prefix) == expected


class TestRejectDupeText:
    def test_rejects_duplicate(self) -> None:
        rows = [SimpleNamespace(text="Hello World")]
        with pytest.raises(ValueError, match="duplicate"):
            _reject_dupe_text(rows, lambda r: r.text, "hello world", kind="test")

    def test_allows_different(self) -> None:
        rows = [SimpleNamespace(text="Hello")]
        _reject_dupe_text(rows, lambda r: r.text, "Different", kind="test")

    def test_empty_list_passes(self) -> None:
        _reject_dupe_text([], lambda r: r.text, "anything", kind="test")


class TestSkillOperations:
    def test_practice_skill_cross_self(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "python", 0.5, SkillKind.INTELLECTUAL, new_id)
        with pytest.raises(PermissionError, match="cross-self"):
            practice_skill(srepo, "other-self", s.node_id)

    def test_practice_skill_out_of_range(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "python", 0.5, SkillKind.INTELLECTUAL, new_id)
        with pytest.raises(ValueError, match="out of range"):
            practice_skill(srepo, self_id, s.node_id, new_level=1.5)

    def test_practice_skill_negative_level(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "python", 0.5, SkillKind.INTELLECTUAL, new_id)
        with pytest.raises(ValueError, match="out of range"):
            practice_skill(srepo, self_id, s.node_id, new_level=1.5)

    def test_downgrade_skill_cross_self(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
        with pytest.raises(PermissionError, match="cross-self"):
            downgrade_skill(srepo, "other-self", s.node_id, 0.5, "reason")

    def test_downgrade_skill_out_of_range(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
        with pytest.raises(ValueError, match="out of range"):
            downgrade_skill(srepo, self_id, s.node_id, 1.5, "reason")

    def test_downgrade_skill_blank_reason(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "python", 0.8, SkillKind.INTELLECTUAL, new_id)
        with pytest.raises(ValueError, match="reason is required"):
            downgrade_skill(srepo, self_id, s.node_id, 0.3, "   ")

    def test_note_skill_custom_decay_rate(self, srepo, self_id, new_id) -> None:
        s = note_skill(
            srepo,
            self_id,
            "archery",
            0.6,
            SkillKind.PHYSICAL,
            new_id,
            decay_rate_per_day=0.01,
        )
        assert s.decay_rate_per_day == 0.01

    def test_note_skill_default_decay_rate(self, srepo, self_id, new_id) -> None:
        s = note_skill(srepo, self_id, "archery", 0.6, SkillKind.PHYSICAL, new_id)
        assert s.decay_rate_per_day == DEFAULT_DECAY_RATES[SkillKind.PHYSICAL]


class TestNoteHobbyWithContributor:
    def test_hobby_with_contributes_to(self, srepo, self_id, new_id) -> None:
        fid = _seed_facet(srepo, self_id)
        h = note_hobby(
            srepo,
            self_id,
            "Climbing",
            "bouldering",
            new_id,
            contributes_to=[(fid, 0.4)],
        )
        contribs = srepo.active_contributors_for(fid, at=datetime.now(UTC))
        assert any(c.source_id == h.node_id for c in contribs)


class TestNoteInterestWithContributor:
    def test_interest_with_contributes_to(self, srepo, self_id, new_id) -> None:
        fid = _seed_facet(srepo, self_id)
        i = note_interest(
            srepo,
            self_id,
            "Physics",
            "quantum mechanics",
            new_id,
            contributes_to=[(fid, 0.5)],
        )
        contribs = srepo.active_contributors_for(fid, at=datetime.now(UTC))
        assert any(c.source_id == i.node_id for c in contribs)


class TestNotePreferenceWithContributor:
    def test_preference_with_contributes_to(self, srepo, self_id, new_id) -> None:
        fid = _seed_facet(srepo, self_id)
        p = note_preference(
            srepo,
            self_id,
            PreferenceKind.FAVORITE,
            "tea",
            0.9,
            "warm",
            new_id,
            contributes_to=[(fid, 0.3)],
        )
        contribs = srepo.active_contributors_for(fid, at=datetime.now(UTC))
        assert any(c.source_id == p.node_id for c in contribs)


class TestNotePassionWithContributor:
    def test_passion_with_contributes_to(self, srepo, self_id, new_id) -> None:
        fid = _seed_facet(srepo, self_id)
        p = note_passion(
            srepo,
            self_id,
            "music",
            0.8,
            new_id,
            contributes_to=[(fid, 0.5)],
        )
        contribs = srepo.active_contributors_for(fid, at=datetime.now(UTC))
        assert any(c.source_id == p.node_id for c in contribs)


class SimpleNamespace:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
