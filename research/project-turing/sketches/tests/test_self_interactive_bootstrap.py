"""Tests for specs/interactive-bootstrap.md."""

from __future__ import annotations

import pytest

from turing.self_interactive_bootstrap import (
    DEFAULT_AGENT_WEIGHT,
    DEFAULT_USER_WEIGHT,
    HEXACO_ITEMS_PHASE1,
    HEXACO_ITEMS_PHASE2,
    NEGATIVE_BIAS_FACETS,
    OPEN_ENDED_QUESTIONS,
    POSITIVE_BIAS_FACETS,
    THREE_LAWS,
    BootstrapPhase,
    current_phase,
    facet_score_biased,
    is_bootstrap_complete,
    merge_profiles,
)


def test_current_phase_1():
    phase = current_phase(0)
    assert phase.phase == 1
    assert phase.total_questions == HEXACO_ITEMS_PHASE1
    assert not phase.complete


def test_current_phase_1_mid():
    phase = current_phase(10)
    assert phase.phase == 1
    assert phase.answered == 10


def test_current_phase_2():
    phase = current_phase(HEXACO_ITEMS_PHASE1)
    assert phase.phase == 2
    assert phase.total_questions == HEXACO_ITEMS_PHASE2


def test_current_phase_3():
    phase = current_phase(HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2)
    assert phase.phase == 3
    assert phase.total_questions == OPEN_ENDED_QUESTIONS


def test_current_phase_4_complete():
    total = HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2 + OPEN_ENDED_QUESTIONS
    phase = current_phase(total)
    assert phase.phase == 4
    assert phase.complete


def test_is_bootstrap_complete_false():
    total = HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2 + OPEN_ENDED_QUESTIONS
    assert not is_bootstrap_complete(total - 1)


def test_is_bootstrap_complete_true():
    total = HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2 + OPEN_ENDED_QUESTIONS
    assert is_bootstrap_complete(total)


def test_facet_score_biased_positive_floor():
    score = facet_score_biased(0.5, "sincerity")
    assert score >= 1.0


def test_facet_score_biased_negative_cap():
    score = facet_score_biased(2.0, "fearfulness")
    assert score <= 1.0


def test_facet_score_biased_neutral_unchanged():
    score = facet_score_biased(3.0, "some_other_facet")
    assert score == 3.0


def test_facet_score_biased_multiplier():
    score = facet_score_biased(2.0, "sincerity", multiplier=1.5)
    assert score == 3.0


def test_facet_score_biased_clamped_upper():
    score = facet_score_biased(10.0, "sincerity")
    assert score == 5.0


def test_facet_score_biased_clamped_lower():
    score = facet_score_biased(-10.0, "fearfulness")
    assert score == 0.0


def test_positive_bias_facets_known():
    assert "sincerity" in POSITIVE_BIAS_FACETS
    assert "fairness" in POSITIVE_BIAS_FACETS
    assert "conscientiousness" in POSITIVE_BIAS_FACETS


def test_negative_bias_facets_known():
    assert "fearfulness" in NEGATIVE_BIAS_FACETS
    assert "anxiety" in NEGATIVE_BIAS_FACETS
    assert "liveliness" in NEGATIVE_BIAS_FACETS


def test_no_overlap_bias_sets():
    assert POSITIVE_BIAS_FACETS.isdisjoint(NEGATIVE_BIAS_FACETS)


def test_merge_profiles_basic():
    agent = {"sincerity": 3.0, "fairness": 3.0}
    user = {"sincerity": 4.0, "fairness": 2.0}
    guided = {}
    merged = merge_profiles(agent, user, guided)
    expected_sincerity = (3.0 * DEFAULT_AGENT_WEIGHT + 4.0 * DEFAULT_USER_WEIGHT) / (
        DEFAULT_AGENT_WEIGHT + DEFAULT_USER_WEIGHT
    )
    assert abs(merged["sincerity"] - expected_sincerity) < 0.01


def test_merge_profiles_missing_facet_uses_default():
    agent = {"sincerity": 3.0}
    user = {"fairness": 4.0}
    guided = {}
    merged = merge_profiles(agent, user, guided)
    assert "sincerity" in merged
    assert "fairness" in merged


def test_merge_profiles_influence_consent():
    agent = {"sincerity": 3.0}
    user = {"sincerity": 5.0}
    guided = {}
    full = merge_profiles(agent, user, guided, influence_consent=1.0)
    zero = merge_profiles(agent, user, guided, influence_consent=0.0)
    assert full["sincerity"] > zero["sincerity"]


def test_three_laws_present():
    assert len(THREE_LAWS) == 3
    assert any("sincere" in law.lower() or "fair" in law.lower() for law in THREE_LAWS)
    assert any(
        "cooperative" in law.lower() or "gentle" in law.lower() or "harm" in law.lower()
        for law in THREE_LAWS
    )
    assert any("thorough" in law.lower() or "diligent" in law.lower() for law in THREE_LAWS)


def test_total_questions():
    total = HEXACO_ITEMS_PHASE1 + HEXACO_ITEMS_PHASE2 + OPEN_ENDED_QUESTIONS
    assert total == 45


def test_weights_sum():
    assert DEFAULT_USER_WEIGHT + DEFAULT_AGENT_WEIGHT > 0
    assert DEFAULT_USER_WEIGHT > DEFAULT_AGENT_WEIGHT


def test_bootstrap_phase_dataclass():
    phase = BootstrapPhase(phase=1, total_questions=20, answered=5)
    assert phase.phase == 1
    assert phase.total_questions == 20
    assert phase.answered == 5
    assert not phase.complete
