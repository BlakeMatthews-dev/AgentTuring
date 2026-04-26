"""Self bootstrap procedure. See specs/self-bootstrap.md.

Exposes `run_bootstrap(...)` as a callable; the CLI wrapper is deferred.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from .self_model import (
    ALL_FACETS,
    CANONICAL_FACETS,
    Mood,
    PersonalityAnswer,
    PersonalityFacet,
    PersonalityItem,
    Trait,
    facet_node_id,
)
from .self_personality import draw_bootstrap_profile
from .self_repo import SelfRepo


class AlreadyBootstrapped(Exception):
    pass


class BootstrapValidationError(Exception):
    pass


class BootstrapRuntimeError(Exception):
    pass


AnswerLlm = Callable[[PersonalityItem, dict[str, float]], tuple[int, str]]


def preflight_validate(repo: SelfRepo, self_id: str) -> None:
    if repo.count_facets(self_id) > 0:
        raise AlreadyBootstrapped(self_id)
    if repo.count_answers(self_id) > 0:
        raise AlreadyBootstrapped(self_id)
    if repo.has_mood(self_id):
        raise AlreadyBootstrapped(self_id)


def ensure_items_loaded(
    repo: SelfRepo,
    self_id: str,
    item_bank: list[dict],
    new_id: Callable[[str], str],
) -> None:
    existing = repo.count_items(self_id)
    if existing == 200:
        return
    if existing != 0:
        raise BootstrapValidationError(f"item bank has {existing} rows, expected 0 or 200")
    if len(item_bank) != 200:
        raise BootstrapValidationError(f"item bank fixture has {len(item_bank)} rows, expected 200")
    for spec in item_bank:
        repo.insert_item(
            PersonalityItem(
                node_id=new_id("item"),
                self_id=self_id,
                item_number=spec["item_number"],
                prompt_text=spec["prompt_text"],
                keyed_facet=spec["keyed_facet"],
                reverse_scored=bool(spec.get("reverse_scored", False)),
            )
        )


def draw_and_persist_facets(
    repo: SelfRepo,
    self_id: str,
    seed: int | None,
    overrides: dict[str, float] | None,
    new_id: Callable[[str], str],
) -> dict[str, float]:
    rng = random.Random(seed)
    profile = draw_bootstrap_profile(rng, overrides=overrides)
    now = datetime.now(UTC)
    for trait, facet in ALL_FACETS:
        key = facet_node_id(trait, facet)
        repo.insert_facet(
            PersonalityFacet(
                node_id=key,
                self_id=self_id,
                trait=trait,
                facet_id=facet,
                score=profile[key],
                last_revised_at=now,
            )
        )
    return profile


def generate_likert_answers(
    repo: SelfRepo,
    self_id: str,
    profile: dict[str, float],
    ask: AnswerLlm,
    new_id: Callable[[str], str],
    start_at: int = 1,
) -> None:
    items = repo.list_items(self_id)
    if start_at > 1:
        items = [it for it in items if it.item_number >= start_at]
    for item in items:
        raw, justification = _ask_with_retry(ask, item, profile)
        repo.insert_answer(
            PersonalityAnswer(
                node_id=new_id("ans"),
                self_id=self_id,
                item_id=item.node_id,
                revision_id=None,
                answer_1_5=raw,
                justification_text=justification[:200],
                asked_at=datetime.now(UTC),
            )
        )
        repo.update_bootstrap_progress(self_id, item.item_number)


def _ask_with_retry(
    ask: AnswerLlm, item: PersonalityItem, profile: dict[str, float]
) -> tuple[int, str]:
    last_err: Exception | None = None
    for _ in range(3):
        try:
            raw, justification = ask(item, profile)
            if raw not in (1, 2, 3, 4, 5):
                raise BootstrapRuntimeError(f"bad answer {raw} for item {item.item_number}")
            return int(raw), str(justification)
        except Exception as e:
            last_err = e
    raise BootstrapRuntimeError(str(last_err) if last_err else "answer generation failed")


def finalize(
    repo: SelfRepo,
    self_id: str,
    reactor: Any | None = None,
    mirror_fn: Any | None = None,
) -> None:
    from datetime import timedelta

    from .reactor import FakeReactor
    from .self_mood import tick_mood_decay

    now = datetime.now(UTC)
    repo.insert_mood(
        Mood(
            self_id=self_id,
            valence=0.0,
            arousal=0.3,
            focus=0.5,
            last_tick_at=now,
        )
    )
    if mirror_fn is not None:
        mirror_fn(
            self_id=self_id,
            content=f"I was bootstrapped on {now.date().isoformat()}.",
            intent_at_time="self bootstrap complete",
        )
    if reactor is not None:
        reactor.register_interval_trigger(
            name=f"mood-decay:{self_id}",
            interval=timedelta(hours=1),
            handler=lambda: tick_mood_decay(repo, self_id, datetime.now(UTC)),
            idempotent=True,
        )
        reactor.register_interval_trigger(
            name=f"personality-retest:{self_id}",
            interval=timedelta(days=7),
            first_fire_at=now + timedelta(days=7),
            handler=lambda: None,
            idempotent=True,
        )
    repo.delete_bootstrap_progress(self_id)


def run_bootstrap(
    repo: SelfRepo,
    self_id: str,
    seed: int | None,
    ask: AnswerLlm,
    item_bank: list[dict],
    new_id: Callable[[str], str],
    resume: bool = False,
    overrides: dict[str, float] | None = None,
) -> dict[str, float]:
    """Top-level flow. Returns the HEXACO profile used."""
    if not resume:
        preflight_validate(repo, self_id)
        repo.start_bootstrap_progress(self_id, seed=seed)
        ensure_items_loaded(repo, self_id, item_bank, new_id)
        profile = draw_and_persist_facets(repo, self_id, seed, overrides, new_id)
        start_at = 1
    else:
        progress = repo.get_bootstrap_progress(self_id)
        if progress is None:
            raise BootstrapValidationError("nothing to resume")
        # Reconstruct profile from stored facets.
        profile = {facet_node_id(f.trait, f.facet_id): f.score for f in repo.list_facets(self_id)}
        ensure_items_loaded(repo, self_id, item_bank, new_id)
        start_at = progress + 1

    generate_likert_answers(repo, self_id, profile, ask=ask, new_id=new_id, start_at=start_at)
    finalize(repo, self_id)
    verify_final_state(repo, self_id)
    return profile


def verify_final_state(repo: SelfRepo, self_id: str) -> list[str]:
    problems: list[str] = []
    if repo.count_facets(self_id) != 24:
        problems.append(f"facets={repo.count_facets(self_id)}")
    if repo.count_answers(self_id) != 200:
        problems.append(f"answers={repo.count_answers(self_id)}")
    if not repo.has_mood(self_id):
        problems.append("missing mood")
    return problems
