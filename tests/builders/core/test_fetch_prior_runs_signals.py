"""Unit-level coverage for the regex shape used by _fetch_prior_runs.

The full method is async and reads from a tool dispatcher; testing it
end-to-end would require fakes for the GitHub tool. The regex
constants themselves are pure and module-level, so we import them
directly from pipeline.py — any future change to either pattern
without an accompanying test update will fail loudly.
"""
from __future__ import annotations

from stronghold.builders.pipeline import (
    BUILDERS_RUN_PATTERN,
    GATEKEEPER_VERDICT_PATTERN,
)


# ── Builders Run regex ──────────────────────────────────────────────


def test_run_id_pattern_matches_manual_run_prefix() -> None:
    body = "## Builders Run `run-f23c8f66`\n\nIssue analysis follows."
    match = BUILDERS_RUN_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "run-f23c8f66"


def test_run_id_pattern_matches_scheduler_sched_prefix() -> None:
    body = "## Builders Run `sched-bac9832f`\n\nFrank executing acceptance_defined."
    match = BUILDERS_RUN_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "sched-bac9832f"


def test_run_id_pattern_matches_unbacktick_form() -> None:
    body = "## Builders Run sched-abc1234\n"
    match = BUILDERS_RUN_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "sched-abc1234"


def test_run_id_pattern_rejects_unrelated_prefixes() -> None:
    body = "## Builders Run `manual-12345`\n"
    match = BUILDERS_RUN_PATTERN.search(body)
    assert match is None


def test_run_id_pattern_rejects_non_builders_comments() -> None:
    body = "## Auditor Review: `tests_written` (attempt 1)\n\nVerdict: APPROVED"
    match = BUILDERS_RUN_PATTERN.search(body)
    assert match is None


# ── Gatekeeper Verdict regex ────────────────────────────────────────


def test_gatekeeper_pattern_matches_basic_verdict() -> None:
    body = "## Gatekeeper Verdict on PR #943\n\n**Decision:** REQUEST_CHANGES"
    match = GATEKEEPER_VERDICT_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "943"


def test_gatekeeper_pattern_matches_no_space_before_hash() -> None:
    body = "## Gatekeeper Verdict on PR#56\n"
    match = GATEKEEPER_VERDICT_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "56"


def test_gatekeeper_pattern_is_case_insensitive() -> None:
    body = "## gatekeeper verdict on pr #999\n"
    match = GATEKEEPER_VERDICT_PATTERN.search(body)
    assert match is not None
    assert match.group(1) == "999"


def test_gatekeeper_pattern_rejects_non_verdict_mentions() -> None:
    body = "We discussed the Gatekeeper verdict for PR 42 earlier."
    match = GATEKEEPER_VERDICT_PATTERN.search(body)
    assert match is None


def test_gatekeeper_pattern_rejects_auditor_reviews() -> None:
    body = "## Auditor Review: `acceptance_defined` (attempt 1)\n"
    match = GATEKEEPER_VERDICT_PATTERN.search(body)
    assert match is None


# ── Disjoint patterns: same body never matches both ─────────────────


def test_run_and_gatekeeper_patterns_are_disjoint() -> None:
    """A single comment body should not match both patterns —
    _fetch_prior_runs uses an else-branch and we want to make sure
    the categorization is unambiguous."""
    builders_body = "## Builders Run `sched-deadbeef`\n"
    gatekeeper_body = "## Gatekeeper Verdict on PR #100\n"

    assert BUILDERS_RUN_PATTERN.search(builders_body) is not None
    assert GATEKEEPER_VERDICT_PATTERN.search(builders_body) is None

    assert BUILDERS_RUN_PATTERN.search(gatekeeper_body) is None
    assert GATEKEEPER_VERDICT_PATTERN.search(gatekeeper_body) is not None


# ── End-to-end coverage of _fetch_prior_runs with a fake dispatcher ─
#
# These tests exercise the actual method (not just the regex) so
# changes to the iteration / filtering logic are caught too. The
# fake dispatcher only needs to implement execute(name, args).


import json
import pytest

from stronghold.builders.pipeline import RuntimePipeline


class _FakeDispatcher:
    """Minimal tool dispatcher that returns canned JSON for github
    list_issue_comments calls and asserts it isn't called for anything
    else (the test should be fully insulated from real I/O)."""

    def __init__(self, comments: list[dict]) -> None:
        self._comments = comments
        self.call_count = 0

    async def execute(self, name: str, args: dict) -> str:
        self.call_count += 1
        assert name == "github", f"unexpected tool: {name}"
        assert args.get("action") == "list_issue_comments"
        return json.dumps(self._comments)


def _make_pipeline(comments: list[dict]) -> RuntimePipeline:
    return RuntimePipeline(llm=None, tool_dispatcher=_FakeDispatcher(comments))


@pytest.mark.asyncio
async def test_fetch_prior_runs_picks_up_scheduler_dispatched_runs() -> None:
    """Regression test for the original bug: scheduler-dispatched
    runs use `sched-` IDs but the old regex only matched `run-`."""
    pipeline = _make_pipeline(
        [
            {"id": 1, "body": "## Builders Run `sched-bac9832f`\n\nFrank started."},
            {"id": 2, "body": "## Auditor Review: `issue_analyzed` (attempt 1)"},
        ]
    )
    runs = await pipeline._fetch_prior_runs("org", "repo", 42)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "sched-bac9832f"


@pytest.mark.asyncio
async def test_fetch_prior_runs_picks_up_gatekeeper_verdicts() -> None:
    """Regression test for the second half of the bug: Gatekeeper
    verdicts were never picked up so Mason couldn't see rejections."""
    pipeline = _make_pipeline(
        [
            {"id": 100, "body": "## Gatekeeper Verdict on PR #943\n\n**Decision:** REQUEST_CHANGES\n\nMissing tests."},
        ]
    )
    runs = await pipeline._fetch_prior_runs("org", "repo", 42)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "gatekeeper-pr943-100"
    assert "REQUEST_CHANGES" in runs[0]["summary"]


@pytest.mark.asyncio
async def test_fetch_prior_runs_multiple_gatekeeper_verdicts_unique_ids() -> None:
    """Multiple Gatekeeper rejections on the same PR each get a
    unique synthesized id (was a collision before the comment-id
    suffix was added). All three verdicts should appear in the
    prior_runs list independently so Frank's prompt sees all of
    them."""
    pipeline = _make_pipeline(
        [
            {"id": 100, "body": "## Gatekeeper Verdict on PR #943\n\nFirst reject."},
            {"id": 200, "body": "## Gatekeeper Verdict on PR #943\n\nSecond reject."},
            {"id": 300, "body": "## Gatekeeper Verdict on PR #943\n\nThird reject."},
        ]
    )
    runs = await pipeline._fetch_prior_runs("org", "repo", 42)
    assert len(runs) == 3
    ids = [r["run_id"] for r in runs]
    assert ids == [
        "gatekeeper-pr943-100",
        "gatekeeper-pr943-200",
        "gatekeeper-pr943-300",
    ]


@pytest.mark.asyncio
async def test_fetch_prior_runs_mixes_runs_and_verdicts() -> None:
    """A real conversation has interleaved Builders Run and Gatekeeper
    Verdict comments. _fetch_prior_runs should return all of them in
    document order."""
    pipeline = _make_pipeline(
        [
            {"id": 1, "body": "## Builders Run `sched-aaaa1111`\n"},
            {"id": 2, "body": "## Gatekeeper Verdict on PR #100\n\nRequest changes."},
            {"id": 3, "body": "## Builders Run `run-bbbb2222`\n"},
            {"id": 4, "body": "Just a chat comment from a user."},
        ]
    )
    runs = await pipeline._fetch_prior_runs("org", "repo", 42)
    ids = [r["run_id"] for r in runs]
    assert ids == [
        "sched-aaaa1111",
        "gatekeeper-pr100-2",
        "run-bbbb2222",
    ]


@pytest.mark.asyncio
async def test_fetch_prior_runs_excludes_current_run_id() -> None:
    """exclude_run_id prevents Mason from seeing its own current run
    in the prior history. Applies only to Builders Run ids — gatekeeper
    ids are never excluded since the current run can't have one."""
    pipeline = _make_pipeline(
        [
            {"id": 1, "body": "## Builders Run `sched-aaaa1111`\n"},
            {"id": 2, "body": "## Builders Run `sched-bbbb2222`\n"},
        ]
    )
    runs = await pipeline._fetch_prior_runs(
        "org", "repo", 42, exclude_run_id="sched-aaaa1111",
    )
    assert len(runs) == 1
    assert runs[0]["run_id"] == "sched-bbbb2222"


@pytest.mark.asyncio
async def test_fetch_prior_runs_returns_empty_on_tool_error() -> None:
    """When the github tool returns an Error: prefix, the function
    returns an empty list rather than raising."""

    class _ErrorDispatcher:
        async def execute(self, name: str, args: dict) -> str:
            return "Error: GitHub API rate limit exceeded"

    pipeline = RuntimePipeline(llm=None, tool_dispatcher=_ErrorDispatcher())
    runs = await pipeline._fetch_prior_runs("org", "repo", 42)
    assert runs == []


@pytest.mark.asyncio
async def test_fetch_prior_runs_returns_empty_on_malformed_json() -> None:
    """Malformed JSON from the tool returns an empty list rather
    than raising."""

    class _BadJsonDispatcher:
        async def execute(self, name: str, args: dict) -> str:
            return "this is not json"

    pipeline = RuntimePipeline(llm=None, tool_dispatcher=_BadJsonDispatcher())
    runs = await pipeline._fetch_prior_runs("org", "repo", 42)
    assert runs == []


@pytest.mark.asyncio
async def test_fetch_prior_runs_skips_non_dict_comments() -> None:
    """Defensive: a malformed entry in the comments list (e.g., a
    string instead of a dict) is silently skipped."""
    pipeline = _make_pipeline(
        [
            "this should not be here",  # type: ignore[list-item]
            {"id": 1, "body": "## Builders Run `sched-cccc3333`\n"},
        ]
    )
    runs = await pipeline._fetch_prior_runs("org", "repo", 42)
    assert len(runs) == 1
    assert runs[0]["run_id"] == "sched-cccc3333"
