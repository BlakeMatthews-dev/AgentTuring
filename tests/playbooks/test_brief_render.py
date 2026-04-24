"""Brief.to_markdown() rendering: happy path + edge cases."""

from __future__ import annotations

from stronghold.playbooks.brief import (
    DEFAULT_MAX_BYTES,
    SUMMARY_SOFT_LIMIT,
    Brief,
    BriefSection,
    NextAction,
)


def test_minimal_brief_renders_title_only() -> None:
    brief = Brief(title="Hello")
    md = brief.to_markdown()
    assert md.startswith("# Hello")
    assert md.endswith("\n")


def test_brief_with_summary_and_sections() -> None:
    brief = Brief(
        title="PR #42 in acme/widget",
        summary="Author alice. +120/-30 LOC across 4 files. 1 check failing.",
        sections=(
            BriefSection(heading="Diff highlights", body="- src/foo.py: 40 added"),
            BriefSection(heading="Checks", body="- lint: passing\n- tests: failing"),
        ),
    )
    md = brief.to_markdown()
    assert "# PR #42 in acme/widget" in md
    assert "Author alice" in md
    assert "## Diff highlights" in md
    assert "- src/foo.py: 40 added" in md
    assert "## Checks" in md
    assert "- tests: failing" in md


def test_brief_renders_flags_with_prefix() -> None:
    brief = Brief(
        title="Review",
        summary="ok",
        flags=("merge conflicts", "missing code-owner review"),
    )
    md = brief.to_markdown()
    assert "> Flags: merge conflicts, missing code-owner review" in md


def test_brief_omits_flag_prefix_when_empty() -> None:
    brief = Brief(title="Review", summary="clean")
    md = brief.to_markdown()
    assert "> Flags" not in md


def test_next_actions_render_in_whats_next_section() -> None:
    brief = Brief(
        title="Review",
        next_actions=(
            NextAction(
                tool="merge_pull_request",
                args={"url": "https://github.com/a/b/pull/1", "dry_run": True},
                reason="preview the merge plan",
            ),
            NextAction(tool="respond_to_issue", args={}, reason=""),
        ),
    )
    md = brief.to_markdown()
    assert "## What's next" in md
    assert "merge_pull_request" in md
    assert '"url": "https://github.com/a/b/pull/1"' in md
    assert "preview the merge plan" in md
    assert "respond_to_issue" in md


def test_summary_soft_limit_truncates_with_ellipsis() -> None:
    long = "x" * (SUMMARY_SOFT_LIMIT + 50)
    brief = Brief(title="t", summary=long)
    md = brief.to_markdown()
    # ellipsis char used, original summary not fully present
    assert "…" in md
    assert long not in md


def test_budget_truncates_oversize_brief() -> None:
    body = "a" * 10_000
    brief = Brief(
        title="Big",
        summary="large body",
        sections=(BriefSection(heading="Dump", body=body),),
    )
    md = brief.to_markdown(max_bytes=DEFAULT_MAX_BYTES)
    assert len(md.encode("utf-8")) <= DEFAULT_MAX_BYTES
    assert "Truncated" in md


def test_unicode_in_title_and_body_roundtrips() -> None:
    brief = Brief(
        title="レビュー — PR #1",
        summary="done",
        sections=(BriefSection(heading="Détails", body="café ✓"),),
    )
    md = brief.to_markdown()
    assert "レビュー" in md
    assert "Détails" in md
    assert "café" in md


def test_empty_sections_tuple_does_not_emit_headings() -> None:
    brief = Brief(title="t", summary="s", sections=())
    md = brief.to_markdown()
    assert "##" not in md


def test_brief_is_hashable_and_frozen() -> None:
    brief = Brief(title="t", flags=("x",))
    # frozen dataclasses with hashable fields are hashable
    assert hash(brief) == hash(Brief(title="t", flags=("x",)))
