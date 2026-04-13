"""Tests for stronghold.learning.retrospective -- RetrospectiveLearningManager.

Covers the 5 analysis passes: first-pass success, rework feedback,
persistent failures, model performance, and tool effectiveness.
Plus deduplication by trigger_keys.
"""

from __future__ import annotations

from stronghold.learning.retrospective import RetrospectiveLearningManager


def _make_run(
    issue: int = 1,
    stages: list[dict[str, str]] | None = None,
    status: str = "completed",
    model: str = "gpt-4o",
    tools_used: list[str] | None = None,
    rework_count: int = 0,
) -> dict[str, object]:
    """Build a minimal pipeline run dict for testing."""
    default_stages = [
        {"name": "scaffold", "status": "completed", "agent_name": "archie"},
        {"name": "implement", "status": "completed", "agent_name": "mason"},
        {"name": "review", "status": "completed", "agent_name": "auditor"},
    ]
    return {
        "issue_number": issue,
        "status": status,
        "stages": stages or default_stages,
        "model": model,
        "tools_used": tools_used or [],
        "rework_count": rework_count,
    }


class TestFirstPassSuccess:
    """Pass 1: Identify runs that succeeded on first attempt."""

    async def test_first_pass_success_detected(self) -> None:
        mgr = RetrospectiveLearningManager()
        history = [_make_run(issue=1, status="completed", rework_count=0)]
        insights = await mgr.analyze_runs(history)
        first_pass = [i for i in insights if i["pass"] == "first_pass_success"]
        assert len(first_pass) >= 1
        assert first_pass[0]["issue_number"] == 1

    async def test_reworked_run_not_first_pass(self) -> None:
        mgr = RetrospectiveLearningManager()
        history = [_make_run(issue=1, status="completed", rework_count=2)]
        insights = await mgr.analyze_runs(history)
        first_pass = [i for i in insights if i["pass"] == "first_pass_success"]
        assert len(first_pass) == 0


class TestReworkFeedback:
    """Pass 2: Identify runs that required rework."""

    async def test_rework_detected(self) -> None:
        mgr = RetrospectiveLearningManager()
        history = [_make_run(issue=5, status="completed", rework_count=3)]
        insights = await mgr.analyze_runs(history)
        rework = [i for i in insights if i["pass"] == "rework_feedback"]
        assert len(rework) >= 1
        assert rework[0]["rework_count"] == 3


class TestPersistentFailures:
    """Pass 3: Identify runs that failed repeatedly."""

    async def test_persistent_failure_detected(self) -> None:
        mgr = RetrospectiveLearningManager()
        stages = [
            {"name": "implement", "status": "failed", "agent_name": "mason"},
        ]
        history = [_make_run(issue=10, status="failed at implement", stages=stages)]
        insights = await mgr.analyze_runs(history)
        failures = [i for i in insights if i["pass"] == "persistent_failure"]
        assert len(failures) >= 1
        assert failures[0]["issue_number"] == 10


class TestModelPerformance:
    """Pass 4: Aggregate model performance metrics."""

    async def test_model_perf_aggregated(self) -> None:
        mgr = RetrospectiveLearningManager()
        history = [
            _make_run(issue=1, model="gpt-4o", status="completed"),
            _make_run(issue=2, model="gpt-4o", status="completed"),
            _make_run(issue=3, model="claude-sonnet", status="failed at review"),
        ]
        insights = await mgr.analyze_runs(history)
        model_perf = [i for i in insights if i["pass"] == "model_performance"]
        assert len(model_perf) >= 1
        # Should have entries for both models
        models = {m["model"] for m in model_perf}
        assert "gpt-4o" in models


class TestToolEffectiveness:
    """Pass 5: Aggregate tool effectiveness."""

    async def test_tool_effectiveness_tracked(self) -> None:
        mgr = RetrospectiveLearningManager()
        history = [
            _make_run(issue=1, tools_used=["github", "shell"], status="completed"),
            _make_run(issue=2, tools_used=["github"], status="failed at implement"),
        ]
        insights = await mgr.analyze_runs(history)
        tool_eff = [i for i in insights if i["pass"] == "tool_effectiveness"]
        assert len(tool_eff) >= 1
        tools = {t["tool"] for t in tool_eff}
        assert "github" in tools


class TestDeduplication:
    """Deduplication by trigger_keys prevents duplicate insights."""

    async def test_duplicate_runs_deduplicated(self) -> None:
        mgr = RetrospectiveLearningManager()
        # Same issue appearing twice should not produce duplicate insights
        run = _make_run(issue=42, status="completed", rework_count=0)
        history = [run, run]
        insights = await mgr.analyze_runs(history)
        first_pass = [i for i in insights if i["pass"] == "first_pass_success"]
        # Should have at most 1 entry for issue 42
        issue_42 = [fp for fp in first_pass if fp["issue_number"] == 42]
        assert len(issue_42) == 1
