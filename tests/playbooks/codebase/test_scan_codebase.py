"""scan_codebase_for_issues playbook: composes the scanner detectors."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from stronghold.playbooks.codebase.scan_codebase_for_issues import scan_codebase_for_issues
from stronghold.protocols.playbooks import PlaybookContext
from stronghold.tools.scanner import IssueSuggestion
from stronghold.types.auth import SYSTEM_AUTH

if TYPE_CHECKING:
    import pytest


def _ctx() -> PlaybookContext:
    return PlaybookContext(auth=SYSTEM_AUTH)


def _fake_suggestions() -> list[IssueSuggestion]:
    return [
        IssueSuggestion(
            title="Add FakeQuotaTracker to tests/fakes.py",
            category="missing-fakes",
            files=("src/stronghold/protocols/quota.py",),
            description="QuotaTracker protocol has no fake.",
            what_youll_learn="Protocol-first design.",
            acceptance_criteria=("FakeQuotaTracker class exists", "Covered in test_fakes.py"),
            estimated_scope="small",
        ),
        IssueSuggestion(
            title="Add docstrings to router/selector.py",
            category="missing-docstrings",
            files=("src/stronghold/router/selector.py",),
            description="3 public functions missing docstrings.",
            what_youll_learn="Documentation patterns.",
            acceptance_criteria=("All public functions documented",),
            estimated_scope="small",
        ),
        IssueSuggestion(
            title="Resolve TODO in agents/base.py:147",
            category="todo-fixme",
            files=("src/stronghold/agents/base.py",),
            description="TODO marker.",
            what_youll_learn="Agent pipeline.",
            acceptance_criteria=("TODO resolved or ticket opened",),
            estimated_scope="small",
        ),
    ]


async def test_scan_renders_suggestions_grouped_by_category(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    mod = sys.modules["stronghold.playbooks.codebase.scan_codebase_for_issues"]
    monkeypatch.setattr(mod, "scan_for_good_first_issues", lambda _root: _fake_suggestions())

    brief = await scan_codebase_for_issues({"project_root": str(tmp_path)}, _ctx())
    md = brief.to_markdown()
    assert "3 candidate issue(s)" in brief.title
    assert "## missing-fakes" in md
    assert "## missing-docstrings" in md
    assert "## todo-fixme" in md
    assert "FakeQuotaTracker" in md


async def test_scan_filters_by_category(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    mod = sys.modules["stronghold.playbooks.codebase.scan_codebase_for_issues"]
    monkeypatch.setattr(mod, "scan_for_good_first_issues", lambda _root: _fake_suggestions())

    brief = await scan_codebase_for_issues(
        {"project_root": str(tmp_path), "categories": ["missing-fakes"]},
        _ctx(),
    )
    md = brief.to_markdown()
    assert "## missing-fakes" in md
    assert "## missing-docstrings" not in md
    assert "## todo-fixme" not in md


async def test_scan_respects_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    mod = sys.modules["stronghold.playbooks.codebase.scan_codebase_for_issues"]
    monkeypatch.setattr(mod, "scan_for_good_first_issues", lambda _root: _fake_suggestions())

    brief = await scan_codebase_for_issues(
        {"project_root": str(tmp_path), "limit": 1},
        _ctx(),
    )
    assert "1 candidate issue(s)" in brief.title


async def test_scan_zero_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    mod = sys.modules["stronghold.playbooks.codebase.scan_codebase_for_issues"]
    monkeypatch.setattr(mod, "scan_for_good_first_issues", lambda _root: [])

    brief = await scan_codebase_for_issues({"project_root": str(tmp_path)}, _ctx())
    assert "No candidate issues" in brief.title


async def test_scan_rejects_bad_root() -> None:
    brief = await scan_codebase_for_issues(
        {"project_root": "/nonexistent/path/here/xyzzy"},
        _ctx(),
    )
    assert "bad-input" in brief.flags


async def test_scan_next_actions_cap_at_three(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    mod = sys.modules["stronghold.playbooks.codebase.scan_codebase_for_issues"]
    monkeypatch.setattr(mod, "scan_for_good_first_issues", lambda _root: _fake_suggestions())

    brief = await scan_codebase_for_issues({"project_root": str(tmp_path)}, _ctx())
    assert len(brief.next_actions) == 3
