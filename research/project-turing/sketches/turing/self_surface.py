"""Self-surface: minimal prompt block, recall_self(), tool registry stub.

See specs/self-surface.md.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .self_activation import ActivationContext, active_now
from .self_model import (
    FACET_TO_TRAIT,
    current_level,
    Mood,
    PersonalityFacet,
)
from .self_mood import mood_descriptor
from .self_repo import SelfRepo


class SelfNotReady(Exception):
    pass


def _bootstrap_complete(repo: SelfRepo, self_id: str) -> bool:
    return (
        repo.count_facets(self_id) == 24
        and repo.count_answers(self_id) == 200
        and repo.has_mood(self_id)
    )


def _require_ready(repo: SelfRepo, self_id: str) -> None:
    if not _bootstrap_complete(repo, self_id):
        raise SelfNotReady(self_id)


RECALL_TOKEN_BUDGET: int = 4000
MINIMAL_TODO_COUNT: int = 5
MINIMAL_TOKEN_CEILING: int = 120


# High-adjective / low-adjective per facet (for trait one-liner).
TRAIT_ADJECTIVES: dict[str, tuple[str, str]] = {
    "sincerity": ("sincere", "strategic"),
    "fairness": ("fair-minded", "opportunistic"),
    "greed_avoidance": ("unacquisitive", "acquisitive"),
    "modesty": ("modest", "self-promoting"),
    "fearfulness": ("cautious", "bold"),
    "anxiety": ("prone-to-worry", "calm"),
    "dependence": ("attachment-seeking", "self-reliant"),
    "sentimentality": ("tender", "unsentimental"),
    "social_self_esteem": ("confident", "self-doubting"),
    "social_boldness": ("socially bold", "reserved"),
    "sociability": ("sociable", "solitary"),
    "liveliness": ("lively", "subdued"),
    "forgiveness": ("forgiving", "grudge-holding"),
    "gentleness": ("gentle", "critical"),
    "flexibility": ("flexible", "inflexible"),
    "patience": ("patient", "quick-tempered"),
    "organization": ("organized", "loose"),
    "diligence": ("diligent", "easygoing"),
    "perfectionism": ("perfectionist", "satisficing"),
    "prudence": ("prudent", "impulsive"),
    "aesthetic_appreciation": ("aesthetically attuned", "pragmatic"),
    "inquisitiveness": ("inquisitive", "disinterested"),
    "creativity": ("creative", "conventional"),
    "unconventionality": ("unconventional", "conventional"),
}
assert set(TRAIT_ADJECTIVES.keys()) == set(FACET_TO_TRAIT.keys())


def recall_self(repo: SelfRepo, self_id: str) -> dict:
    if repo.count_facets(self_id) != 24:
        raise SelfNotReady(self_id)
    ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))

    personality = []
    for f in sorted(repo.list_facets(self_id), key=lambda x: x.facet_id):
        personality.append(
            {
                "trait": f.trait.value,
                "facet": f.facet_id,
                "score": f.score,
                "active_now": active_now(repo, f.node_id, ctx),
            }
        )

    passions = [
        {
            "node_id": p.node_id,
            "text": p.text,
            "strength": p.strength,
            "rank": p.rank,
            "active_now": active_now(repo, p.node_id, ctx),
        }
        for p in repo.list_passions(self_id)
    ]
    passions.sort(key=lambda p: p["active_now"], reverse=True)

    hobbies = [
        {
            "node_id": h.node_id,
            "name": h.name,
            "last_engaged_at": h.last_engaged_at.isoformat() if h.last_engaged_at else None,
            "active_now": active_now(repo, h.node_id, ctx),
        }
        for h in repo.list_hobbies(self_id)
    ]
    hobbies.sort(key=lambda h: h["active_now"], reverse=True)

    interests = [
        {
            "node_id": i.node_id,
            "topic": i.topic,
            "active_now": active_now(repo, i.node_id, ctx),
        }
        for i in repo.list_interests(self_id)
    ]
    interests.sort(key=lambda i: i["active_now"], reverse=True)

    skills = []
    for s in repo.list_skills(self_id):
        skills.append(
            {
                "node_id": s.node_id,
                "name": s.name,
                "kind": s.kind.value,
                "stored_level": s.stored_level,
                "current_level": current_level(s, ctx.now),
                "active_now": active_now(repo, s.node_id, ctx),
            }
        )
    skills.sort(key=lambda s: s["active_now"], reverse=True)

    preferences = [
        {
            "node_id": p.node_id,
            "kind": p.kind.value,
            "target": p.target,
            "strength": p.strength,
            "active_now": active_now(repo, p.node_id, ctx),
        }
        for p in repo.list_preferences(self_id)
    ]
    preferences.sort(key=lambda p: p["active_now"], reverse=True)

    active_todos = [
        {
            "node_id": t.node_id,
            "text": t.text,
            "motivated_by": t.motivated_by_node_id,
        }
        for t in repo.list_active_todos(self_id)
    ]

    mood = repo.get_mood(self_id)
    mood_view = {
        "valence": mood.valence,
        "arousal": mood.arousal,
        "focus": mood.focus,
        "descriptor": mood_descriptor(mood),
    }

    return {
        "self_id": self_id,
        "personality": personality,
        "passions": passions,
        "hobbies": hobbies,
        "interests": interests,
        "skills": skills,
        "preferences": preferences,
        "active_todos": active_todos,
        "mood": mood_view,
    }


def trait_phrase_top3(repo: SelfRepo, self_id: str, ctx: ActivationContext) -> str:
    facets = sorted(
        repo.list_facets(self_id),
        key=lambda f: active_now(repo, f.node_id, ctx),
        reverse=True,
    )[:3]
    parts: list[str] = []
    for f in facets:
        high, low = TRAIT_ADJECTIVES[f.facet_id]
        parts.append(high if f.score >= 3.0 else low)
    return ", ".join(parts)


def render_minimal_block(repo: SelfRepo, self_id: str) -> str:
    if repo.count_facets(self_id) != 24:
        raise SelfNotReady(self_id)
    ctx = ActivationContext(self_id=self_id, now=datetime.now(UTC))
    lines: list[str] = [f"I am {self_id} ({trait_phrase_top3(repo, self_id, ctx)})."]

    mood = repo.get_mood(self_id)
    lines.append(f"Right now: {mood_descriptor(mood)}.")

    todos = repo.list_active_todos(self_id)[:MINIMAL_TODO_COUNT]
    if todos:
        rendered = "; ".join(f"[todo:{t.node_id}] {t.text}" for t in todos)
        lines.append(f"My active todos: {rendered}.")

    top = repo.top_passion(self_id)
    if top and top.strength > 0:
        lines.append(f"I care about: {top.text}.")

    block = "\n".join(lines)
    while _approx_tokens(block) > MINIMAL_TOKEN_CEILING and lines:
        if any(l.startswith("My active todos:") for l in lines):
            lines = [l for l in lines if not l.startswith("My active todos:")]
        elif any(l.startswith("I care about:") for l in lines):
            lines = [l for l in lines if not l.startswith("I care about:")]
        else:
            break
        block = "\n".join(lines)
    return block


def _approx_tokens(text: str) -> int:
    # Crude: whitespace tokens. The prompt is tiny enough that precision doesn't matter.
    return len(text.split())
