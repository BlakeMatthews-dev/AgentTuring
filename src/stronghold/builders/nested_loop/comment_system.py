"""Issue comment documentation system for workflow steps.

Formats and publishes structured comments to GitHub issues for:
- Frank/Archie problem decomposition
- Mason test results
- Quality checks
- PR creation
- Outer loop failures
- Admin signaling
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, UTC
from enum import StrEnum
from typing import Any


class CommentType(StrEnum):
    """Types of workflow documentation comments."""

    FRANK_DECOMPOSITION = "frank_decomposition"
    MASON_TEST_RESULTS = "mason_test_results"
    QUALITY_CHECKS = "quality_checks"
    PR_CREATED = "pr_created"
    OUTER_LOOP_FAILURE = "outer_loop_failure"
    ADMIN_SIGNAL = "admin_signal"
    ACCEPTANCE_CRITERIA = "acceptance_criteria"
    TEST_DESIGN = "test_design"


@dataclass
class CommentPublishResult:
    """Result of publishing a comment to GitHub."""

    success: bool
    comment_id: int | None = None
    error: str | None = None


class IssueCommentFormatter:
    """Formats workflow step documentation into structured GitHub issue comments."""

    def format_comment(
        self,
        comment_type: CommentType,
        step: str,
        details: dict[str, Any],
        run_id: str = "",
    ) -> str:
        """Format a workflow step comment."""
        timestamp = datetime.now(UTC).isoformat()
        run_id_line = f"Run ID: {run_id}\n" if run_id else ""
        header = self._get_header(comment_type)
        body = self._format_details(comment_type, details)

        return f"""{header}

{run_id_line}Step: {step}
Timestamp: {timestamp}

{body}
"""

    def _get_header(self, comment_type: CommentType) -> str:
        headers = {
            CommentType.FRANK_DECOMPOSITION: "## Problem Decomposition",
            CommentType.MASON_TEST_RESULTS: "## Mason Test Results",
            CommentType.QUALITY_CHECKS: "## Quality Checks",
            CommentType.PR_CREATED: "## Pull Request Created",
            CommentType.OUTER_LOOP_FAILURE: "## Outer Loop Failure",
            CommentType.ADMIN_SIGNAL: "## Admin Attention Required",
            CommentType.ACCEPTANCE_CRITERIA: "## Acceptance Criteria Defined",
            CommentType.TEST_DESIGN: "## Test Design",
        }
        return headers.get(comment_type, "## Workflow Step")

    def _format_details(self, comment_type: CommentType, details: dict[str, Any]) -> str:
        if comment_type == CommentType.FRANK_DECOMPOSITION:
            return self._format_decomposition(details)
        elif comment_type == CommentType.MASON_TEST_RESULTS:
            return self._format_test_results(details)
        elif comment_type == CommentType.QUALITY_CHECKS:
            return self._format_quality_checks(details)
        elif comment_type == CommentType.PR_CREATED:
            return self._format_pr_created(details)
        elif comment_type == CommentType.OUTER_LOOP_FAILURE:
            return self._format_outer_loop_failure(details)
        elif comment_type == CommentType.ADMIN_SIGNAL:
            return self._format_admin_signal(details)
        return self._format_generic_details(details)

    def _format_decomposition(self, details: dict[str, Any]) -> str:
        sections = []
        if "sub_problems" in details:
            sections.append(
                "### Sub-problems\n" + "\n".join(f"- {p}" for p in details["sub_problems"])
            )
        if "assumptions" in details:
            sections.append(
                "### Assumptions\n" + "\n".join(f"- {a}" for a in details["assumptions"])
            )
        if "existing_work" in details:
            sections.append(f"### Existing Work Found\n{details['existing_work']}")
        return "\n\n".join(sections)

    def _format_test_results(self, details: dict[str, Any]) -> str:
        passing = details.get("passing", 0)
        failing = details.get("failing", 0)
        coverage = details.get("coverage", "N/A")
        high_water_mark = details.get("high_water_mark", 0)
        stall_counter = details.get("stall_counter", 0)

        return f"""### Test Statistics
- Passing: {passing}
- Failing: {failing}
- Coverage: {coverage}
- High Water Mark: {high_water_mark}
- Stall Counter: {stall_counter}
"""

    def _format_quality_checks(self, details: dict[str, Any]) -> str:
        checks = [
            ("pytest", details.get("pytest", "unknown")),
            ("ruff_check", details.get("ruff_check", "unknown")),
            ("ruff_format", details.get("ruff_format", "unknown")),
            ("mypy", details.get("mypy", "unknown")),
            ("bandit", details.get("bandit", "unknown")),
        ]
        check_lines = [f"- {name}: {status}" for name, status in checks]
        coverage = details.get("coverage", "N/A")
        return f"### Quality Gates\n" + "\n".join(check_lines) + f"\n\nCoverage: {coverage}"

    def _format_pr_created(self, details: dict[str, Any]) -> str:
        pr_number = details.get("pr_number", "unknown")
        pr_url = details.get("pr_url", "unknown")
        branch = details.get("branch", "unknown")
        return f"""### Pull Request Details
- PR #{pr_number}
- URL: {pr_url}
- Branch: {branch}
"""

    def _format_outer_loop_failure(self, details: dict[str, Any]) -> str:
        retry_count = details.get("retry_count", 0)
        error_reason = details.get("error_reason", "unknown")
        model_used = details.get("model_used", "unknown")
        return f"""### Failure Details
- Retry Count: {retry_count}
- Error: {error_reason}
- Model Used: {model_used}
"""

    def _format_admin_signal(self, details: dict[str, Any]) -> str:
        total_failures = details.get("total_failures", 0)
        recommendation = details.get("recommendation", "No specific recommendation")
        return f"""### Escalation Summary
- Total Failures: {total_failures}
- Recommendation: {recommendation}
"""

    def _format_generic_details(self, details: dict[str, Any]) -> str:
        return "\n".join(f"- {k}: {v}" for k, v in details.items())


class IssueCommentPublisher:
    """Publishes formatted comments to GitHub issues with error handling."""

    def __init__(
        self,
        tool_dispatcher: Any,
        formatter: IssueCommentFormatter | None = None,
    ) -> None:
        self._tool_dispatcher = tool_dispatcher
        self._formatter = formatter or IssueCommentFormatter()

    async def publish_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        comment_body: str,
    ) -> CommentPublishResult:
        """Publish a comment to the issue."""
        try:
            result = await self._tool_dispatcher.execute(
                "github",
                {
                    "action": "post_pr_comment",
                    "owner": owner,
                    "repo": repo,
                    "issue_number": issue_number,
                    "body": comment_body,
                },
            )
            if result.startswith("Error:"):
                return CommentPublishResult(success=False, error=result)
            import json

            data = json.loads(result)
            return CommentPublishResult(success=True, comment_id=data.get("id"))
        except Exception as e:
            return CommentPublishResult(success=False, error=str(e))

    async def publish_workflow_step(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        comment_type: CommentType,
        step: str,
        details: dict[str, Any],
        run_id: str = "",
    ) -> CommentPublishResult:
        """Format and publish a workflow step comment."""
        comment_body = self._formatter.format_comment(
            comment_type=comment_type,
            step=step,
            details=details,
            run_id=run_id,
        )
        return await self.publish_comment(owner, repo, issue_number, comment_body)
