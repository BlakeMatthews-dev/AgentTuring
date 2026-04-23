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


class TestGetPrDiff:
    """get_pr_diff action."""

    @respx.mock
    async def test_returns_diff_text(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/pulls/42").mock(
            return_value=httpx.Response(200, text="diff --git a/file.py b/file.py\n+new line\n")
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "get_pr_diff",
            "owner": "org",
            "repo": "repo",
            "issue_number": 42,
        })
        assert result.success
        data = json.loads(result.content)
        assert "diff --git" in data["diff"]


class TestListPrComments:
    """list_pr_comments action."""

    @respx.mock
    async def test_returns_comments(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues/99/comments").mock(
            return_value=httpx.Response(200, json=[
                {
                    "id": 111,
                    "user": {"login": "reviewer"},
                    "body": "LGTM",
                    "created_at": "2026-04-10T12:00:00Z",
                },
                {
                    "id": 222,
                    "user": {"login": "mason"},
                    "body": "Fixed.",
                    "created_at": "2026-04-10T13:00:00Z",
                },
            ])
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "list_pr_comments",
            "owner": "org",
            "repo": "repo",
            "issue_number": 99,
        })
        assert result.success
        comments = json.loads(result.content)
        assert len(comments) == 2
        assert comments[0]["user"] == "reviewer"
        assert comments[1]["body"] == "Fixed."


class TestCreateIssue:
    """create_issue action."""

    @respx.mock
    async def test_creates_issue(self) -> None:
        respx.post("https://api.github.com/repos/org/repo/issues").mock(
            return_value=httpx.Response(201, json={
                "number": 55,
                "html_url": "https://github.com/org/repo/issues/55",
                "state": "open",
            })
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "create_issue",
            "owner": "org",
            "repo": "repo",
            "title": "New feature request",
            "body": "Please add X",
            "labels": ["enhancement"],
        })
        assert result.success
        data = json.loads(result.content)
        assert data["number"] == 55
        assert data["state"] == "open"

    @respx.mock
    async def test_creates_issue_without_labels(self) -> None:
        respx.post("https://api.github.com/repos/org/repo/issues").mock(
            return_value=httpx.Response(201, json={
                "number": 56,
                "html_url": "https://github.com/org/repo/issues/56",
                "state": "open",
            })
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "create_issue",
            "owner": "org",
            "repo": "repo",
            "title": "Bug report",
        })
        assert result.success


class TestHttpErrors:
    """Error handling: HTTP errors and exceptions."""

    @respx.mock
    async def test_http_error_returns_tool_error(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/issues/999").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "get_issue",
            "owner": "org",
            "repo": "repo",
            "issue_number": 999,
        })
        assert not result.success
        assert result.error is not None

    async def test_missing_action_returns_error(self) -> None:
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "owner": "org",
            "repo": "repo",
        })
        assert not result.success
        assert "Unknown GitHub action" in (result.error or "")


class TestNoTokenHeaders:
    """Token-less requests omit Authorization header."""

    @respx.mock
    async def test_no_token_omits_auth_header(self) -> None:
        route = respx.get("https://api.github.com/repos/org/repo/issues").mock(
            return_value=httpx.Response(200, json=[])
        )
        executor = GitHubToolExecutor(token="")
        await executor.execute({
            "action": "list_issues",
            "owner": "org",
            "repo": "repo",
        })
        auth = route.calls[0].request.headers.get("authorization")
        assert auth is None


class TestListIssuesPagination:
    """list_issues pagination behavior."""

    @respx.mock
    async def test_pagination_stops_on_empty_page(self) -> None:
        """list_issues stops fetching when a page returns empty results."""
        # Page 1: one item (less than per_page=100 default, so stops)
        respx.get("https://api.github.com/repos/org/repo/issues").mock(
            return_value=httpx.Response(200, json=[
                {
                    "number": 1,
                    "title": "Issue 1",
                    "state": "open",
                    "labels": [],
                    "assignee": None,
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
        assert len(issues) == 1


class TestCreateBranchCustomBase:
    """create_branch with custom base branch."""

    @respx.mock
    async def test_creates_branch_from_custom_base(self) -> None:
        respx.get("https://api.github.com/repos/org/repo/git/ref/heads/integration").mock(
            return_value=httpx.Response(200, json={
                "object": {"sha": "def456"},
            })
        )
        respx.post("https://api.github.com/repos/org/repo/git/refs").mock(
            return_value=httpx.Response(201, json={
                "ref": "refs/heads/feature/new",
            })
        )
        executor = GitHubToolExecutor(token="test-token")
        result = await executor.execute({
            "action": "create_branch",
            "owner": "org",
            "repo": "repo",
            "branch": "feature/new",
            "base": "integration",
        })
        assert result.success
        data = json.loads(result.content)
        assert data["sha"] == "def456"


# ─────────────────────────────────────────────────────────────────────
# Token helper: _get_app_installation_token
# ─────────────────────────────────────────────────────────────────────

import logging  # noqa: E402
import sys  # noqa: E402

import pytest  # noqa: E402

from stronghold.tools.github import _BOT_REGISTRY, _get_app_installation_token  # noqa: E402


class TestAppInstallationToken:
    """Behavior of _get_app_installation_token — never raises, returns str."""

    def test_token_returns_empty_when_pyjwt_missing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        # Force ImportError for `import jwt` by injecting None as the module.
        monkeypatch.setitem(sys.modules, "jwt", None)
        with caplog.at_level(logging.DEBUG, logger="stronghold.tools.github"):
            result = _get_app_installation_token("gatekeeper")
        assert result == ""
        assert any("PyJWT not installed" in rec.message for rec in caplog.records)

    def test_token_returns_empty_when_env_override_blanks_app_id(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "/does/not/exist/here.pem")
        result = _get_app_installation_token("gatekeeper")
        assert result == ""

    def test_token_returns_empty_when_key_file_missing(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("GITHUB_APP_ID", "1234")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "5678")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", "/tmp/nope-missing-key.pem")
        with caplog.at_level(logging.DEBUG, logger="stronghold.tools.github"):
            result = _get_app_installation_token("gatekeeper")
        assert result == ""
        assert any("private key not found" in rec.message for rec in caplog.records)

    def test_token_returns_empty_on_http_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem_bytes = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pem_path = tmp_path / "test.pem"
        pem_path.write_bytes(pem_bytes)

        monkeypatch.setenv("GITHUB_APP_ID", "1234")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "5678")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(pem_path))

        def boom(*args, **kwargs):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("network down")

        import httpx as _httpx
        monkeypatch.setattr(_httpx, "post", boom)

        with caplog.at_level(logging.WARNING, logger="stronghold.tools.github"):
            result = _get_app_installation_token("gatekeeper")
        assert result == ""
        assert any("Failed to generate" in rec.message for rec in caplog.records)

    def test_token_success_returns_token_string(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem_bytes = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pem_path = tmp_path / "mason.pem"
        pem_path.write_bytes(pem_bytes)

        monkeypatch.setenv("GITHUB_APP_ID", "1234")
        monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "123362160")
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(pem_path))

        captured: dict = {}

        class _FakeResp:
            status_code = 200
            def raise_for_status(self) -> None: return None
            def json(self) -> dict: return {"token": "ghs_abc"}

        def fake_post(url, headers=None, timeout=None, **kw):  # type: ignore[no-untyped-def]
            captured["url"] = url
            return _FakeResp()

        import httpx as _httpx
        monkeypatch.setattr(_httpx, "post", fake_post)

        with caplog.at_level(logging.INFO, logger="stronghold.tools.github"):
            result = _get_app_installation_token("mason")

        assert result == "ghs_abc"
        assert "123362160" in captured["url"]
        assert any(
            "GitHub App token generated for bot=mason" in rec.message
            for rec in caplog.records
        )

    def test_token_unknown_bot_falls_back_to_gatekeeper(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path,
    ) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem_bytes = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pem_path = tmp_path / "gk.pem"
        pem_path.write_bytes(pem_bytes)

        monkeypatch.delenv("GITHUB_APP_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
        monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY_PATH", str(pem_path))

        captured: dict = {}

        class _FakeResp:
            status_code = 200
            def raise_for_status(self) -> None: return None
            def json(self) -> dict: return {"token": "ghs_fallback"}

        def fake_post(url, headers=None, timeout=None, **kw):  # type: ignore[no-untyped-def]
            captured["url"] = url
            return _FakeResp()

        import httpx as _httpx
        monkeypatch.setattr(_httpx, "post", fake_post)

        result = _get_app_installation_token("nonexistent-bot-name")
        assert result == "ghs_fallback"
        assert _BOT_REGISTRY["gatekeeper"]["installation_id"] in captured["url"]


# ─────────────────────────────────────────────────────────────────────
# Constructor token resolution + _headers
# ─────────────────────────────────────────────────────────────────────


class TestExecutorConstructor:
    def test_init_prefers_app_token_over_param(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "stronghold.tools.github._get_app_installation_token",
            lambda bot="gatekeeper": "app_tok",
        )
        exec_ = GitHubToolExecutor(token="pat")
        assert exec_._headers()["Authorization"] == "Bearer app_tok"

    def test_init_falls_back_to_param_when_app_token_empty(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "stronghold.tools.github._get_app_installation_token",
            lambda bot="gatekeeper": "",
        )
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        exec_ = GitHubToolExecutor(token="pat")
        assert exec_._headers()["Authorization"] == "Bearer pat"

    def test_init_falls_back_to_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "stronghold.tools.github._get_app_installation_token",
            lambda bot="gatekeeper": "",
        )
        monkeypatch.setenv("GITHUB_TOKEN", "envtok")
        exec_ = GitHubToolExecutor(token="")
        assert exec_._headers()["Authorization"] == "Bearer envtok"

    def test_headers_omit_authorization_when_no_token(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "stronghold.tools.github._get_app_installation_token",
            lambda bot="gatekeeper": "",
        )
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        exec_ = GitHubToolExecutor(token="")
        headers = exec_._headers()
        assert "Authorization" not in headers
        assert headers["Accept"] == "application/vnd.github+json"
        assert headers["X-GitHub-Api-Version"] == "2022-11-28"

    def test_name_property_is_github(self) -> None:
        assert GitHubToolExecutor(token="x").name == "github"


# ─────────────────────────────────────────────────────────────────────
# execute() dispatcher — lines 193, 263
# ─────────────────────────────────────────────────────────────────────


class TestExecuteDispatcher:
    async def test_execute_unknown_action_returns_error(self) -> None:
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({"action": "nope", "owner": "o", "repo": "r"})
        assert not result.success
        assert result.error == "Unknown GitHub action: nope"

    async def test_execute_missing_action_key_returns_error(self) -> None:
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({"owner": "o", "repo": "r"})
        assert not result.success
        assert result.error == "Unknown GitHub action: "

    @respx.mock
    async def test_execute_handler_exception_becomes_error_result(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        respx.get("https://api.github.com/repos/o/r/issues/42").mock(
            side_effect=httpx.ConnectError("blown up")
        )
        exec_ = GitHubToolExecutor(token="x")
        with caplog.at_level(logging.WARNING, logger="stronghold.tools.github"):
            result = await exec_.execute(
                {"action": "get_issue", "owner": "o", "repo": "r", "issue_number": 42},
            )
        assert not result.success
        assert result.error
        assert any("GitHub tool error" in rec.message for rec in caplog.records)

    @respx.mock
    async def test_execute_success_serializes_json(self) -> None:
        respx.get("https://api.github.com/repos/o/r/issues/42").mock(
            return_value=httpx.Response(
                200,
                json={
                    "number": 42, "title": "t", "body": "b",
                    "state": "open", "labels": [], "assignee": None,
                },
            ),
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute(
            {"action": "get_issue", "owner": "o", "repo": "r", "issue_number": 42},
        )
        assert result.success
        assert json.loads(result.content)["number"] == 42


# ─────────────────────────────────────────────────────────────────────
# _submit_review (419-447)
# ─────────────────────────────────────────────────────────────────────


class TestSubmitReview:
    async def test_submit_review_rejects_invalid_event(self) -> None:
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "submit_review",
            "owner": "o", "repo": "r", "issue_number": 1,
            "event": "LGTM",
        })
        assert result.success  # handler returned dict, execute() serializes it
        data = json.loads(result.content)
        assert "Invalid review event: LGTM" in data["error"]

    async def test_submit_review_rejects_request_changes_without_body(self) -> None:
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "submit_review",
            "owner": "o", "repo": "r", "issue_number": 1,
            "event": "REQUEST_CHANGES", "body": "",
        })
        assert result.success
        data = json.loads(result.content)
        assert data["error"] == "body is required for REQUEST_CHANGES reviews"

    @respx.mock
    async def test_submit_review_approve_omits_body_when_empty(self) -> None:
        route = respx.post(
            "https://api.github.com/repos/o/r/pulls/1/reviews"
        ).mock(
            return_value=httpx.Response(200, json={
                "id": 7, "state": "APPROVED",
                "user": {"login": "bot"},
                "submitted_at": "2026-04-17T00:00:00Z",
            })
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "submit_review",
            "owner": "o", "repo": "r", "issue_number": 1,
            "event": "APPROVE",
        })
        assert result.success
        sent = json.loads(route.calls[0].request.content)
        assert sent == {"event": "APPROVE"}
        data = json.loads(result.content)
        assert {"id", "state", "user", "submitted_at"} <= data.keys()

    @respx.mock
    async def test_submit_review_comment_with_body(self) -> None:
        route = respx.post(
            "https://api.github.com/repos/o/r/pulls/1/reviews"
        ).mock(
            return_value=httpx.Response(200, json={
                "id": 1, "state": "COMMENTED",
                "user": {"login": "b"}, "submitted_at": "x",
            })
        )
        exec_ = GitHubToolExecutor(token="x")
        await exec_.execute({
            "action": "submit_review",
            "owner": "o", "repo": "r", "issue_number": 1,
            "event": "COMMENT", "body": "nit",
        })
        sent = json.loads(route.calls[0].request.content)
        assert sent == {"event": "COMMENT", "body": "nit"}

    @respx.mock
    async def test_submit_review_normalizes_lowercase_event(self) -> None:
        route = respx.post(
            "https://api.github.com/repos/o/r/pulls/1/reviews"
        ).mock(
            return_value=httpx.Response(200, json={
                "id": 1, "state": "APPROVED",
                "user": {"login": "b"}, "submitted_at": "x",
            })
        )
        exec_ = GitHubToolExecutor(token="x")
        await exec_.execute({
            "action": "submit_review",
            "owner": "o", "repo": "r", "issue_number": 1,
            "event": "approve",
        })
        sent = json.loads(route.calls[0].request.content)
        assert sent["event"] == "APPROVE"

    @respx.mock
    async def test_submit_review_missing_submitted_at_returns_empty_string(self) -> None:
        respx.post("https://api.github.com/repos/o/r/pulls/1/reviews").mock(
            return_value=httpx.Response(200, json={
                "id": 1, "state": "COMMENTED", "user": {"login": "b"},
            })
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "submit_review",
            "owner": "o", "repo": "r", "issue_number": 1,
            "event": "COMMENT", "body": "ok",
        })
        data = json.loads(result.content)
        assert data["submitted_at"] == ""


# ─────────────────────────────────────────────────────────────────────
# _close_pr (456-468)
# ─────────────────────────────────────────────────────────────────────


class TestClosePR:
    @respx.mock
    async def test_close_pr_sends_patch_with_closed_state(self) -> None:
        route = respx.patch("https://api.github.com/repos/o/r/pulls/7").mock(
            return_value=httpx.Response(200, json={"number": 7, "state": "closed"})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "close_pr", "owner": "o", "repo": "r", "issue_number": 7,
        })
        assert result.success
        sent = json.loads(route.calls[0].request.content)
        assert sent == {"state": "closed"}
        assert json.loads(result.content) == {"state": "closed", "number": "7"}

    @respx.mock
    async def test_close_pr_propagates_404(self) -> None:
        respx.patch("https://api.github.com/repos/o/r/pulls/7").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "close_pr", "owner": "o", "repo": "r", "issue_number": 7,
        })
        assert not result.success
        assert result.error


# ─────────────────────────────────────────────────────────────────────
# _merge_pr (472-486)
# ─────────────────────────────────────────────────────────────────────


class TestMergePR:
    @respx.mock
    async def test_merge_pr_default_method_is_squash(self) -> None:
        route = respx.put("https://api.github.com/repos/o/r/pulls/9/merge").mock(
            return_value=httpx.Response(200, json={"merged": True, "sha": "a", "message": "m"})
        )
        exec_ = GitHubToolExecutor(token="x")
        await exec_.execute({
            "action": "merge_pr", "owner": "o", "repo": "r", "issue_number": 9,
        })
        sent = json.loads(route.calls[0].request.content)
        assert sent == {"merge_method": "squash"}

    @respx.mock
    async def test_merge_pr_honors_explicit_merge_method(self) -> None:
        route = respx.put("https://api.github.com/repos/o/r/pulls/9/merge").mock(
            return_value=httpx.Response(200, json={"merged": True, "sha": "a", "message": "m"})
        )
        exec_ = GitHubToolExecutor(token="x")
        await exec_.execute({
            "action": "merge_pr", "owner": "o", "repo": "r", "issue_number": 9,
            "merge_method": "rebase",
        })
        sent = json.loads(route.calls[0].request.content)
        assert sent["merge_method"] == "rebase"

    @respx.mock
    async def test_merge_pr_defaults_when_response_fields_missing(self) -> None:
        respx.put("https://api.github.com/repos/o/r/pulls/9/merge").mock(
            return_value=httpx.Response(200, json={})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "merge_pr", "owner": "o", "repo": "r", "issue_number": 9,
        })
        assert result.success
        data = json.loads(result.content)
        assert data == {"merged": False, "sha": "", "message": ""}

    @respx.mock
    async def test_merge_pr_passes_through_sha_and_message(self) -> None:
        respx.put("https://api.github.com/repos/o/r/pulls/9/merge").mock(
            return_value=httpx.Response(
                200, json={"merged": True, "sha": "abc", "message": "Merged"},
            )
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "merge_pr", "owner": "o", "repo": "r", "issue_number": 9,
        })
        data = json.loads(result.content)
        assert data == {"merged": True, "sha": "abc", "message": "Merged"}


# ─────────────────────────────────────────────────────────────────────
# _add_labels (494-507)
# ─────────────────────────────────────────────────────────────────────


class TestAddLabels:
    @respx.mock
    async def test_add_labels_returns_names_only(self) -> None:
        respx.post("https://api.github.com/repos/o/r/issues/3/labels").mock(
            return_value=httpx.Response(
                200, json=[{"name": "bug", "color": "red"}, {"name": "p1"}],
            )
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "add_labels", "owner": "o", "repo": "r",
            "issue_number": 3, "labels": ["bug", "p1"],
        })
        assert result.success
        assert json.loads(result.content) == ["bug", "p1"]

    @respx.mock
    async def test_add_labels_empty_input(self) -> None:
        route = respx.post("https://api.github.com/repos/o/r/issues/3/labels").mock(
            return_value=httpx.Response(200, json=[])
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "add_labels", "owner": "o", "repo": "r",
            "issue_number": 3,
        })
        assert result.success
        sent = json.loads(route.calls[0].request.content)
        assert sent == {"labels": []}
        assert json.loads(result.content) == []

    @respx.mock
    async def test_add_labels_propagates_422_validation_error(self) -> None:
        respx.post("https://api.github.com/repos/o/r/issues/3/labels").mock(
            return_value=httpx.Response(422, json={"message": "Validation"})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "add_labels", "owner": "o", "repo": "r",
            "issue_number": 3, "labels": ["x"],
        })
        assert not result.success


# ─────────────────────────────────────────────────────────────────────
# _remove_label (511-525)
# ─────────────────────────────────────────────────────────────────────


class TestRemoveLabel:
    @respx.mock
    async def test_remove_label_success(self) -> None:
        respx.delete("https://api.github.com/repos/o/r/issues/3/labels/wip").mock(
            return_value=httpx.Response(200, json=[])
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "remove_label", "owner": "o", "repo": "r",
            "issue_number": 3, "label": "wip",
        })
        assert result.success
        assert json.loads(result.content) == {"status": "removed", "label": "wip"}

    @respx.mock
    async def test_remove_label_404_is_soft_ok(self) -> None:
        respx.delete("https://api.github.com/repos/o/r/issues/3/labels/wip").mock(
            return_value=httpx.Response(404, json={"message": "Not Found"})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "remove_label", "owner": "o", "repo": "r",
            "issue_number": 3, "label": "wip",
        })
        assert result.success
        assert json.loads(result.content) == {"status": "not_found", "label": "wip"}

    @respx.mock
    async def test_remove_label_500_propagates(self) -> None:
        respx.delete("https://api.github.com/repos/o/r/issues/3/labels/wip").mock(
            return_value=httpx.Response(500, json={"message": "server error"})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "remove_label", "owner": "o", "repo": "r",
            "issue_number": 3, "label": "wip",
        })
        assert not result.success
        assert "500" in (result.error or "")


# ─────────────────────────────────────────────────────────────────────
# _close_issue (529-541)
# ─────────────────────────────────────────────────────────────────────


class TestCloseIssue:
    @respx.mock
    async def test_close_issue_sends_patch(self) -> None:
        route = respx.patch("https://api.github.com/repos/o/r/issues/5").mock(
            return_value=httpx.Response(200, json={"number": 5, "state": "closed"})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "close_issue", "owner": "o", "repo": "r", "issue_number": 5,
        })
        assert result.success
        sent = json.loads(route.calls[0].request.content)
        assert sent == {"state": "closed"}
        assert json.loads(result.content) == {"state": "closed", "number": "5"}

    @respx.mock
    async def test_close_issue_propagates_422(self) -> None:
        respx.patch("https://api.github.com/repos/o/r/issues/5").mock(
            return_value=httpx.Response(422, json={"message": "bad"})
        )
        exec_ = GitHubToolExecutor(token="x")
        result = await exec_.execute({
            "action": "close_issue", "owner": "o", "repo": "r", "issue_number": 5,
        })
        assert not result.success


class TestListIssuesMultiPage:
    """Exercise the page += 1 branch: a batch of exactly per_page forces a second fetch."""

    @respx.mock
    async def test_list_issues_walks_multiple_pages(self) -> None:
        # per_page=2 (forces 2 pages). First page: 2 items (full). Second: 0 items → break.
        full_batch = [
            {
                "number": 1, "title": "a", "state": "open",
                "labels": [], "assignee": None,
            },
            {
                "number": 2, "title": "b", "state": "open",
                "labels": [], "assignee": None,
            },
        ]
        # respx matches the URL without query; both pages go to the same mock,
        # but we can switch response via side_effect on the route.
        route = respx.get("https://api.github.com/repos/org/repo/issues")
        # Return full batch on first call, empty on subsequent calls.
        calls_ref = {"n": 0}

        def _respond(request):  # type: ignore[no-untyped-def]
            calls_ref["n"] += 1
            if calls_ref["n"] == 1:
                return httpx.Response(200, json=full_batch)
            return httpx.Response(200, json=[])

        route.mock(side_effect=_respond)
        executor = GitHubToolExecutor(token="t")
        result = await executor.execute({
            "action": "list_issues", "owner": "org", "repo": "repo",
            "per_page": 2, "max_pages": 3,
        })
        assert result.success
        issues = json.loads(result.content)
        assert len(issues) == 2
        assert calls_ref["n"] == 2  # confirmed we walked into page 2
