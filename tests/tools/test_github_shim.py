"""github(action=…) shim: verify dispatch to playbooks + deprecation warning."""

from __future__ import annotations

import warnings

import httpx
import respx

from stronghold.tools.github_shim import GithubActionShim


@respx.mock
async def test_shim_list_issues_dispatches_to_triage() -> None:
    respx.mock.get("https://api.github.com/search/issues").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "number": 1,
                        "title": "t",
                        "state": "open",
                        "html_url": "https://github.com/a/b/issues/1",
                        "labels": [],
                    }
                ]
            },
        ),
    )
    shim = GithubActionShim()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = await shim.execute(
            {"action": "list_issues", "owner": "a", "repo": "b", "state": "open"},
        )
    assert result.success is True
    assert "# Triage" in result.content
    assert any(issubclass(w.category, DeprecationWarning) for w in caught)


@respx.mock
async def test_shim_create_pr_dispatches_to_open_pr() -> None:
    respx.mock.post("https://api.github.com/repos/a/b/pulls").mock(
        return_value=httpx.Response(
            201,
            json={"number": 5, "html_url": "https://github.com/a/b/pull/5", "state": "open"},
        ),
    )
    shim = GithubActionShim()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = await shim.execute(
            {
                "action": "create_pr",
                "owner": "a",
                "repo": "b",
                "branch": "feat",
                "title": "t",
            },
        )
    assert result.success is True
    assert "Opened PR #5" in result.content


@respx.mock
async def test_shim_post_pr_comment_dispatches_to_respond() -> None:
    respx.mock.post("https://api.github.com/repos/a/b/issues/9/comments").mock(
        return_value=httpx.Response(201, json={"id": 11, "html_url": "c"}),
    )
    shim = GithubActionShim()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = await shim.execute(
            {
                "action": "post_pr_comment",
                "owner": "a",
                "repo": "b",
                "issue_number": 9,
                "body": "ack",
            },
        )
    assert result.success is True


async def test_shim_unknown_action_without_fallback_returns_error() -> None:
    shim = GithubActionShim()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = await shim.execute({"action": "mystery", "owner": "a", "repo": "b"})
    assert result.success is False
    assert result.error is not None
    assert "no playbook mapping" in result.error


async def test_shim_unknown_action_with_fallback_delegates() -> None:
    class _Fallback:
        async def execute(self, args: dict[str, object]) -> object:
            from stronghold.types.tool import ToolResult  # noqa: PLC0415

            return ToolResult(content=f"fallback:{args['action']}", success=True)

    shim = GithubActionShim(fallback=_Fallback())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        result = await shim.execute({"action": "mystery"})
    assert result.success is True
    assert result.content == "fallback:mystery"
