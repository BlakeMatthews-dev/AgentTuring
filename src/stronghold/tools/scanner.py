"""Codebase scanner — discovers good-first-issue opportunities.

Scans the Stronghold codebase for patterns that indicate approachable
tasks suitable for new contributors. Each detector returns structured
findings that can be converted to GitHub issues.

Design principles:
- Every finding must teach something about codebase architecture
- Difficulty must be genuinely low (mechanical, well-scoped)
- Each finding includes WHAT to do, WHERE to look, and WHAT you'll learn
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class IssueSuggestion:
    """A suggested good-first-issue found by scanning the codebase."""

    title: str
    category: str
    files: tuple[str, ...]
    description: str
    what_youll_learn: str
    acceptance_criteria: tuple[str, ...]
    estimated_scope: str = "small"  # small, medium


# ---------------------------------------------------------------------------
# Detectors — pure functions, each scans for one pattern
# ---------------------------------------------------------------------------


def detect_missing_fakes(
    src_dir: Path,
    tests_dir: Path,
) -> list[IssueSuggestion]:
    """Find protocols without corresponding fakes in tests/fakes.py."""
    fakes_path = tests_dir / "fakes.py"
    if not fakes_path.exists():
        return []

    fakes_content = fakes_path.read_text(encoding="utf-8")
    protocols_dir = src_dir / "protocols"
    if not protocols_dir.is_dir():
        return []

    suggestions: list[IssueSuggestion] = []
    for proto_file in sorted(protocols_dir.glob("*.py")):
        if proto_file.name == "__init__.py":
            continue
        content = proto_file.read_text(encoding="utf-8")
        # Find protocol class names
        for match in re.finditer(r"class\s+(\w+)\(Protocol\)", content):
            proto_name = match.group(1)
            fake_name = f"Fake{proto_name}"
            noop_name = f"Noop{proto_name}"
            if fake_name not in fakes_content and noop_name not in fakes_content:
                suggestions.append(
                    IssueSuggestion(
                        title=f"test: add {fake_name} to tests/fakes.py",
                        category="missing_fake",
                        files=(str(proto_file), "tests/fakes.py"),
                        description=(
                            f"Protocol `{proto_name}` in `{proto_file.name}` has no "
                            f"corresponding fake implementation in `tests/fakes.py`. "
                            f"Add a `{fake_name}` class that implements the protocol "
                            f"with in-memory behavior for testing."
                        ),
                        what_youll_learn=(
                            f"How Stronghold's protocol-driven DI works. You'll read "
                            f"the `{proto_name}` protocol, understand its contract, "
                            f"and build a test double that satisfies it."
                        ),
                        acceptance_criteria=(
                            f"`{fake_name}` class exists in `tests/fakes.py`",
                            f"`isinstance({fake_name}(), {proto_name})` returns True",
                            "All protocol methods are implemented with sensible defaults",
                            "Existing tests still pass",
                        ),
                    )
                )
    return suggestions


def detect_missing_docstrings(
    src_dir: Path,
) -> list[IssueSuggestion]:
    """Find modules without module-level docstrings."""
    suggestions: list[IssueSuggestion] = []
    for py_file in sorted(src_dir.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        content = py_file.read_text(encoding="utf-8")
        lines = content.strip().split("\n")
        # Check if first non-empty, non-future-import line is a docstring
        has_docstring = False
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped == "from __future__ import annotations":
                continue
            if stripped.startswith('"""') or stripped.startswith("'''"):
                has_docstring = True
            break

        if not has_docstring and len(lines) > 20:
            rel = py_file.relative_to(src_dir.parent.parent)
            suggestions.append(
                IssueSuggestion(
                    title=f"docs: add module docstring to {py_file.name}",
                    category="missing_docstring",
                    files=(str(rel),),
                    description=(
                        f"`{rel}` has no module-level docstring. Add a docstring "
                        f"explaining what the module does, its key classes/functions, "
                        f"and how it fits into the architecture."
                    ),
                    what_youll_learn=(
                        f"What `{py_file.stem}` does in Stronghold's architecture. "
                        f"You'll need to read the code and ARCHITECTURE.md to write "
                        f"an accurate description."
                    ),
                    acceptance_criteria=(
                        "Module has a docstring as the first statement",
                        "Docstring explains purpose, not just restates the filename",
                        "No other changes to the file",
                    ),
                    estimated_scope="small",
                )
            )
    return suggestions


def detect_sidebar_inconsistencies(
    dashboard_dir: Path,
) -> list[IssueSuggestion]:
    """Find dashboard pages with inconsistent sidebar navigation."""
    if not dashboard_dir.is_dir():
        return []

    reference_file = dashboard_dir / "index.html"
    if not reference_file.exists():
        return []

    ref_content = reference_file.read_text(encoding="utf-8")
    ref_links = set(re.findall(r'href="(/[^"]+)"', ref_content))
    # Only sidebar links (not script/css)
    nav_pages = ("/greathall", "/prompts")
    ref_links = {lnk for lnk in ref_links if "/dashboard/" in lnk or lnk in nav_pages}

    inconsistent: list[str] = []
    for html_file in sorted(dashboard_dir.glob("*.html")):
        if html_file.name in ("index.html", "login.html"):
            continue
        content = html_file.read_text(encoding="utf-8")
        page_links = set(re.findall(r'href="(/[^"]+)"', content))
        page_links = {lnk for lnk in page_links if "/dashboard/" in lnk or lnk in nav_pages}
        missing = ref_links - page_links
        if missing:
            inconsistent.append(html_file.name)

    if inconsistent:
        return [
            IssueSuggestion(
                title="chore: sync sidebar navigation across all dashboard pages",
                category="sidebar_inconsistency",
                files=tuple(f"src/stronghold/dashboard/{f}" for f in inconsistent),
                description=(
                    f"{len(inconsistent)} dashboard pages have inconsistent sidebar "
                    f"navigation compared to index.html. Missing links need to be "
                    f"added to: {', '.join(inconsistent)}"
                ),
                what_youll_learn=(
                    "How the Stronghold dashboard is structured. Each page "
                    "duplicates the sidebar — you'll see the full navigation "
                    "hierarchy and understand all the dashboard sections."
                ),
                acceptance_criteria=(
                    "All dashboard pages have identical sidebar links",
                    "Active page is highlighted correctly on each page",
                    "No other changes to page content",
                ),
            )
        ]
    return []


def detect_untested_modules(
    src_dir: Path,
    tests_dir: Path,
) -> list[IssueSuggestion]:
    """Find source modules with no corresponding test file."""
    suggestions: list[IssueSuggestion] = []

    for py_file in sorted(src_dir.rglob("*.py")):
        if py_file.name == "__init__.py":
            continue
        rel = py_file.relative_to(src_dir / "stronghold")
        parts = list(rel.parts)
        parts[-1] = f"test_{parts[-1]}"

        # Check common test locations
        found = False
        for test_path_parts in [parts, [parts[0], parts[-1]]]:
            candidate = tests_dir / Path(*test_path_parts)
            if candidate.exists():
                found = True
                break

        if not found:
            # Check if there's a test file that imports this module
            module_name = py_file.stem
            for test_file in tests_dir.rglob("*.py"):
                try:
                    if module_name in test_file.read_text(encoding="utf-8"):
                        found = True
                        break
                except (OSError, UnicodeDecodeError):
                    continue

        if not found:
            src_rel = py_file.relative_to(src_dir.parent.parent)
            # Only suggest for files with meaningful content
            line_count = len(py_file.read_text(encoding="utf-8").split("\n"))
            if line_count < 20:
                continue
            suggestions.append(
                IssueSuggestion(
                    title=f"test: add tests for {py_file.stem}",
                    category="untested_module",
                    files=(str(src_rel),),
                    description=(
                        f"`{src_rel}` has no corresponding test file. Add tests "
                        f"that exercise the public API using real classes and "
                        f"fakes from `tests/fakes.py`."
                    ),
                    what_youll_learn=(
                        f"How `{py_file.stem}` works and what it depends on. "
                        f"Writing tests forces you to understand the module's "
                        f"inputs, outputs, and error cases."
                    ),
                    acceptance_criteria=(
                        "Test file exists with at least 3 test cases",
                        "Tests use real classes, not unittest.mock",
                        "Tests cover happy path and at least one error case",
                        "All existing tests still pass",
                    ),
                    estimated_scope="medium",
                )
            )
    return suggestions


def detect_todo_fixme(
    src_dir: Path,
) -> list[IssueSuggestion]:
    """Find TODO/FIXME comments that could become good-first-issues."""
    pattern = re.compile(r"#\s*(TODO|FIXME|HACK|XXX):?\s*(.+)", re.IGNORECASE)
    suggestions: list[IssueSuggestion] = []

    for py_file in sorted(src_dir.rglob("*.py")):
        try:
            content = py_file.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # SEC-010: skip binary / unreadable files rather than crashing
            continue
        for i, line in enumerate(content.split("\n"), start=1):
            match = pattern.search(line)
            if match:
                tag = match.group(1).upper()
                desc = match.group(2).strip()
                if len(desc) < 10:
                    continue
                rel = py_file.relative_to(src_dir.parent.parent)
                suggestions.append(
                    IssueSuggestion(
                        title=f"fix: resolve {tag} in {py_file.name}:{i}",
                        category="todo_fixme",
                        files=(f"{rel}:{i}",),
                        description=(
                            f'`{rel}` line {i} has a `{tag}` comment: "{desc}". '
                            f"Resolve this by implementing the missing functionality "
                            f"or removing the comment if it's no longer relevant."
                        ),
                        what_youll_learn=(
                            f"How `{py_file.stem}` works and what technical debt "
                            f"exists. Understanding why a TODO was left helps you "
                            f"learn the design tradeoffs."
                        ),
                        acceptance_criteria=(
                            f"The {tag} comment is resolved or removed",
                            "If code was added, it has tests",
                            "All existing tests still pass",
                        ),
                    )
                )
    return suggestions


# ---------------------------------------------------------------------------
# Public API — run all detectors
# ---------------------------------------------------------------------------


def scan_for_good_first_issues(
    project_root: Path,
) -> list[IssueSuggestion]:
    """Run all detectors and return deduplicated suggestions.

    Detectors are ordered from most architectural (fakes, tests)
    to most mechanical (docstrings, TODOs).
    """
    src_dir = project_root / "src"
    tests_dir = project_root / "tests"
    dashboard_dir = src_dir / "stronghold" / "dashboard"

    all_suggestions: list[IssueSuggestion] = []

    if src_dir.is_dir() and tests_dir.is_dir():
        all_suggestions.extend(detect_missing_fakes(src_dir / "stronghold", tests_dir))
        all_suggestions.extend(detect_untested_modules(src_dir, tests_dir))

    if src_dir.is_dir():
        all_suggestions.extend(detect_todo_fixme(src_dir))
        all_suggestions.extend(detect_missing_docstrings(src_dir))

    if dashboard_dir.is_dir():
        all_suggestions.extend(detect_sidebar_inconsistencies(dashboard_dir))

    return all_suggestions


def format_as_github_issue(suggestion: IssueSuggestion) -> dict[str, object]:
    """Convert a suggestion to GitHub issue create payload."""
    criteria = "\n".join(f"- [ ] {c}" for c in suggestion.acceptance_criteria)
    files = "\n".join(f"- `{f}`" for f in suggestion.files)

    body = (
        f"## Summary\n\n{suggestion.description}\n\n"
        f"## Files\n\n{files}\n\n"
        f"## What you'll learn\n\n{suggestion.what_youll_learn}\n\n"
        f"## Acceptance criteria\n\n{criteria}\n\n"
        f"## Scope\n\n{suggestion.estimated_scope}"
    )

    return {
        "title": suggestion.title,
        "body": body,
        "labels": ["good first issue"],
    }
