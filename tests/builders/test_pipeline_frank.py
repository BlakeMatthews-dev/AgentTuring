"""Characterization tests for Frank's stage handlers (analyze_issue, define_acceptance).

Uses FakeLLMClient + a minimal FakeToolDispatcher to exercise the happy path
and extraction-failure paths. No real LLM or GitHub calls.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from types import SimpleNamespace

from stronghold.builders.pipeline import RuntimePipeline

from tests.fakes import FakeLLMClient, FakePromptManager

if TYPE_CHECKING:
    pass


# ── Helpers ──────────────────────────────────────────────────────────


def _make_response(content: str) -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 20},
    }


class FakeToolDispatcher:
    """Minimal tool dispatcher that records calls and returns canned responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.file_contents: dict[str, str] = {}
        self.default_result = "OK"

    async def execute(self, tool: str, args: dict[str, Any]) -> str:
        self.calls.append((tool, args))
        action = args.get("action", "")
        path = args.get("path", "")

        if tool == "file_ops" and action == "read":
            return self.file_contents.get(path, "")
        if tool == "file_ops" and action == "write":
            self.file_contents[path] = args.get("content", "")
            return "OK"
        if tool == "shell":
            cmd = args.get("command", "")
            if "find" in cmd or "ls" in cmd:
                return "src/stronghold/foo.py\nsrc/stronghold/bar.py"
            return "OK"
        if tool == "github":
            if action == "post_pr_comment":
                return "OK"
            if action == "list_issue_comments":
                return "[]"
            return "OK"
        return self.default_result


def _make_run(
    run_id: str = "run-test",
    repo: str = "owner/repo",
    issue_number: int = 42,
) -> SimpleNamespace:
    """Minimal fake run object with the attributes stage handlers read."""
    run = SimpleNamespace()
    run.run_id = run_id
    run.repo = repo
    run.issue_number = issue_number
    run.branch = "mason/42"
    run.artifacts = []
    run.events = []
    run._workspace_path = "/tmp/test-ws"
    run._issue_content = "Fix the bug in foo module"
    run._issue_title = "Bug in foo"
    run._analysis = {}
    run._locked_criteria = set()
    run._criteria = []
    return run


def _pipeline(fake_llm: FakeLLMClient, fake_td: FakeToolDispatcher | None = None) -> RuntimePipeline:
    td = fake_td or FakeToolDispatcher()
    pm = FakePromptManager()
    # Seed the prompt templates that the handlers look up
    pm.seed("builders.frank.analyze_issue", "Analyze: {{issue_title}} {{issue_content}} {{file_listing}} {{test_listing}} {{dashboard_listing}} {{architecture_excerpt}} {{feedback_block}} {{issue_number}}")
    pm.seed("builders.frank.acceptance_criteria", "Criteria: {{issue_title}} {{requirements}} {{edge_cases}} {{feedback_block}} {{issue_number}}")
    return RuntimePipeline(llm=fake_llm, tool_dispatcher=td, prompt_manager=pm)


# ── analyze_issue ────────────────────────────────────────────────────


class TestAnalyzeIssue:
    async def test_happy_path_returns_success_with_analysis(self) -> None:
        analysis = {
            "problem": "foo is broken",
            "requirements": ["fix foo"],
            "edge_cases": ["empty input"],
            "affected_files": ["src/stronghold/foo.py"],
            "approach": "patch foo.py",
        }
        llm = FakeLLMClient()
        llm.set_responses(
            _make_response(f"```json\n{json.dumps(analysis)}\n```"),
        )
        p = _pipeline(llm)
        run = _make_run()
        result = await p.analyze_issue(run)

        assert result.success is True
        assert "analysis" in result.evidence
        assert result.evidence["analysis"]["problem"] == "foo is broken"
        assert "src/stronghold/foo.py" in result.evidence["analysis"]["affected_files"]

    async def test_extraction_failure_raises(self) -> None:
        """If LLM returns junk 3 times, ExtractionError propagates."""
        from stronghold.builders.extractors import ExtractionError

        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("not json"),
            _make_response("still not json"),
            _make_response("nope"),
        )
        p = _pipeline(llm)
        run = _make_run()
        import pytest
        with pytest.raises(ExtractionError):
            await p.analyze_issue(run)

    async def test_posts_summary_to_github_issue(self) -> None:
        analysis = {
            "problem": "bug",
            "requirements": ["fix"],
            "edge_cases": [],
            "affected_files": ["src/stronghold/foo.py"],
            "approach": "patch",
        }
        llm = FakeLLMClient()
        llm.set_responses(_make_response(f"```json\n{json.dumps(analysis)}\n```"))
        td = FakeToolDispatcher()
        p = _pipeline(llm, td)
        run = _make_run()
        await p.analyze_issue(run)

        github_calls = [(t, a) for t, a in td.calls if t == "github" and a.get("action") == "post_pr_comment"]
        assert len(github_calls) >= 1

    async def test_issue_body_files_override_llm_files(self) -> None:
        """When issue body has a ## Files section, those files take priority."""
        analysis = {
            "problem": "bug",
            "requirements": ["fix"],
            "edge_cases": [],
            "affected_files": ["src/stronghold/wrong.py"],
            "approach": "patch",
        }
        llm = FakeLLMClient()
        llm.set_responses(_make_response(f"```json\n{json.dumps(analysis)}\n```"))
        p = _pipeline(llm)
        run = _make_run()
        run._issue_content = (
            "Fix the bug\n\n"
            "## Files\n"
            "- `src/stronghold/correct.py`\n"
        )
        result = await p.analyze_issue(run)
        files = result.evidence["analysis"]["affected_files"]
        # Body file comes first, LLM file appended
        assert files[0] == "src/stronghold/correct.py"

    async def test_feedback_included_in_prompt(self) -> None:
        analysis = {"problem": "x", "requirements": [], "edge_cases": [], "affected_files": [], "approach": "y"}
        llm = FakeLLMClient()
        llm.set_responses(_make_response(f"```json\n{json.dumps(analysis)}\n```"))
        p = _pipeline(llm)
        run = _make_run()
        await p.analyze_issue(run, feedback="Try harder")

        sent_prompt = llm.calls[0]["messages"][0]["content"]
        assert "Try harder" in sent_prompt


# ── define_acceptance_criteria ───────────────────────────────────────


class TestDefineAcceptanceCriteria:
    async def test_happy_path_returns_scenarios(self) -> None:
        gherkin = (
            "Scenario: foo works\n"
            "  Given a foo\n"
            "  When called\n"
            "  Then returns true\n"
            "\n"
            "Scenario: bar works\n"
            "  Given a bar\n"
            "  When invoked\n"
            "  Then returns false"
        )
        llm = FakeLLMClient()
        llm.set_responses(_make_response(gherkin))
        p = _pipeline(llm)
        run = _make_run()
        result = await p.define_acceptance_criteria(run)

        assert result.success is True
        assert result.evidence["scenario_count"] == 2
        assert len(result.evidence["scenarios"]) == 2

    async def test_stashes_criteria_on_run(self) -> None:
        gherkin = "Scenario: x\n  Given a\n  When b\n  Then c"
        llm = FakeLLMClient()
        llm.set_responses(_make_response(gherkin))
        p = _pipeline(llm)
        run = _make_run()
        await p.define_acceptance_criteria(run)
        assert hasattr(run, "_criteria")
        assert len(run._criteria) >= 1

    async def test_extraction_failure_raises(self) -> None:
        from stronghold.builders.extractors import ExtractionError

        llm = FakeLLMClient()
        llm.set_responses(
            _make_response("not gherkin"),
            _make_response("still not gherkin"),
            _make_response("nope"),
        )
        p = _pipeline(llm)
        run = _make_run()
        import pytest
        with pytest.raises(ExtractionError):
            await p.define_acceptance_criteria(run)

    async def test_locked_criteria_info_in_prompt(self) -> None:
        """When prior criteria are locked, the prompt tells Frank to preserve them."""
        gherkin = "Scenario: x\n  Given a\n  When b\n  Then c"
        llm = FakeLLMClient()
        llm.set_responses(_make_response(gherkin))
        p = _pipeline(llm)
        run = _make_run()
        run._locked_criteria = {0}
        run._criteria = ["First criterion text"]
        await p.define_acceptance_criteria(run)

        sent_prompt = llm.calls[0]["messages"][0]["content"]
        assert "LOCKED" in sent_prompt

    async def test_ui_dashboard_adds_testing_constraint(self) -> None:
        """UI issues get a special constraint about no-browser testing."""
        gherkin = "Scenario: x\n  Given a\n  When b\n  Then c"
        llm = FakeLLMClient()
        llm.set_responses(_make_response(gherkin))
        p = _pipeline(llm)
        run = _make_run()
        run._issue_title = "Fix sidebar overlap on dashboard"
        run._issue_content = "The sidebar button overlaps"
        await p.define_acceptance_criteria(run)

        sent_prompt = llm.calls[0]["messages"][0]["content"]
        assert "NO browser" in sent_prompt or "no browser" in sent_prompt.lower()
