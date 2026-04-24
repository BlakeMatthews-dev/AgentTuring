"""Smoke tests for the 5 additional GitHub playbooks shipped in phase F.

Each playbook gets: dry-run happy path (write playbooks), live happy path
(with respx mocks), and a representative edge case. Full fixture coverage
stays with review_pull_request; these are breadth tests.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from stronghold.playbooks.brief import Brief
from stronghold.playbooks.github.list_repo_activity import list_repo_activity
from stronghold.playbooks.github.merge_pull_request import merge_pull_request
from stronghold.playbooks.github.open_pull_request import open_pull_request
from stronghold.playbooks.github.respond_to_issue import respond_to_issue
from stronghold.playbooks.github.triage_issues import triage_issues
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.types.auth import SYSTEM_AUTH

OWNER = "acme"
REPO = "widget"


def _ctx() -> PlaybookContext:
    return PlaybookContext(auth=SYSTEM_AUTH)


# --- open_pull_request ---


async def test_open_pr_dry_run_renders_plan_without_upstream() -> None:
    brief = await open_pull_request(
        {
            "repo": f"{OWNER}/{REPO}",
            "branch": "feature/x",
            "title": "Add x",
            "body": "Adds x",
            "dry_run": True,
        },
        _ctx(),
    )
    assert isinstance(brief, Brief)
    assert "Dry-run" in brief.title
    assert "feature/x" in brief.to_markdown()
    assert brief.source_calls == ("(dry-run — no upstream calls)",)


@respx.mock
async def test_open_pr_live_posts_and_returns_url() -> None:
    respx.mock.post(f"https://api.github.com/repos/{OWNER}/{REPO}/pulls").mock(
        return_value=httpx.Response(
            201,
            json={
                "number": 9,
                "html_url": f"https://github.com/{OWNER}/{REPO}/pull/9",
                "state": "open",
            },
        ),
    )
    brief = await open_pull_request(
        {
            "repo": f"{OWNER}/{REPO}",
            "branch": "feature/x",
            "title": "Add x",
            "dry_run": False,
        },
        _ctx(),
    )
    md = brief.to_markdown()
    assert "Opened PR #9" in md
    assert "pull/9" in md


async def test_open_pr_rejects_repo_without_slash() -> None:
    with pytest.raises(ValueError, match="owner/repo"):
        await open_pull_request({"repo": "bad", "branch": "x", "title": "y"}, _ctx())


# --- merge_pull_request ---


def _pr_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "number": 1,
        "head": {"sha": "headsha1234"},
        "mergeable": True,
        "mergeable_state": "clean",
        "draft": False,
    }
    base.update(overrides)
    return base


@respx.mock
async def test_merge_pr_dry_run_shows_plan_and_flags() -> None:
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/1").mock(
        return_value=httpx.Response(
            200, json=_pr_payload(mergeable=False, mergeable_state="dirty")
        ),
    )
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/commits/headsha1234/status").mock(
        return_value=httpx.Response(200, json={"state": "failure", "statuses": []})
    )
    brief = await merge_pull_request(
        {"url": f"https://github.com/{OWNER}/{REPO}/pull/1", "method": "squash", "dry_run": True},
        _ctx(),
    )
    assert "Dry-run" in brief.title
    assert "merge conflicts" in brief.flags
    assert "failing required checks" in brief.flags


@respx.mock
async def test_merge_pr_live_merges() -> None:
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/1").mock(
        return_value=httpx.Response(200, json=_pr_payload()),
    )
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/commits/headsha1234/status").mock(
        return_value=httpx.Response(200, json={"state": "success", "statuses": []})
    )
    respx.mock.put(f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/1/merge").mock(
        return_value=httpx.Response(
            200,
            json={"merged": True, "sha": "newshamergedabcdef1234567"},
        ),
    )
    brief = await merge_pull_request(
        {"url": f"https://github.com/{OWNER}/{REPO}/pull/1", "dry_run": False},
        _ctx(),
    )
    assert "Merged PR #1" in brief.title
    assert "merged=True" in brief.summary


# --- triage_issues ---


@respx.mock
async def test_triage_issues_translates_nl_and_returns_summary() -> None:
    respx.mock.get("https://api.github.com/search/issues").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "number": 11,
                        "title": "auth crashes",
                        "state": "open",
                        "html_url": f"https://github.com/{OWNER}/{REPO}/issues/11",
                        "labels": [{"name": "P0"}, {"name": "bug"}],
                    }
                ]
            },
        ),
    )
    brief = await triage_issues(
        {"repo": f"{OWNER}/{REPO}", "query": "open P0 bugs"},
        _ctx(),
    )
    md = brief.to_markdown()
    assert "auth crashes" in md
    assert "#11" in md
    assert "label:P0" in (brief.source_calls[0])
    assert "label:bug" in (brief.source_calls[0])
    assert "state:open" in (brief.source_calls[0])


@respx.mock
async def test_triage_issues_empty_result_renders_zero_brief() -> None:
    respx.mock.get("https://api.github.com/search/issues").mock(
        return_value=httpx.Response(200, json={"items": []}),
    )
    brief = await triage_issues(
        {"repo": f"{OWNER}/{REPO}", "query": "nonexistent query"},
        _ctx(),
    )
    assert "No matches" in brief.title


# --- respond_to_issue ---


async def test_respond_to_issue_dry_run_comment() -> None:
    brief = await respond_to_issue(
        {
            "url": f"https://github.com/{OWNER}/{REPO}/issues/7",
            "action": "comment",
            "message": "ack",
            "dry_run": True,
        },
        _ctx(),
    )
    assert "Dry-run" in brief.title
    assert brief.source_calls == ("(dry-run — no upstream calls)",)


@respx.mock
async def test_respond_to_issue_live_comment() -> None:
    respx.mock.post(f"https://api.github.com/repos/{OWNER}/{REPO}/issues/7/comments").mock(
        return_value=httpx.Response(201, json={"id": 777, "html_url": "c777"})
    )
    brief = await respond_to_issue(
        {
            "url": f"https://github.com/{OWNER}/{REPO}/issues/7",
            "action": "comment",
            "message": "thanks",
            "dry_run": False,
        },
        _ctx(),
    )
    assert "comment: #7" in brief.title


async def test_respond_to_issue_rejects_unknown_action() -> None:
    with pytest.raises(ValueError, match="Unknown action"):
        await respond_to_issue(
            {"url": f"https://github.com/{OWNER}/{REPO}/issues/1", "action": "nuke"},
            _ctx(),
        )


async def test_respond_to_issue_rejects_empty_comment() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        await respond_to_issue(
            {
                "url": f"https://github.com/{OWNER}/{REPO}/issues/1",
                "action": "comment",
                "dry_run": False,
            },
            _ctx(),
        )


# --- list_repo_activity ---


@respx.mock
async def test_list_repo_activity_summarizes_all_kinds() -> None:
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/pulls").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "number": 10,
                    "title": "X",
                    "state": "open",
                    "html_url": f"https://github.com/{OWNER}/{REPO}/pull/10",
                },
            ],
        ),
    )
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/issues").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "number": 20,
                    "title": "I",
                    "state": "open",
                    "html_url": f"https://github.com/{OWNER}/{REPO}/issues/20",
                },
            ],
        ),
    )
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/commits").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"sha": "abcdef1234567890", "commit": {"message": "fix: x\n\nbody"}},
            ],
        ),
    )
    brief = await list_repo_activity({"repo": f"{OWNER}/{REPO}"}, _ctx())
    md = brief.to_markdown()
    assert "Recent PRs" in md
    assert "Recent issues" in md
    assert "Recent commits" in md
    assert "PRs=1" in brief.summary


@respx.mock
async def test_list_repo_activity_kind_prs_only() -> None:
    respx.mock.get(f"https://api.github.com/repos/{OWNER}/{REPO}/pulls").mock(
        return_value=httpx.Response(200, json=[]),
    )
    brief = await list_repo_activity({"repo": f"{OWNER}/{REPO}", "kind": "prs"}, _ctx())
    assert "issues=0" in brief.summary
    assert "commits=0" in brief.summary
