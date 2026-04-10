"""Tests for RuntimePipeline.run_quality_gates."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from stronghold.builders.pipeline import RuntimePipeline

from tests.fakes import FakeLLMClient, FakePromptManager


class QualityToolDispatcher:
    """Tool dispatcher for quality gate tests — returns canned shell outputs."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.gate_results: dict[str, str] = {
            "ruff": "All checks passed!",
            "mypy": "Success: no issues found",
            "bandit": "No issues identified.",
            "pytest": "5 passed in 1.2s",
        }

    async def execute(self, tool: str, args: dict[str, Any]) -> str:
        self.calls.append((tool, args))
        cmd = args.get("command", "")
        if tool == "git":
            if "diff --name-only" in cmd:
                return "src/stronghold/foo.py\n"
            return "OK"
        if tool == "shell":
            if "ruff check --fix" in cmd or "ruff format" in cmd or "autotyping" in cmd:
                return "OK"
            if "pyrefly" in cmd:
                return ""
            if "ruff check" in cmd:
                return self.gate_results.get("ruff", "")
            if "mypy" in cmd:
                return self.gate_results.get("mypy", "")
            if "bandit" in cmd:
                return self.gate_results.get("bandit", "")
            if "pytest" in cmd:
                return self.gate_results.get("pytest", "")
        if tool == "file_ops":
            return "def foo(): pass\n"
        if tool == "github":
            return "OK"
        return "OK"


def _make_run() -> SimpleNamespace:
    run = SimpleNamespace()
    run.run_id = "run-qg-test"
    run.repo = "owner/repo"
    run.issue_number = 42
    run.events = []
    run._workspace_path = "/tmp/test-ws"
    return run


def _pipeline(td: QualityToolDispatcher) -> RuntimePipeline:
    pm = FakePromptManager()
    pm.seed("builders.quality.mypy_fix", "Fix mypy: {{error}} {{source}} {{suggestion}}")
    return RuntimePipeline(llm=FakeLLMClient(), tool_dispatcher=td, prompt_manager=pm)


class TestQualityGates:
    async def test_happy_path_all_green(self) -> None:
        td = QualityToolDispatcher()
        p = _pipeline(td)
        result = await p.run_quality_gates(_make_run())
        assert result.success is True

    async def test_no_source_changes_skips(self) -> None:
        td = QualityToolDispatcher()
        # Override diff to return no .py files
        orig_exec = td.execute

        async def no_diff(tool: str, args: dict[str, Any]) -> str:
            if tool == "git" and "diff --name-only" in args.get("command", ""):
                return "README.md\n"
            return await orig_exec(tool, args)

        td.execute = no_diff  # type: ignore[assignment]
        p = _pipeline(td)
        result = await p.run_quality_gates(_make_run())
        assert result.success is True
        assert "No source changes" in result.summary
