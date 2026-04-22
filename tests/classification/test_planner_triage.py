"""Tests for complexity-based planner model triage.

Spec: specs/complexity-triage.yaml
Property tests verify:
  - simple_avoids_opus: simple issues never route to frontier
  - complex_gets_best: complex issues always route to frontier
  - monotonic_escalation: tier escalates with complexity
  - override_wins: explicit override always takes precedence
"""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from stronghold.classifier.complexity import planner_model_tier
from stronghold.types.intent import TIER_ORDER


_complexity = st.sampled_from(["simple", "moderate", "complex"])
_tier = st.sampled_from(["small", "medium", "large", "frontier"])


class TestPlannerTriageProperties:
    @given(complexity=st.just("simple"))
    @settings(max_examples=5)
    def test_simple_avoids_opus(self, complexity: str) -> None:
        """Invariant: simple_avoids_opus."""
        tier = planner_model_tier(complexity)
        assert tier != "frontier"

    @given(complexity=st.just("complex"))
    @settings(max_examples=5)
    def test_complex_gets_best(self, complexity: str) -> None:
        """Invariant: complex_gets_best."""
        tier = planner_model_tier(complexity)
        assert tier == "frontier"

    def test_monotonic_escalation(self) -> None:
        """Invariant: monotonic_escalation."""
        tiers = [planner_model_tier(c) for c in ("simple", "moderate", "complex")]
        orders = [TIER_ORDER[t] for t in tiers]
        assert orders[0] <= orders[1] <= orders[2]

    @given(complexity=_complexity, override=_tier)
    @settings(max_examples=20)
    def test_override_wins(self, complexity: str, override: str) -> None:
        """Invariant: override_wins."""
        tier = planner_model_tier(complexity, override=override)
        assert tier == override


class TestPlannerTriage:
    def test_simple_returns_medium(self) -> None:
        assert planner_model_tier("simple") == "medium"

    def test_moderate_returns_large(self) -> None:
        assert planner_model_tier("moderate") == "large"

    def test_complex_returns_frontier(self) -> None:
        assert planner_model_tier("complex") == "frontier"

    def test_unknown_complexity_defaults_large(self) -> None:
        assert planner_model_tier("unknown") == "large"

    def test_override_ignores_complexity(self) -> None:
        assert planner_model_tier("complex", override="small") == "small"
