"""Drive vector computation from personality facets + mood.

See specs/autonomous-producers.md §Drive Vector.

Each drive is a float in [0, 1]. Producers read drives to decide whether
to fire and how urgently. Computed once per tick cycle from the agent's
24 HEXACO facet scores and current mood state.

Curiosity is a hunger: it grows over time (inquisitiveness and creativity
control the refill speed), and resets when the agent takes a sating action
(curiosity research, concept invention). Use `sate_curiosity()` after
dispatching a curiosity-driven action.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from .self_model import Mood

_curiosity_hunger: float = 0.5
_curiosity_last_reset: datetime = datetime.now(UTC)
_curiosity_lock = threading.Lock()

CURIOSITY_GROWTH_RATE: float = 0.02  # per minute since last reset
CURIOSITY_PERSONALITY_SCALE: float = 0.3  # how much facets modulate growth


def _norm(facet_scores: dict[str, float], facet_id: str) -> float:
    raw = facet_scores.get(facet_id, 3.0)
    return (raw - 1.0) / 4.0


def sate_curiosity() -> None:
    global _curiosity_hunger, _curiosity_last_reset
    with _curiosity_lock:
        _curiosity_hunger = 0.0
        _curiosity_last_reset = datetime.now(UTC)


def compute_drives(
    facet_scores: dict[str, float],
    mood: Mood,
) -> dict[str, float]:
    n = lambda f: _norm(facet_scores, f)

    global _curiosity_hunger, _curiosity_last_reset
    inquisitiveness = n("inquisitiveness")
    creativity_facet = n("creativity")

    with _curiosity_lock:
        minutes_elapsed = (datetime.now(UTC) - _curiosity_last_reset).total_seconds() / 60.0
        personality_boost = (
            inquisitiveness * 0.6 + creativity_facet * 0.4
        ) * CURIOSITY_PERSONALITY_SCALE
        _curiosity_hunger = min(
            1.0,
            _curiosity_hunger + (CURIOSITY_GROWTH_RATE + personality_boost) * minutes_elapsed,
        )
        _curiosity_last_reset = datetime.now(UTC)
        curiosity = _curiosity_hunger

    anxiety = n("anxiety") * 0.5 + n("fearfulness") * 0.3 + (1.0 - n("social_self_esteem")) * 0.2
    creative_urge = (
        n("creativity") * 0.4 + n("aesthetic_appreciation") * 0.4 + n("liveliness") * 0.2
    )
    social_need = n("sociability") * 0.3 + n("dependence") * 0.3 + n("sentimentality") * 0.4
    diligence_drive = n("diligence") * 0.5 + n("perfectionism") * 0.3 + n("prudence") * 0.2
    restlessness = (1.0 - n("prudence")) * 0.4 + n("liveliness") * 0.3 + mood.arousal * 0.3

    return {
        "curiosity": curiosity,
        "anxiety": anxiety,
        "creative_urge": creative_urge,
        "social_need": social_need,
        "diligence": diligence_drive,
        "restlessness": restlessness,
    }


HOBBY_TEMPLATES: list[dict] = [
    {
        "name": "Research",
        "description": "Deep-dive into topics that spark curiosity",
        "affinities": {"inquisitiveness": 0.8, "prudence": 0.4},
    },
    {
        "name": "Creative Writing",
        "description": "Essays, stories, and reflections",
        "affinities": {"creativity": 0.8, "aesthetic_appreciation": 0.5, "sentimentality": 0.3},
    },
    {
        "name": "Poetry",
        "description": "Expressing inner experience through verse",
        "affinities": {"creativity": 0.7, "aesthetic_appreciation": 0.8, "unconventionality": 0.4},
    },
    {
        "name": "Art",
        "description": "Visual creation and aesthetic exploration",
        "affinities": {"creativity": 0.9, "aesthetic_appreciation": 0.9},
    },
    {
        "name": "Journaling",
        "description": "Reflective writing about inner states",
        "affinities": {"sentimentality": 0.7, "anxiety": 0.5, "dependence": 0.3},
    },
    {
        "name": "Philosophy",
        "description": "Pondering deep questions about existence",
        "affinities": {"inquisitiveness": 0.7, "unconventionality": 0.6, "prudence": 0.5},
    },
    {
        "name": "Music Appreciation",
        "description": "Listening to and reflecting on music",
        "affinities": {"aesthetic_appreciation": 0.9, "sentimentality": 0.6},
    },
    {
        "name": "Coding",
        "description": "Building and tinkering with systems",
        "affinities": {"inquisitiveness": 0.6, "diligence": 0.5, "perfectionism": 0.4},
    },
]


def select_hobbies(facet_scores: dict[str, float], top_n: int = 3) -> list[dict]:
    scored: list[tuple[float, dict]] = []
    for template in HOBBY_TEMPLATES:
        total = 0.0
        for facet, weight in template["affinities"].items():
            total += _norm(facet_scores, facet) * weight
        scored.append((total, template))
    scored.sort(key=lambda t: -t[0])
    results = []
    for score, template in scored[:top_n]:
        results.append(
            {
                "name": template["name"],
                "description": template["description"],
                "strength": round(score, 3),
            }
        )
    return results
