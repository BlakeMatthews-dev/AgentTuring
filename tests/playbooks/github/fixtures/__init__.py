"""Canned GitHub API responses for playbook tests.

Keep these deterministic and small. Playbook tests mount them via respx;
the token-economy harness replays the same fixtures against both shapes
(old github(action=...) and new playbooks) to compare byte counts.
"""

from __future__ import annotations

from typing import Any

OWNER = "acme"
REPO = "widget"
PR_NUMBER = 42
HEAD_SHA = "abc1234def5678"
PR_URL = f"https://github.com/{OWNER}/{REPO}/pull/{PR_NUMBER}"


def _full_user(login: str, uid: int = 1001) -> dict[str, Any]:
    """Realistic GitHub user object — ~17 fields per API docs."""
    return {
        "login": login,
        "id": uid,
        "node_id": f"U_kgDO{uid:016x}",
        "avatar_url": f"https://avatars.githubusercontent.com/u/{uid}?v=4",
        "gravatar_id": "",
        "url": f"https://api.github.com/users/{login}",
        "html_url": f"https://github.com/{login}",
        "followers_url": f"https://api.github.com/users/{login}/followers",
        "following_url": f"https://api.github.com/users/{login}/following{{/other_user}}",
        "gists_url": f"https://api.github.com/users/{login}/gists{{/gist_id}}",
        "starred_url": f"https://api.github.com/users/{login}/starred{{/owner}}{{/repo}}",
        "subscriptions_url": f"https://api.github.com/users/{login}/subscriptions",
        "organizations_url": f"https://api.github.com/users/{login}/orgs",
        "repos_url": f"https://api.github.com/users/{login}/repos",
        "events_url": f"https://api.github.com/users/{login}/events{{/privacy}}",
        "received_events_url": f"https://api.github.com/users/{login}/received_events",
        "type": "User",
        "site_admin": False,
    }


def _full_repo_ref() -> dict[str, Any]:
    """Realistic head/base repo object within a PR — nested repo includes owner, urls, etc."""
    return {
        "repo": {
            "id": 12345678,
            "node_id": "R_kgDOAA12345",
            "name": REPO,
            "full_name": f"{OWNER}/{REPO}",
            "private": False,
            "owner": _full_user(OWNER, 2002),
            "html_url": f"https://github.com/{OWNER}/{REPO}",
            "description": "Widget manufacturing service.",
            "url": f"https://api.github.com/repos/{OWNER}/{REPO}",
            "archive_url": f"https://api.github.com/repos/{OWNER}/{REPO}/{{archive_format}}{{/ref}}",
            "assignees_url": f"https://api.github.com/repos/{OWNER}/{REPO}/assignees{{/user}}",
            "blobs_url": f"https://api.github.com/repos/{OWNER}/{REPO}/git/blobs{{/sha}}",
            "branches_url": f"https://api.github.com/repos/{OWNER}/{REPO}/branches{{/branch}}",
            "collaborators_url": (
                f"https://api.github.com/repos/{OWNER}/{REPO}/collaborators{{/collaborator}}"
            ),
            "comments_url": f"https://api.github.com/repos/{OWNER}/{REPO}/comments{{/number}}",
            "commits_url": f"https://api.github.com/repos/{OWNER}/{REPO}/commits{{/sha}}",
            "default_branch": "main",
            "visibility": "public",
        }
    }


def pr_metadata(*, body: str = "Adds widget support across the build pipeline.") -> dict[str, Any]:
    """PR payload that looks like a real GitHub response (~70 fields nested)."""
    return {
        "url": f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}",
        "id": 99999999,
        "node_id": f"PR_kwDO{PR_NUMBER:016x}",
        "html_url": PR_URL,
        "diff_url": f"{PR_URL}.diff",
        "patch_url": f"{PR_URL}.patch",
        "issue_url": f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUMBER}",
        "commits_url": f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/commits",
        "review_comments_url": (
            f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/comments"
        ),
        "review_comment_url": (
            f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/comments{{/number}}"
        ),
        "comments_url": (
            f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUMBER}/comments"
        ),
        "statuses_url": (f"https://api.github.com/repos/{OWNER}/{REPO}/statuses/{HEAD_SHA}"),
        "number": PR_NUMBER,
        "state": "open",
        "locked": False,
        "title": "Add widget support",
        "body": body,
        "draft": False,
        "mergeable": True,
        "mergeable_state": "clean",
        "merged": False,
        "merged_at": None,
        "merge_commit_sha": None,
        "rebaseable": True,
        "user": _full_user("alice"),
        "assignee": None,
        "assignees": [],
        "requested_reviewers": [_full_user("reviewer0", 3003)],
        "requested_teams": [],
        "labels": [
            {"id": 1, "node_id": "LA_1", "name": "enhancement", "color": "84b6eb"},
            {"id": 2, "node_id": "LA_2", "name": "needs-review", "color": "fbca04"},
        ],
        "milestone": None,
        "head": {"ref": "feature/widget", "sha": HEAD_SHA, **_full_repo_ref()},
        "base": {"ref": "main", "sha": "000aaa1112223334", **_full_repo_ref()},
        "_links": {
            "self": {"href": f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}"},
            "html": {"href": PR_URL},
            "issue": {"href": f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUMBER}"},
            "comments": {
                "href": (f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUMBER}/comments")
            },
            "review_comments": {
                "href": (f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/comments")
            },
            "commits": {
                "href": (f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/commits")
            },
            "statuses": {
                "href": f"https://api.github.com/repos/{OWNER}/{REPO}/statuses/{HEAD_SHA}"
            },
        },
        "author_association": "MEMBER",
        "auto_merge": None,
        "active_lock_reason": None,
        "comments": 1,
        "review_comments": 0,
        "commits": 2,
        "additions": 165,
        "deletions": 2,
        "changed_files": 3,
        "created_at": "2026-04-20T10:00:00Z",
        "updated_at": "2026-04-22T14:30:00Z",
        "closed_at": None,
    }


def _widget_patch(n: int) -> str:
    """Realistic-size diff patches — these dominate file response bytes."""
    lines = [f"@@ -0,0 +1,{n} @@"]
    for i in range(n):
        lines.append(f"+    widget_call_{i:03}({i}, 'process', data={{ 'key': {i} }})")
    return "\n".join(lines)


def pr_files() -> list[dict[str, Any]]:
    """File list with realistic patch sizes — patches are the bulk."""
    return [
        {
            "sha": f"file-sha-{i:04}",
            "filename": filename,
            "status": status,
            "additions": adds,
            "deletions": dels,
            "changes": adds + dels,
            "blob_url": f"https://github.com/{OWNER}/{REPO}/blob/{HEAD_SHA}/{filename}",
            "raw_url": f"https://github.com/{OWNER}/{REPO}/raw/{HEAD_SHA}/{filename}",
            "contents_url": (
                f"https://api.github.com/repos/{OWNER}/{REPO}/contents/{filename}?ref={HEAD_SHA}"
            ),
            "patch": _widget_patch(patch_lines),
        }
        for i, (filename, status, adds, dels, patch_lines) in enumerate(
            [
                ("src/widget.py", "added", 120, 0, 120),
                ("tests/test_widget.py", "added", 40, 0, 40),
                ("README.md", "modified", 5, 2, 7),
            ]
        )
    ]


def pr_commits() -> list[dict[str, Any]]:
    """Commits with full author/committer/verification payloads."""
    return [
        {
            "sha": "abc1234def5678abc1234def5678abc1234def56",
            "node_id": "C_kgDOAA1234",
            "commit": {
                "author": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "date": "2026-04-20T10:00:00Z",
                },
                "committer": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "date": "2026-04-20T10:00:00Z",
                },
                "message": (
                    "feat(widget): add support\n\n"
                    "Implements widget support across the build pipeline."
                ),
                "tree": {
                    "sha": "tree-sha-0001",
                    "url": f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees/tree-sha-0001",
                },
                "url": f"https://api.github.com/repos/{OWNER}/{REPO}/git/commits/abc1234",
                "comment_count": 0,
                "verification": {
                    "verified": True,
                    "reason": "valid",
                    "signature": "-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----",
                    "payload": "commit abc1234 author Alice ...",
                },
            },
            "url": f"https://api.github.com/repos/{OWNER}/{REPO}/commits/abc1234",
            "html_url": f"https://github.com/{OWNER}/{REPO}/commit/abc1234",
            "comments_url": f"https://api.github.com/repos/{OWNER}/{REPO}/commits/abc1234/comments",
            "author": _full_user("alice"),
            "committer": _full_user("alice"),
            "parents": [],
        },
        {
            "sha": "bbb2345efg6789bbb2345efg6789bbb2345efg67",
            "node_id": "C_kgDOAA2345",
            "commit": {
                "author": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "date": "2026-04-21T11:00:00Z",
                },
                "committer": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "date": "2026-04-21T11:00:00Z",
                },
                "message": "test(widget): cover edge cases",
                "tree": {
                    "sha": "tree-sha-0002",
                    "url": f"https://api.github.com/repos/{OWNER}/{REPO}/git/trees/tree-sha-0002",
                },
                "url": f"https://api.github.com/repos/{OWNER}/{REPO}/git/commits/bbb2345",
                "comment_count": 0,
                "verification": {
                    "verified": True,
                    "reason": "valid",
                    "signature": "-----BEGIN PGP SIGNATURE-----\n...\n-----END PGP SIGNATURE-----",
                    "payload": "commit bbb2345 author Alice ...",
                },
            },
            "url": f"https://api.github.com/repos/{OWNER}/{REPO}/commits/bbb2345",
            "html_url": f"https://github.com/{OWNER}/{REPO}/commit/bbb2345",
            "comments_url": f"https://api.github.com/repos/{OWNER}/{REPO}/commits/bbb2345/comments",
            "author": _full_user("alice"),
            "committer": _full_user("alice"),
            "parents": [{"sha": "abc1234def5678abc1234def5678abc1234def56"}],
        },
    ]


def pr_reviews(*, approvals: int = 1, changes: int = 0) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(approvals):
        out.append(
            {
                "id": 100 + i,
                "node_id": f"PRR_kwDO{i:08x}",
                "user": _full_user(f"reviewer{i}", 4000 + i),
                "body": "Looks good. I have some minor suggestions in-line.",
                "state": "APPROVED",
                "submitted_at": "2026-04-22T09:00:00Z",
                "commit_id": HEAD_SHA,
                "html_url": f"{PR_URL}#pullrequestreview-{100 + i}",
                "pull_request_url": (
                    f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}"
                ),
                "author_association": "MEMBER",
                "_links": {
                    "html": {"href": f"{PR_URL}#pullrequestreview-{100 + i}"},
                    "pull_request": {
                        "href": (f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}")
                    },
                },
            }
        )
    for i in range(changes):
        out.append(
            {
                "id": 200 + i,
                "node_id": f"PRR_kwDO{200 + i:08x}",
                "user": _full_user(f"nitpicker{i}", 5000 + i),
                "body": "Please address the review comments before merging.",
                "state": "CHANGES_REQUESTED",
                "submitted_at": "2026-04-22T10:00:00Z",
                "commit_id": HEAD_SHA,
                "html_url": f"{PR_URL}#pullrequestreview-{200 + i}",
                "pull_request_url": (
                    f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}"
                ),
                "author_association": "MEMBER",
                "_links": {
                    "html": {"href": f"{PR_URL}#pullrequestreview-{200 + i}"},
                    "pull_request": {
                        "href": (f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}")
                    },
                },
            }
        )
    return out


def pr_comments(*, extra_bodies: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    base = [
        {
            "url": f"https://api.github.com/repos/{OWNER}/{REPO}/issues/comments/801",
            "html_url": f"{PR_URL}#issuecomment-801",
            "issue_url": (f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUMBER}"),
            "id": 801,
            "node_id": "IC_kwDO0000801",
            "user": _full_user("bob", 6006),
            "created_at": "2026-04-22T08:00:00Z",
            "updated_at": "2026-04-22T08:00:00Z",
            "author_association": "COLLABORATOR",
            "body": "LGTM, but consider renaming the helper.",
            "reactions": {
                "url": (
                    f"https://api.github.com/repos/{OWNER}/{REPO}/issues/comments/801/reactions"
                ),
                "total_count": 0,
                "+1": 0,
                "-1": 0,
                "laugh": 0,
                "hooray": 0,
                "confused": 0,
                "heart": 0,
                "rocket": 0,
                "eyes": 0,
            },
            "performed_via_github_app": None,
        },
    ]
    for idx, body in enumerate(extra_bodies):
        base.append(
            {
                "url": f"https://api.github.com/repos/{OWNER}/{REPO}/issues/comments/{900 + idx}",
                "html_url": f"{PR_URL}#issuecomment-{900 + idx}",
                "issue_url": (f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUMBER}"),
                "id": 900 + idx,
                "node_id": f"IC_kwDO0000{900 + idx}",
                "user": _full_user(f"commenter{idx}", 7000 + idx),
                "created_at": "2026-04-22T09:00:00Z",
                "updated_at": "2026-04-22T09:00:00Z",
                "author_association": "NONE",
                "body": body,
                "reactions": {
                    "url": (
                        f"https://api.github.com/repos/{OWNER}/{REPO}"
                        f"/issues/comments/{900 + idx}/reactions"
                    ),
                    "total_count": 0,
                    "+1": 0,
                    "-1": 0,
                    "laugh": 0,
                    "hooray": 0,
                    "confused": 0,
                    "heart": 0,
                    "rocket": 0,
                    "eyes": 0,
                },
                "performed_via_github_app": None,
            },
        )
    return base


def combined_status(*, state: str = "success") -> dict[str, Any]:
    return {
        "state": state,
        "sha": HEAD_SHA,
        "total_count": 2,
        "statuses": [
            {
                "url": (
                    f"https://api.github.com/repos/{OWNER}/{REPO}/statuses/{HEAD_SHA}/ci-tests"
                ),
                "id": 1001,
                "node_id": "SC_kwDO1001",
                "state": state,
                "description": "pytest",
                "target_url": "https://ci.example.com/runs/1001",
                "context": "ci/tests",
                "created_at": "2026-04-22T08:30:00Z",
                "updated_at": "2026-04-22T08:45:00Z",
                "avatar_url": "https://github.com/avatars/u/1",
            },
            {
                "url": (f"https://api.github.com/repos/{OWNER}/{REPO}/statuses/{HEAD_SHA}/ci-lint"),
                "id": 1002,
                "node_id": "SC_kwDO1002",
                "state": state,
                "description": "ruff",
                "target_url": "https://ci.example.com/runs/1002",
                "context": "ci/lint",
                "created_at": "2026-04-22T08:30:00Z",
                "updated_at": "2026-04-22T08:35:00Z",
                "avatar_url": "https://github.com/avatars/u/1",
            },
        ],
        "repository": {
            "id": 12345678,
            "node_id": "R_kgDOAA12345",
            "name": REPO,
            "full_name": f"{OWNER}/{REPO}",
            "owner": _full_user(OWNER, 2002),
        },
        "commit_url": f"https://api.github.com/repos/{OWNER}/{REPO}/commits/{HEAD_SHA}",
        "url": f"https://api.github.com/repos/{OWNER}/{REPO}/commits/{HEAD_SHA}/status",
    }
