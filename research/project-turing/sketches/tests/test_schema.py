"""Tests for specs/schema.md: AC-1.1 through AC-1.6."""

from __future__ import annotations

import pytest

from turing.types import EpisodicMemory, MemoryTier, SourceKind


def _base(**overrides: object) -> dict[str, object]:
    defaults: dict[str, object] = dict(
        memory_id="m1",
        self_id="self-A",
        tier=MemoryTier.OBSERVATION,
        source=SourceKind.I_DID,
        content="something happened",
        weight=0.3,
    )
    defaults.update(overrides)
    return defaults


def test_ac_1_1_missing_self_id_raises() -> None:
    with pytest.raises(ValueError, match="self_id is required"):
        EpisodicMemory(**_base(self_id=""))


def test_ac_1_2_source_is_enum_typed() -> None:
    m = EpisodicMemory(**_base())
    assert isinstance(m.source, SourceKind)


def test_ac_1_3_affect_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="affect"):
        EpisodicMemory(**_base(affect=1.5))
    with pytest.raises(ValueError, match="affect"):
        EpisodicMemory(**_base(affect=-1.5))


def test_ac_1_3_affect_in_range_accepted() -> None:
    for a in (-1.0, -0.5, 0.0, 0.5, 1.0):
        EpisodicMemory(**_base(affect=a))


def test_ac_1_4_confidence_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        EpisodicMemory(**_base(confidence_at_creation=1.5))
    with pytest.raises(ValueError, match="confidence"):
        EpisodicMemory(**_base(confidence_at_creation=-0.1))


def test_ac_1_4_surprise_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="surprise"):
        EpisodicMemory(**_base(surprise_delta=1.5))
    with pytest.raises(ValueError, match="surprise"):
        EpisodicMemory(**_base(surprise_delta=-0.1))


def test_ac_1_5_self_reference_in_supersedes_raises() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        EpisodicMemory(**_base(supersedes="m1"))


def test_ac_1_6_immutable_defaults_false() -> None:
    m = EpisodicMemory(**_base())
    assert m.immutable is False


def test_ac_1_6_immutable_write_once() -> None:
    m = EpisodicMemory(**_base(immutable=True))
    with pytest.raises(AttributeError, match="immutable"):
        m.immutable = False


def test_frozen_fields_cannot_be_mutated() -> None:
    m = EpisodicMemory(**_base())
    with pytest.raises(AttributeError, match="frozen"):
        m.content = "new content"
    with pytest.raises(AttributeError, match="frozen"):
        m.weight = 0.9
    with pytest.raises(AttributeError, match="frozen"):
        m.self_id = "other"


def test_mutable_fields_can_change() -> None:
    m = EpisodicMemory(**_base())
    m.reinforcement_count = 3
    m.contradiction_count = 1
    assert m.reinforcement_count == 3
    assert m.contradiction_count == 1


def test_superseded_by_settable_once() -> None:
    m = EpisodicMemory(**_base())
    m.superseded_by = "m2"
    with pytest.raises(AttributeError, match="settable only once"):
        m.superseded_by = "m3"


def test_durable_tier_requires_i_did_source() -> None:
    with pytest.raises(ValueError, match="requires source=i_did"):
        EpisodicMemory(
            **_base(
                tier=MemoryTier.REGRET,
                source=SourceKind.I_WAS_TOLD,
                weight=0.6,
                intent_at_time="did-something",
            )
        )


def test_accomplishment_requires_intent() -> None:
    with pytest.raises(ValueError, match="intent_at_time"):
        EpisodicMemory(
            **_base(
                tier=MemoryTier.ACCOMPLISHMENT,
                source=SourceKind.I_DID,
                weight=0.6,
                intent_at_time="",
            )
        )
