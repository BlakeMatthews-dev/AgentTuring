"""Tests for GitHubToolExecutor.

Uses respx for HTTP mocking (external service — allowed by testing rules).
Tests real GitHubToolExecutor instances with real ToolResult validation.
"""

from __future__ import annotations

import json

import httpx
import respx

from stronghold.tools.github import GITHUB_TOOL_DEF, GitHubToolExecutor


class TestGitHubToolDefinition:
    """Tool definition structure validation."""

    def test_name(self) -> None:
        assert GITHUB_TOOL_DEF.name == "github"

    def test_has_action_enum(self) -> None:
        actions = GITHUB_TOOL_DEF.parameters["properties"]["action"]["enum"]
        assert "list_issues" in actions
        assert "create_pr" in actions
        assert "get_pr_diff" in actions

    def test_groups(self) -> None:
        assert "code_gen" in GITHUB_TOOL_DEF.groups


class TestListIssues:
    """list_issues action."""

    @respx.mock
    async def test_returns_issues(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues").mock(
            return_value=httpx.Response(200, json=[
                {
                    "number": 1,
                    "title": "Fix bug",
                    "state": "open",
                    "labels": [{"name": "bug"}],
                    "assignee": {"login": "mason"},
                },
                {
                    "number": 2,
                    "title": "PR title",
                    "state": "open",
                    "labels": [],
                    "assignee": None,
                    "pull_request": {"url": "..."},
                },
            ])
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "list_issues",
            "owner": "org",
            "repo": "repo",
        })
        assert result.success
        issues = json.loads(result.content)
        # Tool returns both issues and PRs with is_pr flag — callers filter
        assert len(issues) == 2
        non_prs = [i for i in issues if not i["is_pr"]]
        assert len(non_prs) == 1
        assert non_prs[0]["number"] == 1
        prs = [i for i in issues if i["is_pr"]]
        assert len(prs) == 1

    @respx.mock
    async def test_filters_by_labels(self) -> None:
        route = respx.get("https://api.github.com/repos/org/repo/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        executor = GitHubToolExecutor(token="test-token")
        await executor.execute({
            "action": "list_issues",
            "owner": "org",
            "repo": "repo",
            "labels": ["mason", "ready"],
        })
        assert "labels=mason%2Cready" in str(route.calls[0].request.url)


class TestGetIssue:
    """get_issue action."""

    @respx.mock
    async def test_returns_issue_details(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues/42").mock(
            return_value=httpx.Response(200, json={
                "number": 42,
                "title": "Implement feature",
                "body": "Details here",
                "state": "open",
                "labels": [{"name": "feat"}],
                "assignee": None,
            })
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "get_issue",
            "owner": "org",
            "repo": "repo",
            "issue_number": 42,
        })
        assert result.success
        issue = json.loads(result.content)
        assert issue["number"] == 42
        assert issue["body"] == "Details here"


class TestCreateBranch:
    """create_branch action."""

    @respx.mock
    async def test_creates_branch_from_main(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/git/ref/heads/main").mock(
            return_value=httpx.Response(200, json={
                "object": {"sha": "abc123"},
            })
        )
        respx.post("https://api.github.com/repos/org/repo/git/refs").mock(
            return_value=httpx.Response(201, json={
                "ref": "refs/heads/mason/42-feature",
            })
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "create_branch",
            "owner": "org",
            "repo": "repo",
            "branch": "mason/42-feature",
        })
        assert result.success
        data = json.loads(result.content)
        assert data["branch"] == "mason/42-feature"
        assert data["sha"] == "abc123"


class TestCreatePR:
    """create_pr action."""

    @respx.mock
    async def test_creates_pr(self) -> None:
        respx.post("https://api.github.com/repos/org/repo/pulls").mock(
            return_value=httpx.Response(201, json={
                "number": 99,
                "html_url": "https://github.com/org/repo/pull/99",
                "state": "open",
            })
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "create_pr",
            "owner": "org",
            "repo": "repo",
            "branch": "mason/42-feature",
            "title": "feat: implement feature #42",
            "body": "Closes #42",
        })
        assert result.success
        pr = json.loads(result.content)
        assert pr["number"] == 99


class TestPostComment:
    """post_pr_comment action."""

    @respx.mock
    async def test_posts_comment(self) -> None:
        respx.post(
            "https://api.github.com/repos/org/repo/issues/99/comments"
        ).mock(
            return_value=httpx.Response(201, json={
                "id": 12345,
                "html_url": "https://github.com/org/repo/pull/99#issuecomment-12345",
            })
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "post_pr_comment",
            "owner": "org",
            "repo": "repo",
            "issue_number": 99,
            "body": "[MOCK_USAGE] **high** -- test finding",
        })
        assert result.success


class TestUnknownAction:
    """Error handling for unknown actions."""

    async def test_unknown_action_returns_error(self) -> None:
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "delete_repo",
            "owner": "org",
            "repo": "repo",
        })
        assert not result.success
        assert "Unknown GitHub action" in (result.error or "")


class TestAuthHeaders:
    """Token is included in headers."""

    @respx.mock
    async def test_includes_bearer_token(self) -> None:
        route = respx.get("https://api.github.com/repos/org/repo/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        executor = GitHubToolExecutor(token="ghp_test123")
        await executor.execute({
            "action": "list_issues",
            "owner": "org",
            "repo": "repo",
        })
        auth = route.calls[0].request.headers.get("authorization")
        assert auth == "Bearer ghp_test123"
