"""Tool handlers for accreting passions / hobbies / interests / preferences / skills.

See specs/self-nodes.md.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime

from .self_model import (
    ActivationContributor,
    ContributorOrigin,
    DEFAULT_DECAY_RATES,
    Hobby,
    Interest,
    NodeKind,
    Passion,
    Preference,
    PreferenceKind,
    Skill,
    SkillKind,
    guess_node_kind,
)
from .self_repo import SelfRepo
from .self_surface import _require_ready


def _now() -> datetime:
    return datetime.now(UTC)


def note_passion(
    repo: SelfRepo,
    self_id: str,
    text: str,
    strength: float,
    new_id: Callable[[str], str],
    contributes_to: list[tuple[str, float]] | None = None,
) -> Passion:
    _require_ready(repo, self_id)
    _reject_dupe_text(repo.list_passions(self_id), lambda p: p.text, text, kind="passion")
    rank = repo.max_passion_rank(self_id) + 1
    p = Passion(
        node_id=new_id("passion"),
        self_id=self_id,
        text=text,
        strength=strength,
        rank=rank,
        first_noticed_at=_now(),
    )
    repo.insert_passion(p)
    _wire(repo, self_id, p.node_id, NodeKind.PASSION, contributes_to, new_id)
    return p


def note_hobby(
    repo: SelfRepo,
    self_id: str,
    name: str,
    description: str,
    new_id: Callable[[str], str],
    contributes_to: list[tuple[str, float]] | None = None,
) -> Hobby:
    _require_ready(repo, self_id)
    _reject_dupe_text(repo.list_hobbies(self_id), lambda h: h.name, name, kind="hobby")
    h = Hobby(
        node_id=new_id("hobby"),
        self_id=self_id,
        name=name,
        description=description,
    )
    try:
        repo.insert_hobby(h)
    except sqlite3.IntegrityError as e:
        raise ValueError(f"duplicate hobby: {name}") from e
    _wire(repo, self_id, h.node_id, NodeKind.HOBBY, contributes_to, new_id)
    return h


def note_interest(
    repo: SelfRepo,
    self_id: str,
    topic: str,
    description: str,
    new_id: Callable[[str], str],
    contributes_to: list[tuple[str, float]] | None = None,
) -> Interest:
    _require_ready(repo, self_id)
    _reject_dupe_text(repo.list_interests(self_id), lambda i: i.topic, topic, kind="interest")
    i = Interest(
        node_id=new_id("interest"),
        self_id=self_id,
        topic=topic,
        description=description,
    )
    try:
        repo.insert_interest(i)
    except sqlite3.IntegrityError as e:
        raise ValueError(f"duplicate interest: {topic}") from e
    _wire(repo, self_id, i.node_id, NodeKind.INTEREST, contributes_to, new_id)
    return i


def note_preference(
    repo: SelfRepo,
    self_id: str,
    kind: PreferenceKind,
    target: str,
    strength: float,
    rationale: str,
    new_id: Callable[[str], str],
    contributes_to: list[tuple[str, float]] | None = None,
) -> Preference:
    _require_ready(repo, self_id)
    existing = [p for p in repo.list_preferences(self_id) if p.kind == kind and p.target == target]
    if existing:
        raise ValueError(f"duplicate preference: ({kind}, {target})")
    p = Preference(
        node_id=new_id("pref"),
        self_id=self_id,
        kind=kind,
        target=target,
        strength=strength,
        rationale=rationale,
    )
    repo.insert_preference(p)
    _wire(repo, self_id, p.node_id, NodeKind.PREFERENCE, contributes_to, new_id)
    return p


def note_skill(
    repo: SelfRepo,
    self_id: str,
    name: str,
    level: float,
    kind: SkillKind,
    new_id: Callable[[str], str],
    decay_rate_per_day: float | None = None,
    contributes_to: list[tuple[str, float]] | None = None,
) -> Skill:
    _require_ready(repo, self_id)
    existing = [
        s for s in repo.list_skills(self_id) if s.name.strip().lower() == name.strip().lower()
    ]
    if existing:
        raise ValueError(f"duplicate skill: {name}")
    s = Skill(
        node_id=new_id("skill"),
        self_id=self_id,
        name=name,
        kind=kind,
        stored_level=level,
        decay_rate_per_day=(
            decay_rate_per_day if decay_rate_per_day is not None else DEFAULT_DECAY_RATES[kind]
        ),
        last_practiced_at=_now(),
    )
    repo.insert_skill(s)
    _wire(repo, self_id, s.node_id, NodeKind.SKILL, contributes_to, new_id)
    return s


def practice_skill(
    repo: SelfRepo,
    self_id: str,
    skill_id: str,
    new_level: float | None = None,
    notes: str = "",
) -> Skill:
    s = repo.get_skill(skill_id)
    if s.self_id != self_id:
        raise PermissionError("cross-self practice forbidden")
    _require_ready(repo, self_id)
    if new_level is not None:
        if new_level < s.stored_level:
            raise ValueError("practice_skill cannot lower stored_level; use downgrade_skill")
        if not 0.0 <= new_level <= 1.0:
            raise ValueError("new_level out of range")
        s.stored_level = new_level
    s.last_practiced_at = _now()
    repo.update_skill(s)
    return s


def downgrade_skill(
    repo: SelfRepo,
    self_id: str,
    skill_id: str,
    new_level: float,
    reason: str,
) -> Skill:
    s = repo.get_skill(skill_id)
    if s.self_id != self_id:
        raise PermissionError("cross-self downgrade forbidden")
    _require_ready(repo, self_id)
    if not 0.0 <= new_level <= 1.0:
        raise ValueError("new_level out of range")
    if not reason.strip():
        raise ValueError("reason is required for downgrade")
    s.stored_level = new_level
    repo.update_skill(s)
    return s


def rerank_passions(
    repo: SelfRepo,
    self_id: str,
    ordered_ids: list[str],
) -> list[Passion]:
    _require_ready(repo, self_id)
    existing = repo.list_passions(self_id)
    existing_ids = {p.node_id for p in existing}
    order_set = set(ordered_ids)
    if existing_ids != order_set:
        raise ValueError(
            f"ordered_ids must match current passions exactly; "
            f"missing={existing_ids - order_set}, extra={order_set - existing_ids}"
        )
    # Two-phase: move everyone to ranks offset by +len(existing) to avoid UNIQUE
    # constraint collisions, then down to the target.
    by_id = {p.node_id: p for p in existing}
    offset = len(existing) + 10
    for i, pid in enumerate(ordered_ids):
        p = by_id[pid]
        p.rank = i + offset
        repo.update_passion(p)
    for i, pid in enumerate(ordered_ids):
        p = by_id[pid]
        p.rank = i
        repo.update_passion(p)
    return repo.list_passions(self_id)


def _reject_dupe_text(existing: list, extract, text: str, kind: str) -> None:
    normalized = " ".join(text.strip().lower().split())
    for row in existing:
        candidate = " ".join(extract(row).strip().lower().split())
        if candidate == normalized:
            raise ValueError(f"duplicate {kind}: {text!r}")


def _wire(
    repo: SelfRepo,
    self_id: str,
    source_node_id: str,
    source_kind: NodeKind,
    contributes_to: list[tuple[str, float]] | None,
    new_id: Callable[[str], str],
) -> None:
    if not contributes_to:
        return
    for target, weight in contributes_to:
        repo.insert_contributor(
            ActivationContributor(
                node_id=new_id("contrib"),
                self_id=self_id,
                target_node_id=target,
                target_kind=NodeKind.PERSONALITY_FACET
                if target.startswith("facet:")
                else guess_node_kind(target),
                source_id=source_node_id,
                source_kind=source_kind.value,
                weight=weight,
                origin=ContributorOrigin.SELF,
                rationale=f"{source_kind.value} contributes",
            )
        )
