"""Tests for specs/mood.md: AC-27.*."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from turing.self_model import Mood
from turing.self_mood import (
    DECAY_RATE,
    EVENT_NUDGES,
    NEUTRAL_AROUSAL,
    NEUTRAL_FOCUS,
    NEUTRAL_VALENCE,
    NUDGE_MAX,
    apply_event_nudge,
    decay_step,
    mood_descriptor,
    nudge_mood,
    tick_mood_decay,
)
from turing.self_repo import SelfRepo


def _seed_mood(
    srepo: SelfRepo,
    self_id: str,
    valence: float = 0.0,
    arousal: float = 0.3,
    focus: float = 0.5,
    when: datetime | None = None,
) -> Mood:
    return srepo.insert_mood(
        Mood(
            self_id=self_id,
            valence=valence,
            arousal=arousal,
            focus=focus,
            last_tick_at=when or datetime.now(UTC),
        )
    )


# --------- AC-27.1 seeded at neutral ---------------------------------------


def test_ac_27_1_initial_seed_is_neutral(srepo, self_id) -> None:
    _seed_mood(srepo, self_id)
    m = srepo.get_mood(self_id)
    assert m.valence == NEUTRAL_VALENCE
    assert m.arousal == NEUTRAL_AROUSAL
    assert m.focus == NEUTRAL_FOCUS


# --------- AC-27.4 decay step maths -----------------------------------------


def test_ac_27_4_decay_step_single_hour_formula() -> None:
    # new = current + DECAY_RATE * (neutral - current)
    got = decay_step(1.0, 0.0, 1.0)
    assert got == pytest.approx(1.0 + DECAY_RATE * (0.0 - 1.0))


def test_ac_27_4_decay_step_multiple_hours_asymptote() -> None:
    # At 100 hours, state should be essentially neutral: 0.8 * (0.9)^100 ≈ 2.1e-5.
    got = decay_step(0.8, 0.0, 100.0)
    assert abs(got) < 1e-4


def test_ac_27_4_decay_step_zero_hours_no_change() -> None:
    assert decay_step(0.8, 0.0, 0.0) == 0.8


# --------- AC-27.5 catch-up on long gaps ------------------------------------


def test_ac_27_5_long_downtime_never_crosses_neutral(srepo, self_id) -> None:
    past = datetime.now(UTC) - timedelta(hours=100)
    _seed_mood(srepo, self_id, valence=0.8, arousal=0.9, focus=0.9, when=past)
    m = tick_mood_decay(srepo, self_id, datetime.now(UTC))
    # Approaches neutral but never passes it.
    assert 0.0 <= m.valence <= 0.8
    assert NEUTRAL_AROUSAL <= m.arousal <= 0.9
    assert NEUTRAL_FOCUS <= m.focus <= 0.9


def test_ac_27_5_effective_rate_scales_with_gap() -> None:
    # One hour decay of 10%, two hours ≈ 19%, ten hours ≈ 65%.
    assert decay_step(1.0, 0.0, 1.0) == pytest.approx(0.9, rel=1e-6)
    assert decay_step(1.0, 0.0, 2.0) == pytest.approx(0.81, rel=1e-6)
    assert decay_step(1.0, 0.0, 10.0) == pytest.approx((1.0 - DECAY_RATE) ** 10, rel=1e-6)


# --------- AC-27.6 idempotent within tick ----------------------------------


def test_ac_27_6_same_tick_idempotent(srepo, self_id) -> None:
    now = datetime.now(UTC)
    _seed_mood(srepo, self_id, valence=0.5, arousal=0.4, focus=0.6, when=now)
    m1 = tick_mood_decay(srepo, self_id, now)
    m2 = tick_mood_decay(srepo, self_id, now)
    assert (m1.valence, m1.arousal, m1.focus) == (m2.valence, m2.arousal, m2.focus)


# --------- AC-27.7 no-overshoot --------------------------------------------


def test_ac_27_7_decay_never_crosses_neutral_approaching_from_above() -> None:
    for hours in (0.5, 1.0, 5.0, 50.0, 500.0):
        got = decay_step(0.02, 0.0, hours)
        assert got >= 0.0
        assert got <= 0.02


def test_ac_27_7_decay_never_crosses_neutral_approaching_from_below() -> None:
    for hours in (0.5, 1.0, 5.0, 50.0, 500.0):
        got = decay_step(-0.5, 0.0, hours)
        assert got <= 0.0
        assert got >= -0.5


# --------- AC-27.8 nudge validation -----------------------------------------


def test_ac_27_8_nudge_beyond_max_raises(srepo, self_id) -> None:
    _seed_mood(srepo, self_id)
    with pytest.raises(ValueError, match="exceeds NUDGE_MAX"):
        nudge_mood(srepo, self_id, "valence", NUDGE_MAX + 0.01, reason="")


def test_ac_27_8_nudge_clamps_to_range(srepo, self_id) -> None:
    _seed_mood(srepo, self_id, valence=0.9)
    m = nudge_mood(srepo, self_id, "valence", 0.5, reason="")
    assert m.valence == 1.0  # clamped to upper bound


def test_ac_27_18_unknown_dim_raises(srepo, self_id) -> None:
    _seed_mood(srepo, self_id)
    with pytest.raises(ValueError, match="unknown mood dim"):
        nudge_mood(srepo, self_id, "clarity", 0.1, reason="")


# --------- AC-27.10 event nudge registry ------------------------------------


@pytest.mark.parametrize(
    "event,expected_dim",
    [
        ("tool_succeeded_against_expectation", "valence"),
        ("tool_failed_unexpectedly", "valence"),
        ("affirmation_minted", "valence"),
        ("regret_minted", "valence"),
        ("todo_completed", "valence"),
        ("warden_alert_on_ingress", "arousal"),
    ],
)
def test_ac_27_10_each_standard_event_shifts_expected_dim(
    srepo, self_id, event, expected_dim
) -> None:
    _seed_mood(srepo, self_id)
    before = srepo.get_mood(self_id)
    apply_event_nudge(srepo, self_id, event, reason="test")
    after = srepo.get_mood(self_id)
    # All events in EVENT_NUDGES touch at least one dim; we check the dim
    # declared first in the tuple list actually moved.
    expected_delta = next(d for dim, d in EVENT_NUDGES[event] if dim == expected_dim)
    assert getattr(after, expected_dim) == pytest.approx(
        max(
            -1.0 if expected_dim == "valence" else 0.0,
            min(1.0, getattr(before, expected_dim) + expected_delta),
        )
    )


def test_ac_27_10_regret_lowers_valence(srepo, self_id) -> None:
    _seed_mood(srepo, self_id, valence=0.0)
    apply_event_nudge(srepo, self_id, "regret_minted", reason="misrouted")
    m = srepo.get_mood(self_id)
    assert m.valence == pytest.approx(-0.20)


def test_ac_27_10_unknown_event_is_noop(srepo, self_id) -> None:
    _seed_mood(srepo, self_id, valence=0.4, arousal=0.4, focus=0.4)
    apply_event_nudge(srepo, self_id, "non_event", reason="ignored")
    m = srepo.get_mood(self_id)
    assert (m.valence, m.arousal, m.focus) == (0.4, 0.4, 0.4)


# --------- AC-27.12 descriptor lookup ---------------------------------------


def _mk(valence: float, arousal: float, focus: float) -> Mood:
    return Mood(
        self_id="s",
        valence=valence,
        arousal=arousal,
        focus=focus,
        last_tick_at=datetime.now(UTC),
    )


def test_ac_27_12_negative_low_arousal_descriptor() -> None:
    assert mood_descriptor(_mk(-0.5, 0.3, 0.5)).startswith("flat, withdrawn")


def test_ac_27_12_negative_high_arousal_descriptor() -> None:
    assert mood_descriptor(_mk(-0.5, 0.8, 0.5)).startswith("tense, on edge")


def test_ac_27_12_neutral_low_descriptor() -> None:
    assert mood_descriptor(_mk(0.0, 0.3, 0.5)).startswith("even, steady")


def test_ac_27_12_neutral_high_descriptor() -> None:
    assert mood_descriptor(_mk(0.0, 0.8, 0.5)).startswith("alert, attentive")


def test_ac_27_12_positive_low_descriptor() -> None:
    assert mood_descriptor(_mk(0.5, 0.3, 0.5)).startswith("content, easy")


def test_ac_27_12_positive_high_descriptor() -> None:
    assert mood_descriptor(_mk(0.5, 0.8, 0.5)).startswith("keen, energized")


def test_ac_27_12_focus_high_adds_suffix() -> None:
    assert mood_descriptor(_mk(0.0, 0.3, 0.9)).endswith("; focused")


def test_ac_27_12_focus_low_adds_suffix() -> None:
    assert mood_descriptor(_mk(0.0, 0.3, 0.1)).endswith("; scattered")


def test_ac_27_12_focus_medium_no_suffix() -> None:
    got = mood_descriptor(_mk(0.0, 0.3, 0.5))
    assert ";" not in got


# --------- AC-27.17 tick ordering ------------------------------------------


def test_ac_27_17_tick_before_nudge_same_second(srepo, self_id) -> None:
    past = datetime.now(UTC) - timedelta(hours=1)
    _seed_mood(srepo, self_id, valence=1.0, when=past)
    tick_mood_decay(srepo, self_id, datetime.now(UTC))
    after_tick = srepo.get_mood(self_id).valence
    nudge_mood(srepo, self_id, "valence", 0.1, reason="")
    after_nudge = srepo.get_mood(self_id).valence
    assert after_nudge == pytest.approx(min(1.0, after_tick + 0.1))


# --------- AC-27.11 serialization: sequential nudges are not lost ----------


def test_ac_27_11_sequential_nudges_accumulate(srepo, self_id) -> None:
    _seed_mood(srepo, self_id, valence=0.0)
    for _ in range(3):
        nudge_mood(srepo, self_id, "valence", 0.1, reason="")
    assert srepo.get_mood(self_id).valence == pytest.approx(0.3)
