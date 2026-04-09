from __future__ import annotations

import pytest

from stronghold.builders.pipeline import RuntimePipeline


def test_quartermaster_single_file_section() -> None:
    body = (
        "## Description\n"
        "Create the optimization suggestions system.\n"
        "\n"
        "## Acceptance Criteria\n"
        "- [ ] Class CostOptimizer\n"
        "\n"
        "## Files\n"
        "- src/stronghold/analytics/suggestions.py\n"
        "\n"
        "---\n"
        "_Sub-issue of #136, step 7 of 10_\n"
    )
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/analytics/suggestions.py",
    ]


def test_multiple_files_in_order() -> None:
    body = (
        "## Files\n"
        "- src/stronghold/agents/warden_at_arms/agent.yaml\n"
        "- tests/agents/test_warden_at_arms.py\n"
    )
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/agents/warden_at_arms/agent.yaml",
        "tests/agents/test_warden_at_arms.py",
    ]


def test_returns_empty_list_when_no_files_section() -> None:
    body = "## Description\nrandom prose.\n\n## Acceptance Criteria\n- thing\n"
    assert RuntimePipeline._extract_files_from_issue_body(body) == []


def test_alternate_header_files_to_create() -> None:
    body = "## Files to create\n- src/stronghold/foo.py\n- src/stronghold/bar.py\n"
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/foo.py",
        "src/stronghold/bar.py",
    ]


def test_alternate_header_files_to_modify() -> None:
    body = "## Files to modify\n- src/stronghold/api/routes/status.py\n"
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/api/routes/status.py",
    ]


def test_strips_backticks_and_trailing_prose() -> None:
    body = (
        "## Files\n"
        "- `src/stronghold/baz.py`  (new module)\n"
        "- src/stronghold/qux.py — adds helper\n"
    )
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/baz.py",
        "src/stronghold/qux.py",
    ]


def test_supports_mixed_bullet_styles() -> None:
    body = (
        "## Files\n"
        "* src/stronghold/api/routes/optimization.py\n"
        "- src/stronghold/api/routes/status.py\n"
    )
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/api/routes/optimization.py",
        "src/stronghold/api/routes/status.py",
    ]


def test_deduplicates_repeated_paths() -> None:
    body = (
        "## Files\n"
        "- src/stronghold/foo.py\n"
        "- src/stronghold/bar.py\n"
        "- src/stronghold/foo.py\n"
    )
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/foo.py",
        "src/stronghold/bar.py",
    ]


def test_case_insensitive_header() -> None:
    body = "## FILES\n- src/stronghold/foo.py\n"
    assert RuntimePipeline._extract_files_from_issue_body(body) == [
        "src/stronghold/foo.py",
    ]


def test_ignores_files_section_buried_inside_prose() -> None:
    """A '## Files' header that has no bullet list immediately under it
    should not match — we only care about Quartermaster-style structured
    file lists, not casual prose mentions of files.
    """
    body = (
        "## Files\n"
        "\n"
        "We'll figure out the file structure later.\n"
    )
    assert RuntimePipeline._extract_files_from_issue_body(body) == []
