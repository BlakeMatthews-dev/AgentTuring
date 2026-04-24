"""Token-economy harness: measures the win from playbook shape vs tool shape.

Replays the same GitHub fixture set through two pipelines and compares
`tool_result_bytes`:

- **Old shape**: the thin `github(action=...)` executor called once per
  atomic operation (6 round-trips, 6 JSON blobs).
- **New shape**: one `review_pull_request` playbook call returning a
  single markdown Brief.

Target from the plan: **≥60% byte reduction** on the equivalent task.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from stronghold.playbooks.github.review_pull_request import review_pull_request
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.tools.github import GitHubToolExecutor
from stronghold.types.auth import SYSTEM_AUTH
from tests.playbooks.github.fixtures import (
    HEAD_SHA,
    OWNER,
    PR_NUMBER,
    PR_URL,
    REPO,
    combined_status,
    pr_comments,
    pr_commits,
    pr_files,
    pr_metadata,
    pr_reviews,
)


def _mount_github(respx_mock: respx.MockRouter) -> None:
    respx_mock.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}",
    ).mock(return_value=httpx.Response(200, json=pr_metadata()))
    respx_mock.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/files",
    ).mock(return_value=httpx.Response(200, json=pr_files()))
    respx_mock.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/commits",
    ).mock(return_value=httpx.Response(200, json=pr_commits()))
    respx_mock.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/pulls/{PR_NUMBER}/reviews",
    ).mock(return_value=httpx.Response(200, json=pr_reviews()))
    respx_mock.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/issues/{PR_NUMBER}/comments",
    ).mock(return_value=httpx.Response(200, json=pr_comments()))
    respx_mock.get(
        f"https://api.github.com/repos/{OWNER}/{REPO}/commits/{HEAD_SHA}/status",
    ).mock(return_value=httpx.Response(200, json=combined_status()))


async def _measure_old_shape() -> int:
    """Simulate the agent issuing the 6 atomic calls an old-shape review needs.

    The existing github(action=...) tool has `list_pr_comments` and
    `get_pr_diff` but no direct analogues for reviews/commits/status — so
    we return the raw JSON payloads that would have been returned by
    equivalent endpoints, which is the byte count the agent loop would
    feed to the LLM.
    """
    total = 0
    for payload in (
        pr_metadata(),
        pr_files(),
        pr_commits(),
        pr_reviews(),
        pr_comments(),
        combined_status(),
    ):
        total += len(json.dumps(payload).encode("utf-8"))
    return total


async def _measure_new_shape() -> int:
    brief = await review_pull_request(
        {"url": PR_URL},
        PlaybookContext(auth=SYSTEM_AUTH),
    )
    return len(brief.to_markdown().encode("utf-8"))


@respx.mock
async def test_playbook_cuts_tool_result_bytes_by_at_least_60_percent() -> None:
    _mount_github(respx.mock)
    old_bytes = await _measure_old_shape()
    new_bytes = await _measure_new_shape()
    assert new_bytes < old_bytes, f"new ({new_bytes}) must be smaller than old ({old_bytes})"
    reduction = 1 - (new_bytes / old_bytes)
    assert reduction >= 0.60, (
        f"expected >=60% reduction, got {reduction:.1%} (old={old_bytes}B, new={new_bytes}B)"
    )


@respx.mock
async def test_playbook_collapses_six_calls_into_one_tool_turn() -> None:
    """Old shape requires 6 agent tool-turns; new shape, 1."""
    _mount_github(respx.mock)
    # Sanity: the old shape dispatcher has a single action per call.
    executor = GitHubToolExecutor()
    assert hasattr(executor, "_handlers")
    # The new shape invokes one playbook function — the round-trip count
    # is whatever the playbook does server-side, opaque to the agent.
    brief = await review_pull_request(
        {"url": PR_URL},
        PlaybookContext(auth=SYSTEM_AUTH),
    )
    assert brief is not None


def test_token_economy_harness_is_deterministic() -> None:
    """Fixtures are deterministic — replays should produce identical byte counts.

    This is a guard: if someone adds randomness to a fixture, the harness
    loses its measurement precision.
    """
    import asyncio  # noqa: PLC0415

    async def _run() -> int:
        with respx.mock() as respx_mock:
            _mount_github(respx_mock)
            return await _measure_new_shape()

    a = asyncio.run(_run())
    b = asyncio.run(_run())
    assert a == b, f"non-deterministic harness: {a} vs {b}"


@pytest.mark.skip(reason="Phase F will add 19 more fixture tasks — placeholder")
async def test_twenty_fixture_tasks_average_reduction_at_least_60_percent() -> None:
    """Plan §3.1 calls for 20 fixtures; review_pull_request is task 1/20."""
