"""Tests for specs/mood-affects-decisions.md: AC-59.*."""

from __future__ import annotations

import dataclasses

import pytest

from turing.self_mood_decisions import (
    MoodBiases,
    _model_tier_hint,
    _specialist_preference,
    _warden_adjustment,
    effective_warden_threshold,
    mood_biases,
)


# --------- AC-59.1 neutral mood → empty preference, hint near 0 ---------------


def test_ac_59_1_neutral_empty_preference() -> None:
    got = _specialist_preference(valence=0.0, arousal=0.3, focus=0.5)
    assert got == {}


def test_ac_59_1_neutral_hint_near_zero() -> None:
    biases = mood_biases(valence=0.0, arousal=0.5, focus=0.5)
    assert abs(biases.model_tier_hint) < 0.01


# --------- AC-59.2 negative + high arousal → ranger/warden bias ---------------


def test_ac_59_2_negative_high_arousal() -> None:
    prefs = _specialist_preference(valence=-0.5, arousal=0.8, focus=0.5)
    assert "ranger" in prefs
    assert "warden_at_arms" in prefs
    assert prefs["ranger"] == pytest.approx(0.15)
    assert prefs["warden_at_arms"] == pytest.approx(0.10)


# --------- AC-59.3 positive + high arousal → artificer/scribe bias -----------


def test_ac_59_3_positive_high_arousal() -> None:
    prefs = _specialist_preference(valence=0.5, arousal=0.8, focus=0.5)
    assert "artificer" in prefs
    assert "scribe" in prefs
    assert prefs["artificer"] == pytest.approx(0.10)
    assert prefs["scribe"] == pytest.approx(0.10)


# --------- AC-59.4 low focus → reply_directly bias ---------------------------


def test_ac_59_4_low_focus_reply_directly() -> None:
    prefs = _specialist_preference(valence=0.0, arousal=0.3, focus=0.1)
    assert "reply_directly" in prefs
    assert prefs["reply_directly"] == pytest.approx(0.15)


# --------- AC-59.5 high focus → artificer bias -------------------------------


def test_ac_59_5_high_focus_artificer() -> None:
    prefs = _specialist_preference(valence=0.0, arousal=0.3, focus=0.8)
    assert "artificer" in prefs
    assert prefs["artificer"] == pytest.approx(0.10)


# --------- AC-59.6 model_tier_hint: arousal > focus → positive ---------------


def test_ac_59_6_tier_hint_arousal_gt_focus() -> None:
    got = _model_tier_hint(arousal=0.9, focus=0.3)
    assert got > 0.0


# --------- AC-59.7 warden_adjustment: valence < -0.4 → -0.15 -----------------


def test_ac_59_7_warden_adj_negative() -> None:
    got = _warden_adjustment(valence=-0.6, focus=0.5)
    assert got == pytest.approx(-0.15)


# --------- AC-59.8 warden_adjustment: valence > 0.5 & focus > 0.6 → +0.05 ---


def test_ac_59_8_warden_adj_positive() -> None:
    got = _warden_adjustment(valence=0.7, focus=0.7)
    assert got == pytest.approx(0.05)


# --------- AC-59.9 effective_warden_threshold clamps to [0.3, 0.95] ----------


def test_ac_59_9_clamp_lower_bound() -> None:
    assert effective_warden_threshold(0.2, -0.15) == 0.3


def test_ac_59_9_clamp_upper_bound() -> None:
    assert effective_warden_threshold(0.9, 0.1) == 0.95


def test_ac_59_9_clamp_midrange_unchanged() -> None:
    assert effective_warden_threshold(0.7, -0.05) == pytest.approx(0.65)


# --------- AC-59.10 MoodBiases is frozen -------------------------------------


def test_ac_59_10_frozen_dataclass() -> None:
    biases = mood_biases(valence=0.0, arousal=0.5, focus=0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        biases.model_tier_hint = 0.99


# --------- AC-59.11 full mood_biases integration -----------------------------


def test_ac_59_11_mood_biases_returns_all_fields() -> None:
    got = mood_biases(valence=-0.5, arousal=0.9, focus=0.2)
    assert isinstance(got, MoodBiases)
    assert isinstance(got.specialist_preference, dict)
    assert isinstance(got.model_tier_hint, float)
    assert isinstance(got.warden_threshold_adjustment, float)
