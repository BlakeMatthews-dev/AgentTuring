"""Tests for specs/self-bootstrap.md: AC-29.*."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from turing.repo import Repo
from turing.self_bootstrap import (
    AlreadyBootstrapped,
    BootstrapRuntimeError,
    BootstrapValidationError,
    run_bootstrap,
)
from turing.self_identity import bootstrap_self_id
from turing.self_model import ALL_FACETS
from turing.self_repo import SelfRepo


def _make_item_bank() -> list[dict]:
    """Exactly 200 items, facet-balanced across the 24 facets."""
    bank: list[dict] = []
    facet_names = [f for _, f in ALL_FACETS]
    for i in range(200):
        facet = facet_names[i % len(facet_names)]
        bank.append(
            {
                "item_number": i + 1,
                "prompt_text": f"I am {facet} ({i}).",
                "keyed_facet": facet,
                "reverse_scored": (i % 3 == 0),
            }
        )
    return bank


def _deterministic_ask(item, profile) -> tuple[int, str]:
    # Answer 3 for everything, with a short justification.
    return (3, "neutral tick")


# --------- AC-29.4 pre-flight: already bootstrapped raises ---------------


def test_ac_29_4_preflight_rejects_rebootstrap(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()
    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=42,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
    )
    with pytest.raises(AlreadyBootstrapped):
        run_bootstrap(
            repo=srepo,
            self_id=self_id,
            seed=42,
            ask=_deterministic_ask,
            item_bank=bank,
            new_id=new_id,
        )


# --------- AC-29.6..8 item bank load -------------------------------------


def test_ac_29_6_bank_wrong_size_raises(srepo, self_id, new_id) -> None:
    with pytest.raises(BootstrapValidationError, match="200"):
        run_bootstrap(
            repo=srepo,
            self_id=self_id,
            seed=1,
            ask=_deterministic_ask,
            item_bank=_make_item_bank()[:199],
            new_id=new_id,
        )


def test_ac_29_6_bank_loaded_once(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()
    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=1,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
    )
    assert srepo.count_items(self_id) == 200


# --------- AC-29.9..10 facet draw determinism ----------------------------


def test_ac_29_10_draw_deterministic_under_seed(srepo, new_id) -> None:
    bank = _make_item_bank()
    sid1 = bootstrap_self_id(srepo.conn)
    run_bootstrap(
        repo=srepo,
        self_id=sid1,
        seed=123,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
    )
    profile1 = {f.facet_id: f.score for f in srepo.list_facets(sid1)}

    _r2 = Repo(None)
    srepo2 = SelfRepo(_r2.conn)
    sid2 = bootstrap_self_id(srepo2.conn)
    run_bootstrap(
        repo=srepo2,
        self_id=sid2,
        seed=123,
        ask=_deterministic_ask,
        item_bank=_make_item_bank(),
        new_id=new_id,
    )
    profile2 = {f.facet_id: f.score for f in srepo2.list_facets(sid2)}
    assert profile1 == profile2
    _r2.close()


# --------- AC-29.11 retry on bad LLM answer -----------------------------


def test_ac_29_11_retry_then_succeed(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()
    state = {"calls": 0}

    def flaky(item, profile):
        state["calls"] += 1
        # Fail twice on the 50th item, then succeed.
        if item.item_number == 50 and state["calls"] % 3 != 0:
            return (99, "bad")
        return (4, "ok")

    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=flaky,
        item_bank=bank,
        new_id=new_id,
    )
    assert srepo.count_answers(self_id) == 200


def test_ac_29_11_fourth_failure_aborts(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()

    def always_bad(item, profile):
        if item.item_number == 50:
            return (99, "bad")
        return (3, "ok")

    with pytest.raises(BootstrapRuntimeError):
        run_bootstrap(
            repo=srepo,
            self_id=self_id,
            seed=0,
            ask=always_bad,
            item_bank=bank,
            new_id=new_id,
        )


# --------- AC-29.13 resume -----------------------------------------------


def test_ac_29_13_resume_continues_from_checkpoint(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()

    def halt_at_87(item, profile):
        if item.item_number >= 88:
            raise BootstrapRuntimeError("simulated crash")
        return (3, "ok")

    with pytest.raises(BootstrapRuntimeError):
        run_bootstrap(
            repo=srepo,
            self_id=self_id,
            seed=0,
            ask=halt_at_87,
            item_bank=bank,
            new_id=new_id,
        )
    # Progress should be 87.
    assert srepo.get_bootstrap_progress(self_id) == 87
    # Resume with a good ask; expect 200 answers.
    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
        resume=True,
    )
    assert srepo.count_answers(self_id) == 200


# --------- AC-29.15..18 final state --------------------------------------


def test_ac_29_15_finalize_sets_neutral_mood(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()
    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
    )
    m = srepo.get_mood(self_id)
    assert (m.valence, m.arousal, m.focus) == (0.0, 0.3, 0.5)


def test_ac_29_18_bootstrap_progress_cleared(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()
    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
    )
    assert srepo.get_bootstrap_progress(self_id) is None


def test_ac_29_19_final_facet_and_answer_counts(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()
    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=0,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
    )
    assert srepo.count_facets(self_id) == 24
    assert srepo.count_answers(self_id) == 200


# --------- AC-29.21 per-facet bias ---------------------------------------


def test_ac_29_21_facet_bias_override_shifts_mean(srepo, self_id, new_id) -> None:
    bank = _make_item_bank()
    overrides = {"facet:openness.inquisitiveness": 5.0}
    run_bootstrap(
        repo=srepo,
        self_id=self_id,
        seed=77,
        ask=_deterministic_ask,
        item_bank=bank,
        new_id=new_id,
        overrides=overrides,
    )
    score = srepo.get_facet_score(self_id, "inquisitiveness")
    # A draw centered at μ=5.0, σ=0.8, clamped to [1,5], will be ≥ 4.0 with
    # overwhelming probability. A single seed could land lower in rare cases,
    # but with σ=0.8 and μ=5, the clamp to ≤5 dominates the right tail.
    assert score >= 3.5
