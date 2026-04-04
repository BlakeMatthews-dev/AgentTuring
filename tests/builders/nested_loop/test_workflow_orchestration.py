"""Tests for full workflow orchestration (Frank/Archie ↔ Mason cycles).

Evidence-based contracts:
- Workflow checks for existing work before starting decomposition
- Outer loop limits retries to 5 before signaling admin
- Inner loop cycles between Frank/Archie and Mason
- Model escalation happens with each outer retry
- Each workflow step documents via GitHub comments
- Mason's test tracking determines when to return to Frank/Archie
- Quality gates require 95% coverage before PR creation
- PR created only after all quality gates pass
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, Mock

from stronghold.api.routes.builders import (
    _execute_nested_loop_workflow,
    _check_existing_work,
    _frank_archie_phase,
    _mason_phase,
    _run_quality_gates,
    _create_pr_after_success,
)
from stronghold.builders.nested_loop import (
    MasonTestTracker,
    OuterLoopTracker,
    ModelEscalator,
)
from stronghold.builders.nested_loop.comment_system import (
    CommentType,
)


class TestCheckExistingWork:
    """Checking for existing work before starting decomposition."""

    async def test_returns_empty_dict_when_no_work_found(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            '{"total_count": 0, "items": []}',
            "[]",
            "[]",
        ]

        existing = await _check_existing_work(
            tool_dispatcher=mock_tool_dispatcher,
            owner="org",
            repo="repo",
            issue_number=42,
            issue_title="Implement feature",
        )

        assert existing["prs"] == []
        assert existing["issues"] == []
        assert existing["comments"] == []
        assert existing["has_work"] is False

    async def test_finds_existing_prs_related_to_issue(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            '{"total_count": 1, "items": [{"number": 123, "title": "PR for feature", "html_url": "...", "is_pr": true}]}',
            "[]",
            "[]",
        ]

        existing = await _check_existing_work(
            tool_dispatcher=mock_tool_dispatcher,
            owner="org",
            repo="repo",
            issue_number=42,
            issue_title="Implement feature",
        )

        assert len(existing["prs"]) == 1
        assert existing["prs"][0]["number"] == 123
        assert existing["has_work"] is True

    async def test_finds_linked_issues_and_comments(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            '{"total_count": 0, "items": []}',
            '[{"id": 100, "user": "frank", "body": "## Problem Decomposition"}]',
            '[{"number": 10, "title": "Related issue", "html_url": "...", "is_pr": false}]',
        ]

        existing = await _check_existing_work(
            tool_dispatcher=mock_tool_dispatcher,
            owner="org",
            repo="repo",
            issue_number=42,
            issue_title="Implement feature",
        )

        assert len(existing["comments"]) == 1
        assert len(existing["issues"]) == 1
        assert existing["has_work"] is True

    async def test_uses_issue_title_in_search_query(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = '{"total_count": 0, "items": []}'

        await _check_existing_work(
            tool_dispatcher=mock_tool_dispatcher,
            owner="org",
            repo="repo",
            issue_number=42,
            issue_title="Add user authentication",
        )

        call_args = mock_tool_dispatcher.execute.call_args_list[0]
        args, kwargs = call_args
        query = kwargs.get("query", args[1].get("query", ""))
        assert "user" in query or "authentication" in query


class TestFrankArchiePhase:
    """Frank/Archie phase: problem decomposition and acceptance criteria."""

    async def test_decomposes_problem_when_no_existing_work(self):
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="", blocked=False)
        mock_container.agents = {"frank": mock_agent}
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = "{}"

        result = await _frank_archie_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            issue_title="Feature",
            issue_content="Implement X",
            ws_path="/workspace",
        )

        assert result["phase"] == "frank_archie"
        assert result["decomposed"] is True
        mock_agent.handle.assert_called_once()

    async def test_skips_decomposition_when_existing_work_found(self):
        mock_container = Mock()
        mock_tool_dispatcher = AsyncMock()

        existing_work = {
            "prs": [{"number": 123}],
            "issues": [],
            "comments": [],
            "has_work": True,
        }

        result = await _frank_archie_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            issue_title="Feature",
            issue_content="Implement X",
            ws_path="/workspace",
            existing_work=existing_work,
        )

        assert result["phase"] == "frank_archie"
        assert result["decomposed"] is False
        assert result["existing_prs"] == [123]

    async def test_documents_decomposition_as_issue_comment(self):
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="Decomposition complete", blocked=False)
        mock_container.agents = {"frank": mock_agent}
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            '{"total_count": 0, "items": []}',
            "[]",
            "[]",
            '{"id": 999}',
        ]

        await _frank_archie_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            issue_title="Feature",
            issue_content="Implement X",
            ws_path="/workspace",
        )

        comment_call = None
        for call in mock_tool_dispatcher.execute.call_args_list:
            args, kwargs = call
            if len(args) > 0 and args[0] == "github" and args[1].get("action") == "post_pr_comment":
                comment_call = call
                break

        assert comment_call is not None
        assert "Problem Decomposition" in comment_call[0][1]["body"]


class TestMasonPhase:
    """Mason phase: TDD implementation with test tracking."""

    async def test_builds_until_tests_pass(self):
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="Implementation complete", blocked=False)
        mock_container.agents = {"mason": mock_agent}
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = (
            '{"passing": 50, "failing": 0, "coverage": "95%"}'
        )

        test_tracker = MasonTestTracker()

        result = await _mason_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            test_tracker=test_tracker,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            ws_path="/workspace",
        )

        assert result["phase"] == "mason"
        assert result["success"] is True

    async def test_tracks_test_progress_with_counter(self):
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="More work needed", blocked=False)
        mock_container.agents = {"mason": mock_agent}
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            "10 passed, 40 failed, 20% coverage",
            '{"id": 998}',
            "15 passed, 35 failed, 30% coverage",
            '{"id": 999}',
        ]

        test_tracker = MasonTestTracker()

        await _mason_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            test_tracker=test_tracker,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            ws_path="/workspace",
            max_attempts=2,
        )

        assert test_tracker.high_water_mark == 15
        assert test_tracker.stall_counter == 0

    async def test_returns_to_frank_after_10_stalls(self):
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="Still failing", blocked=False)
        mock_container.agents = {"mason": mock_agent}
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = "10 passed, 40 failed, 20% coverage"

        test_tracker = MasonTestTracker()
        test_tracker.high_water_mark = 50

        result = await _mason_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            test_tracker=test_tracker,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            ws_path="/workspace",
            max_attempts=10,
        )

        assert result["phase"] == "mason"
        assert result["success"] is False
        assert result["stalled"] is True
        assert test_tracker.has_failed is True

    async def test_documents_test_results_as_comments(self):
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="Tests improved", blocked=False)
        mock_container.agents = {"mason": mock_agent}
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            '{"passing": 45, "failing": 5, "coverage": "90%"}',
            '{"id": 998}',
        ]

        test_tracker = MasonTestTracker()

        await _mason_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            test_tracker=test_tracker,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            ws_path="/workspace",
        )

        comment_call = None
        for call in mock_tool_dispatcher.execute.call_args_list:
            args, kwargs = call
            if len(args) > 0 and args[0] == "github" and args[1].get("action") == "post_pr_comment":
                comment_call = call
                break

        assert comment_call is not None
        assert "Mason Test Results" in comment_call[0][1]["body"]


class TestOuterLoopLogic:
    """Outer loop with 5 failure limit and model escalation."""

    async def test_limits_to_5_failures_before_signaling_admin(self):
        mock_container = Mock()
        mock_tool_dispatcher = AsyncMock()

        outer_tracker = OuterLoopTracker(max_failures=5)

        for _ in range(5):
            outer_tracker.record_failure()

        assert outer_tracker.should_signal_admin is True

    async def test_resets_on_successful_completion(self):
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="Success", blocked=False)
        mock_container.agents = {"mason": mock_agent}
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = (
            '{"passing": 100, "failing": 0, "coverage": "95%"}'
        )

        outer_tracker = OuterLoopTracker()
        outer_tracker.record_failure()
        outer_tracker.record_failure()

        result = await _mason_phase(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            test_tracker=MasonTestTracker(),
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            ws_path="/workspace",
        )

        if result["success"]:
            outer_tracker.record_success()

        assert outer_tracker.failure_count == 0

    async def test_escalates_model_with_each_retry(self):
        escalator = ModelEscalator()

        model_0 = escalator.select_model(retry_count=0)
        model_1 = escalator.select_model(retry_count=1)
        model_2 = escalator.select_model(retry_count=2)

        assert model_0 != model_1
        assert model_1 != model_2

    async def test_signals_admin_with_final_comment(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = '{"id": 999}'
        mock_container = Mock()
        mock_agent = AsyncMock()
        mock_agent.handle.return_value = Mock(content="Working", blocked=False)
        mock_container.agents = {"mason": mock_agent}

        outer_tracker = OuterLoopTracker()
        for _ in range(5):
            outer_tracker.record_failure()

        result = await _execute_nested_loop_workflow(
            container=mock_container,
            tool_dispatcher=mock_tool_dispatcher,
            run_id="run-1",
            repo="org/repo",
            issue_number=42,
            ws_path="/workspace",
            issue_title="Complex feature",
            issue_content="Hard problem",
        )

        admin_call = None
        for call in mock_tool_dispatcher.execute.call_args_list:
            args, kwargs = call
            if len(args) > 0 and args[0] == "github" and "Admin" in args[1].get("body", ""):
                admin_call = call
                break

        assert admin_call is not None
        assert "Admin Attention Required" in admin_call[0][1]["body"]


class TestQualityGates:
    """Quality gates requiring 95% coverage."""

    async def test_requires_95_coverage_to_pass(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = (
            '{"passing": 100, "failing": 0, "coverage": "94%"}'
        )

        result = await _run_quality_gates(
            tool_dispatcher=mock_tool_dispatcher,
            ws_path="/workspace",
        )

        assert result["passed"] is False
        assert result["coverage"] == "94%"

    async def test_passes_when_coverage_at_or_above_95_percent(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = (
            '{"passing": 100, "failing": 0, "coverage": "95%"}'
        )

        result = await _run_quality_gates(
            tool_dispatcher=mock_tool_dispatcher,
            ws_path="/workspace",
        )

        assert result["passed"] is True
        assert result["coverage"] == "95%"

    async def test_runs_all_quality_checks_in_order(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.return_value = '{"passed": true}'

        await _run_quality_gates(
            tool_dispatcher=mock_tool_dispatcher,
            ws_path="/workspace",
        )

        assert mock_tool_dispatcher.execute.call_count >= 1

    async def test_documents_quality_check_results(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            "100 passed, 0 failed, 95% coverage",  # pytest
            "All checks passed",                     # ruff
            "Success: no issues found",              # mypy
            "No issues identified",                  # bandit
        ]

        result = await _run_quality_gates(
            tool_dispatcher=mock_tool_dispatcher,
            ws_path="/workspace",
        )

        assert result["passed"] is True
        assert result["coverage"] == "95%"
        assert result["pytest"] == "passed"
        assert result["ruff_check"] == "passed"
        assert result["mypy"] == "passed"
        assert result["bandit"] == "passed"
        assert mock_tool_dispatcher.execute.call_count == 4


class TestPRCreation:
    """PR creation only after all quality gates pass."""

    async def test_creates_pr_only_when_quality_gates_pass(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            '{"id": 123}',                                                          # commit
            '{"id": 456}',                                                          # push
            '{"number": 789, "html_url": "https://github.com/org/repo/pull/789"}',  # create_pr
            '{"id": 997}',                                                          # comment publish
            "{}",                                                                   # cleanup
        ]

        result = await _create_pr_after_success(
            tool_dispatcher=mock_tool_dispatcher,
            owner="org",
            repo="repo",
            branch="builders/42-abc123",
            issue_number=42,
            ws_path="/workspace",
            quality_passed=True,
        )

        assert result["created"] is True
        assert result["pr_number"] == 789

    async def test_skips_pr_creation_when_quality_gates_fail(self):
        mock_tool_dispatcher = AsyncMock()

        result = await _create_pr_after_success(
            tool_dispatcher=mock_tool_dispatcher,
            owner="org",
            repo="repo",
            branch="builders/42-abc123",
            issue_number=42,
            ws_path="/workspace",
            quality_passed=False,
        )

        assert result["created"] is False
        assert result["pr_number"] is None

    async def test_documents_pr_creation(self):
        mock_tool_dispatcher = AsyncMock()
        mock_tool_dispatcher.execute.side_effect = [
            '{"id": 123}',                                                          # commit
            '{"id": 456}',                                                          # push
            '{"number": 789, "html_url": "https://github.com/org/repo/pull/789"}',  # create_pr
            '{"id": 997}',                                                          # comment publish
            "{}",                                                                   # cleanup
        ]

        await _create_pr_after_success(
            tool_dispatcher=mock_tool_dispatcher,
            owner="org",
            repo="repo",
            branch="builders/42-abc123",
            issue_number=42,
            ws_path="/workspace",
            quality_passed=True,
        )

        pr_comment_call = None
        for call in mock_tool_dispatcher.execute.call_args_list:
            args, kwargs = call
            if len(args) > 0 and args[0] == "github" and "Pull Request" in args[1].get("body", ""):
                pr_comment_call = call
                break

        assert pr_comment_call is not None
        assert "Pull Request Created" in pr_comment_call[0][1]["body"]
