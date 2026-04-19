"""Tests for stronghold.tools.scanner — codebase scanner for good-first-issues.

Tests all detector functions and the public API using tmp_path directories
with realistic file structures.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from stronghold.tools.scanner import (
    IssueSuggestion,
    detect_missing_docstrings,
    detect_missing_fakes,
    detect_sidebar_inconsistencies,
    detect_todo_fixme,
    detect_untested_modules,
    format_as_github_issue,
    scan_for_good_first_issues,
)

if TYPE_CHECKING:
    from pathlib import Path


class TestIssueSuggestion:
    """Test the IssueSuggestion dataclass."""

    def test_frozen(self) -> None:
        s = IssueSuggestion(
            title="test",
            category="test",
            files=("a.py",),
            description="desc",
            what_youll_learn="learn",
            acceptance_criteria=("crit1",),
        )
        assert s.estimated_scope == "small"
        # Frozen — cannot mutate
        try:
            s.title = "new"  # type: ignore[misc]
            raise AssertionError("Should not be mutable")
        except AttributeError:
            pass

    def test_medium_scope(self) -> None:
        s = IssueSuggestion(
            title="test",
            category="test",
            files=("a.py",),
            description="desc",
            what_youll_learn="learn",
            acceptance_criteria=("crit1",),
            estimated_scope="medium",
        )
        assert s.estimated_scope == "medium"


class TestDetectMissingFakes:
    """Test detect_missing_fakes with tmp_path directories."""

    def test_no_fakes_file(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        tests_dir = tmp_path / "tests"
        src_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)
        # No fakes.py → empty
        result = detect_missing_fakes(src_dir, tests_dir)
        assert result == []

    def test_no_protocols_dir(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        tests_dir = tmp_path / "tests"
        src_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)
        (tests_dir / "fakes.py").write_text("# empty fakes\n")
        result = detect_missing_fakes(src_dir, tests_dir)
        assert result == []

    def test_finds_missing_fake(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        tests_dir = tmp_path / "tests"
        proto_dir = src_dir / "protocols"
        proto_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (proto_dir / "__init__.py").write_text("")
        (proto_dir / "llm.py").write_text(
            "from typing import Protocol\n"
            "class LLMClient(Protocol):\n"
            "    async def complete(self, prompt: str) -> str: ...\n"
        )
        (tests_dir / "fakes.py").write_text("class FakeOther:\n    pass\n")

        result = detect_missing_fakes(src_dir, tests_dir)
        assert len(result) == 1
        assert "FakeLLMClient" in result[0].title
        assert result[0].category == "missing_fake"

    def test_existing_fake_not_flagged(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        tests_dir = tmp_path / "tests"
        proto_dir = src_dir / "protocols"
        proto_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (proto_dir / "__init__.py").write_text("")
        (proto_dir / "llm.py").write_text(
            "from typing import Protocol\n"
            "class LLMClient(Protocol):\n"
            "    async def complete(self) -> str: ...\n"
        )
        (tests_dir / "fakes.py").write_text("class FakeLLMClient:\n    pass\n")

        result = detect_missing_fakes(src_dir, tests_dir)
        assert len(result) == 0

    def test_noop_variant_not_flagged(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src" / "stronghold"
        tests_dir = tmp_path / "tests"
        proto_dir = src_dir / "protocols"
        proto_dir.mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (proto_dir / "__init__.py").write_text("")
        (proto_dir / "auth.py").write_text(
            "from typing import Protocol\nclass AuthProvider(Protocol):\n    pass\n"
        )
        (tests_dir / "fakes.py").write_text("class NoopAuthProvider:\n    pass\n")

        result = detect_missing_fakes(src_dir, tests_dir)
        assert len(result) == 0


class TestDetectMissingDocstrings:
    """Test detect_missing_docstrings."""

    def test_file_with_docstring_not_flagged(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        py = src_dir / "module.py"
        py.write_text('"""Module docstring."""\n' + "x = 1\n" * 25)
        result = detect_missing_docstrings(src_dir)
        assert len(result) == 0

    def test_file_without_docstring_flagged(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        py = src_dir / "module.py"
        lines = "from __future__ import annotations\n" + "x = 1\n" * 25
        py.write_text(lines)
        result = detect_missing_docstrings(src_dir)
        assert len(result) == 1
        assert result[0].category == "missing_docstring"

    def test_short_file_not_flagged(self, tmp_path: Path) -> None:
        """Files under 20 lines should be skipped."""
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        py = src_dir / "tiny.py"
        py.write_text("x = 1\n" * 10)
        result = detect_missing_docstrings(src_dir)
        assert len(result) == 0

    def test_init_files_skipped(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        py = src_dir / "__init__.py"
        py.write_text("x = 1\n" * 25)
        result = detect_missing_docstrings(src_dir)
        assert len(result) == 0

    def test_single_quote_docstring(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        src_dir.mkdir(parents=True)
        py = src_dir / "mod.py"
        py.write_text("'''Single quote docstring.'''\n" + "x = 1\n" * 25)
        result = detect_missing_docstrings(src_dir)
        assert len(result) == 0


class TestDetectSidebarInconsistencies:
    """Test detect_sidebar_inconsistencies."""

    def test_no_dashboard_dir(self, tmp_path: Path) -> None:
        result = detect_sidebar_inconsistencies(tmp_path / "nonexistent")
        assert result == []

    def test_no_index_html(self, tmp_path: Path) -> None:
        dash = tmp_path / "dashboard"
        dash.mkdir()
        result = detect_sidebar_inconsistencies(dash)
        assert result == []

    def test_consistent_pages(self, tmp_path: Path) -> None:
        dash = tmp_path / "dashboard"
        dash.mkdir()
        nav = '<a href="/dashboard/agents">Agents</a>\n<a href="/dashboard/settings">Settings</a>'
        (dash / "index.html").write_text(nav)
        (dash / "agents.html").write_text(nav)
        result = detect_sidebar_inconsistencies(dash)
        assert result == []

    def test_inconsistent_pages_flagged(self, tmp_path: Path) -> None:
        dash = tmp_path / "dashboard"
        dash.mkdir()
        full_nav = (
            '<a href="/dashboard/agents">Agents</a>\n<a href="/dashboard/settings">Settings</a>'
        )
        partial_nav = '<a href="/dashboard/agents">Agents</a>'
        (dash / "index.html").write_text(full_nav)
        (dash / "settings.html").write_text(partial_nav)
        result = detect_sidebar_inconsistencies(dash)
        assert len(result) == 1
        assert result[0].category == "sidebar_inconsistency"

    def test_login_html_skipped(self, tmp_path: Path) -> None:
        """login.html should be excluded from sidebar check."""
        dash = tmp_path / "dashboard"
        dash.mkdir()
        full_nav = '<a href="/dashboard/agents">Agents</a>'
        (dash / "index.html").write_text(full_nav)
        (dash / "login.html").write_text("no links here")
        result = detect_sidebar_inconsistencies(dash)
        assert result == []


class TestDetectUntestedModules:
    """Test detect_untested_modules."""

    def test_tested_module_not_flagged(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        (src_dir / "stronghold").mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (src_dir / "stronghold" / "router.py").write_text("x = 1\n" * 25)
        (tests_dir / "test_router.py").write_text("import router\n" * 5)
        result = detect_untested_modules(src_dir, tests_dir)
        assert len(result) == 0

    def test_untested_module_flagged(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        (src_dir / "stronghold").mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (src_dir / "stronghold" / "classifier.py").write_text("x = 1\n" * 25)
        (tests_dir / "test_other.py").write_text("# nothing here at all\n")
        result = detect_untested_modules(src_dir, tests_dir)
        assert len(result) == 1
        assert result[0].category == "untested_module"
        assert result[0].estimated_scope == "medium"

    def test_init_files_skipped(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        (src_dir / "stronghold").mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (src_dir / "stronghold" / "__init__.py").write_text("x = 1\n" * 25)
        result = detect_untested_modules(src_dir, tests_dir)
        assert len(result) == 0

    def test_small_files_skipped(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        (src_dir / "stronghold").mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (src_dir / "stronghold" / "tiny.py").write_text("x = 1\n" * 10)
        result = detect_untested_modules(src_dir, tests_dir)
        assert len(result) == 0

    def test_import_in_test_counts_as_tested(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        (src_dir / "stronghold").mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        (src_dir / "stronghold" / "special.py").write_text("x = 1\n" * 25)
        (tests_dir / "test_integration.py").write_text("from stronghold.special import something\n")
        result = detect_untested_modules(src_dir, tests_dir)
        assert len(result) == 0


class TestDetectTodoFixme:
    """Test detect_todo_fixme."""

    def test_finds_todo(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        (src_dir / "stronghold").mkdir(parents=True)
        py = src_dir / "stronghold" / "module.py"
        py.write_text("# TODO: implement caching for performance\nx = 1\n")
        result = detect_todo_fixme(src_dir)
        assert len(result) == 1
        assert result[0].category == "todo_fixme"
        assert "TODO" in result[0].title

    def test_finds_fixme(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        (src_dir / "stronghold").mkdir(parents=True)
        py = src_dir / "stronghold" / "module.py"
        py.write_text("# FIXME: this breaks on empty input strings\nx = 1\n")
        result = detect_todo_fixme(src_dir)
        assert len(result) == 1
        assert "FIXME" in result[0].title

    def test_short_descriptions_skipped(self, tmp_path: Path) -> None:
        """TODO with less than 10 chars description is ignored."""
        src_dir = tmp_path / "src"
        (src_dir / "stronghold").mkdir(parents=True)
        py = src_dir / "stronghold" / "module.py"
        py.write_text("# TODO: fix\nx = 1\n")
        result = detect_todo_fixme(src_dir)
        assert len(result) == 0

    def test_hack_and_xxx(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        (src_dir / "stronghold").mkdir(parents=True)
        py = src_dir / "stronghold" / "module.py"
        py.write_text(
            "# HACK: workaround for upstream library bug in v2\n"
            "# XXX: this needs refactoring before next release\n"
        )
        result = detect_todo_fixme(src_dir)
        assert len(result) == 2

    def test_case_insensitive(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        (src_dir / "stronghold").mkdir(parents=True)
        py = src_dir / "stronghold" / "module.py"
        py.write_text("# todo: implement the missing validation logic\nx = 1\n")
        result = detect_todo_fixme(src_dir)
        assert len(result) == 1


class TestScanForGoodFirstIssues:
    """Test the public API scan_for_good_first_issues."""

    def test_empty_project(self, tmp_path: Path) -> None:
        result = scan_for_good_first_issues(tmp_path)
        assert result == []

    def test_with_src_and_tests(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        tests_dir = tmp_path / "tests"
        (src_dir / "stronghold" / "protocols").mkdir(parents=True)
        tests_dir.mkdir(parents=True)

        # Create a TODO in source
        py = src_dir / "stronghold" / "router.py"
        py.write_text("# TODO: add fallback scoring for edge cases\nx = 1\n")

        # Create fakes.py
        (tests_dir / "fakes.py").write_text("# empty\n")

        result = scan_for_good_first_issues(tmp_path)
        assert len(result) >= 1

    def test_dashboard_detection_included(self, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        dash = src_dir / "stronghold" / "dashboard"
        dash.mkdir(parents=True)

        full_nav = '<a href="/dashboard/agents">A</a>\n<a href="/dashboard/settings">S</a>'
        (dash / "index.html").write_text(full_nav)
        (dash / "page.html").write_text('<a href="/dashboard/agents">A</a>')

        result = scan_for_good_first_issues(tmp_path)
        sidebar_results = [r for r in result if r.category == "sidebar_inconsistency"]
        assert len(sidebar_results) == 1


class TestFormatAsGithubIssue:
    """Test format_as_github_issue conversion."""

    def test_produces_valid_payload(self) -> None:
        suggestion = IssueSuggestion(
            title="test: add FakeLLMClient to tests/fakes.py",
            category="missing_fake",
            files=("src/protocols/llm.py", "tests/fakes.py"),
            description="Protocol LLMClient has no fake.",
            what_youll_learn="How DI works.",
            acceptance_criteria=(
                "FakeLLMClient exists",
                "isinstance check passes",
            ),
        )
        payload = format_as_github_issue(suggestion)
        assert payload["title"] == suggestion.title
        assert "good first issue" in payload["labels"]
        assert "## Summary" in payload["body"]
        assert "## Files" in payload["body"]
        assert "## What you'll learn" in payload["body"]
        assert "## Acceptance criteria" in payload["body"]
        assert "## Scope" in payload["body"]
        assert "- [ ] FakeLLMClient exists" in payload["body"]
        assert "`src/protocols/llm.py`" in payload["body"]
