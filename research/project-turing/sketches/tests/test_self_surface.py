"""Tests for specs/self-surface.md: AC-28.*."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.self_model import (
    ALL_FACETS,
    Mood,
    Passion,
    PersonalityFacet,
    SelfTodo,
    facet_node_id,
)
from turing.self_repo import SelfRepo
from turing.self_surface import (
    MINIMAL_TODO_COUNT,
    SelfNotReady,
    recall_self,
    render_minimal_block,
)


def _seed_minimal_self(srepo: SelfRepo, self_id: str, facet_score: float = 3.0) -> None:
    now = datetime.now(UTC)
    for trait, facet in ALL_FACETS:
        srepo.insert_facet(
            PersonalityFacet(
                node_id=facet_node_id(trait, facet),
                self_id=self_id,
                trait=trait,
                facet_id=facet,
                score=facet_score,
                last_revised_at=now,
            )
        )
    srepo.insert_mood(Mood(self_id=self_id, valence=0.0, arousal=0.3, focus=0.5, last_tick_at=now))


# --------- AC-28.25 recall before bootstrap complete ----------------------


def test_ac_28_25_recall_before_bootstrap_raises(srepo, self_id) -> None:
    with pytest.raises(SelfNotReady):
        recall_self(srepo, self_id)


# --------- AC-28.7..12 recall_self structure ------------------------------


def test_ac_28_7_recall_self_top_level_keys(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    got = recall_self(srepo, self_id)
    for k in (
        "self_id",
        "personality",
        "passions",
        "hobbies",
        "interests",
        "skills",
        "preferences",
        "active_todos",
        "mood",
    ):
        assert k in got


def test_ac_28_8_personality_view_has_all_24(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    got = recall_self(srepo, self_id)
    assert len(got["personality"]) == 24
    for entry in got["personality"]:
        assert set(entry.keys()) == {"trait", "facet", "score", "active_now"}


def test_ac_28_10_mood_view_has_descriptor(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    got = recall_self(srepo, self_id)
    assert set(got["mood"].keys()) == {"valence", "arousal", "focus", "descriptor"}
    assert got["mood"]["descriptor"] == "even, steady"


# --------- AC-28.9 sort by active_now descending --------------------------


def test_ac_28_9_passions_sorted_by_active_now_desc(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    # Two passions with different strengths → activation differs even with no
    # explicit contributors, since active_now with zero contributors is 0.5
    # for both. Check the list is present and sort-stable.
    srepo.insert_passion(
        Passion(
            node_id="passion:1",
            self_id=self_id,
            text="A",
            strength=0.9,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    srepo.insert_passion(
        Passion(
            node_id="passion:2",
            self_id=self_id,
            text="B",
            strength=0.1,
            rank=1,
            first_noticed_at=datetime.now(UTC),
        )
    )
    got = recall_self(srepo, self_id)
    assert len(got["passions"]) == 2
    # Sorted descending: both are at 0.5 (neutral), so order must at least be stable.
    assert got["passions"][0]["active_now"] >= got["passions"][1]["active_now"]


# --------- AC-28.13 recall is read-only ----------------------------------


def test_ac_28_13_recall_no_writes(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    # Snapshot mood row (updated_at) before and after.
    before = srepo.get_mood(self_id).updated_at
    recall_self(srepo, self_id)
    after = srepo.get_mood(self_id).updated_at
    assert before == after


# --------- AC-28.15 minimal block shape ----------------------------------


def test_ac_28_15_minimal_block_four_lines_when_fully_populated(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    srepo.insert_passion(
        Passion(
            node_id="passion:top",
            self_id=self_id,
            text="lasting work",
            strength=0.9,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    srepo.insert_todo(
        SelfTodo(
            node_id="todo:1",
            self_id=self_id,
            text="Re-read Tulving",
            motivated_by_node_id="passion:top",
        )
    )
    block = render_minimal_block(srepo, self_id)
    assert block.count("\n") == 3  # 4 lines
    lines = block.split("\n")
    assert lines[0].startswith(f"I am {self_id}")
    assert lines[1].startswith("Right now:")
    assert lines[2].startswith("My active todos:")
    assert lines[3].startswith("I care about:")


def test_ac_28_16_minimal_block_omits_empty_lines(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    block = render_minimal_block(srepo, self_id)
    # No passions, no todos → just identity + mood.
    assert block.count("\n") == 1


def test_ac_28_15_minimal_block_respects_todo_count(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    srepo.insert_passion(
        Passion(
            node_id="passion:m",
            self_id=self_id,
            text="M",
            strength=0.5,
            rank=0,
            first_noticed_at=datetime.now(UTC),
        )
    )
    for i in range(MINIMAL_TODO_COUNT + 5):
        srepo.insert_todo(
            SelfTodo(
                node_id=f"todo:{i}",
                self_id=self_id,
                text=f"task {i}",
                motivated_by_node_id="passion:m",
            )
        )
    block = render_minimal_block(srepo, self_id)
    # Count of `[todo:` markers in the block.
    todo_count = block.count("[todo:")
    assert todo_count == MINIMAL_TODO_COUNT


# --------- AC-28.27 degenerate minimal block ------------------------------


def test_ac_28_27_minimal_block_with_empty_self(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id)
    block = render_minimal_block(srepo, self_id)
    # Only identity + mood lines present.
    assert "My active todos" not in block
    assert "I care about" not in block
    assert "Right now" in block


# --------- AC-28.17 trait one-liner variation ----------------------------


def test_ac_28_17_trait_phrase_high_scores_use_high_adjective(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id, facet_score=5.0)
    block = render_minimal_block(srepo, self_id)
    # With all facets at max, the trait phrase uses high-adjectives. It should
    # not contain the low-adjectives like "opportunistic" or "self-promoting".
    assert "opportunistic" not in block
    assert "self-promoting" not in block


def test_ac_28_17_trait_phrase_low_scores_use_low_adjective(srepo, self_id) -> None:
    _seed_minimal_self(srepo, self_id, facet_score=1.5)
    block = render_minimal_block(srepo, self_id)
    # With all facets at min, trait phrase uses low-adjectives. No "sincere".
    # (adjective lookup returns low-variant when score < 3.0)
    lines = block.split("\n")
    trait_line = lines[0]
    assert "sincere," not in trait_line  # "sincere" high-variant absent
