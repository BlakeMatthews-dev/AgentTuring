"""Make `turing` importable from the sketches directory."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

_SKETCHES = Path(__file__).resolve().parent.parent
if str(_SKETCHES) not in sys.path:
    sys.path.insert(0, str(_SKETCHES))

from turing.repo import Repo  # noqa: E402
from turing.self_repo import SelfRepo  # noqa: E402
from turing.self_identity import bootstrap_self_id  # noqa: E402
from turing.self_model import (
    ALL_FACETS,
    Mood,
    PersonalityFacet,
    PersonalityAnswer,
    PersonalityItem,
    facet_node_id,
)  # noqa: E402


@pytest.fixture
def repo() -> Repo:
    r = Repo(None)
    yield r
    r.close()


@pytest.fixture
def self_id(repo: Repo) -> str:
    return bootstrap_self_id(repo.conn)


@pytest.fixture
def bootstrapped_id(repo: Repo, srepo: SelfRepo, new_id) -> str:
    sid = bootstrap_self_id(repo.conn)
    now = datetime.now(UTC)
    for trait, facet in ALL_FACETS:
        srepo.insert_facet(
            PersonalityFacet(
                node_id=facet_node_id(trait, facet),
                self_id=sid,
                trait=trait,
                facet_id=facet,
                score=3.0,
                last_revised_at=now,
            )
        )
    for i in range(200):
        facet_names = [f for _, f in ALL_FACETS]
        facet = facet_names[i % len(facet_names)]
        item_id = f"item:{i + 1}"
        srepo.insert_item(
            PersonalityItem(
                node_id=item_id,
                self_id=sid,
                item_number=i + 1,
                prompt_text=f"Q{i + 1}",
                keyed_facet=facet,
                reverse_scored=False,
            )
        )
        srepo.insert_answer(
            PersonalityAnswer(
                node_id=f"ans:{i + 1}",
                self_id=sid,
                item_id=item_id,
                revision_id=None,
                answer_1_5=3,
                justification_text="",
                asked_at=now,
            )
        )
    srepo.insert_mood(Mood(self_id=sid, valence=0.0, arousal=0.3, focus=0.5, last_tick_at=now))
    return sid


@pytest.fixture
def srepo(repo: Repo) -> SelfRepo:
    return SelfRepo(repo.conn)


@pytest.fixture
def new_id():
    counter = {"n": 0}

    def _mk(prefix: str) -> str:
        counter["n"] += 1
        return f"{prefix}:{counter['n']}"

    return _mk
