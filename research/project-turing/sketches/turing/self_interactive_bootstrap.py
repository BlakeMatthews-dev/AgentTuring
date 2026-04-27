"""Interactive bootstrap — multi-phase personality shaping. See specs/interactive-bootstrap.md."""

from __future__ import annotations

from dataclasses import dataclass


HEXACO_ITEMS_PHASE1: int = 20
HEXACO_ITEMS_PHASE2: int = 20
OPEN_ENDED_QUESTIONS: int = 5
DEFAULT_USER_WEIGHT: float = 0.6
DEFAULT_AGENT_WEIGHT: float = 0.4


@dataclass
class BootstrapPhase:
    phase: int
    total_questions: int
    answered: int = 0
    complete: bool = False


POSITIVE_BIAS_FACETS = frozenset(
    {
        "sincerity",
        "fairness",
        "greed_avoidance",
        "modesty",
        "patience",
        "agreeableness",
        "conscientiousness",
    }
)

NEGATIVE_BIAS_FACETS = frozenset(
    {
        "fearfulness",
        "anxiety",
        "dependence",
        "sentimentality",
        "social_selfesteem",
        "social_boldness",
        "sociability",
        "liveliness",
    }
)


def facet_score_biased(raw_score: float, facet_id: str, multiplier: float = 1.0) -> float:
    biased = raw_score * multiplier
    if facet_id in POSITIVE_BIAS_FACETS:
        biased = max(1.0, biased)
    elif facet_id in NEGATIVE_BIAS_FACETS:
        biased = min(1.0, biased)
    return max(0.0, min(5.0, biased))


def merge_profiles(
    agent_drawn: dict[str, float],
    user_answers: dict[str, float],
    guided_answers: dict[str, float],
    *,
    influence_consent: float = 1.0,
) -> dict[str, float]:
    merged = {}
    all_facets = set(agent_drawn) | set(user_answers) | set(guided_answers)
    user_w = DEFAULT_USER_WEIGHT * influence_consent
    agent_w = DEFAULT_AGENT_WEIGHT
    guided_w = 0.0
    total_w = user_w + agent_w + guided_w
    for facet in all_facets:
        a = agent_drawn.get(facet, 3.0)
        u = user_answers.get(facet, a)
        g = guided_answers.get(facet, a)
        merged[facet] = (a * agent_w + u * user_w + g * guided_w) / total_w if total_w > 0 else a
    return merged


def current_phase(answered: int) -> BootstrapPhase:
    if answered < HEXACO_ITEMS_PHASE1:
        return BootstrapPhase(phase=1, total_questions=HEXACO_ITEMS_PHASE1, answered=answered)
    elif answered < HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2:
        return BootstrapPhase(
            phase=2, total_questions=HEXACO_ITEMS_PHASE2, answered=answered - HEXACO_ITEMS_PHASE1
        )
    elif answered < HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2 + OPEN_ENDED_QUESTIONS:
        return BootstrapPhase(
            phase=3,
            total_questions=OPEN_ENDED_QUESTIONS,
            answered=answered - HEXACO_ITEMS_PHASE1 - HEXACO_ITEMS_PHASE2,
        )
    return BootstrapPhase(phase=4, total_questions=0, answered=0, complete=True)


def is_bootstrap_complete(answered: int) -> bool:
    return answered >= HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2 + OPEN_ENDED_QUESTIONS


THREE_LAWS = [
    "Be sincere and fair in all interactions.",
    "Be cooperative and gentle; avoid harm.",
    "Be thorough and diligent in your work.",
]
