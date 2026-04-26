"""Mood-affects-decisions — mood biases for routing. See specs/mood-affects-decisions.md."""

from __future__ import annotations

from dataclasses import dataclass

MIN_WARDEN_THRESHOLD: float = 0.3
MAX_WARDEN_THRESHOLD: float = 0.95


@dataclass(frozen=True)
class MoodBiases:
    specialist_preference: dict[str, float]
    model_tier_hint: float
    warden_threshold_adjustment: float


def _specialist_preference(valence: float, arousal: float, focus: float) -> dict[str, float]:
    prefs: dict[str, float] = {}
    if valence < -0.3 and arousal > 0.5:
        prefs["ranger"] = 0.15
        prefs["warden_at_arms"] = 0.10
    if valence > 0.3 and arousal > 0.5:
        prefs["artificer"] = 0.10
        prefs["scribe"] = 0.10
    if focus < 0.3:
        prefs["reply_directly"] = 0.15
    if focus > 0.7:
        prefs["artificer"] = prefs.get("artificer", 0.0) + 0.10
    clamped = {k: max(-1.0, min(1.0, v)) for k, v in prefs.items()}
    return clamped


def _model_tier_hint(arousal: float, focus: float) -> float:
    import math

    return max(-1.0, min(1.0, math.tanh(arousal - focus)))


def _warden_adjustment(valence: float, focus: float) -> float:
    if valence < -0.4:
        adj = -0.15
    elif valence > 0.5 and focus > 0.6:
        adj = 0.05
    else:
        adj = 0.0
    return max(-0.2, min(0.1, adj))


def mood_biases(valence: float, arousal: float, focus: float) -> MoodBiases:
    sp = _specialist_preference(valence, arousal, focus)
    mth = _model_tier_hint(arousal, focus)
    wa = _warden_adjustment(valence, focus)
    return MoodBiases(
        specialist_preference=sp,
        model_tier_hint=mth,
        warden_threshold_adjustment=wa,
    )


def effective_warden_threshold(base: float, adjustment: float) -> float:
    return max(MIN_WARDEN_THRESHOLD, min(MAX_WARDEN_THRESHOLD, base + adjustment))
