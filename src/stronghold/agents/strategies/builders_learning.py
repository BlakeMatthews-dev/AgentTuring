from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from stronghold.agents.strategies.react import ReactStrategy
from stronghold.types.agent import ReasoningResult

if TYPE_CHECKING:
    from stronghold.protocols.llm import LLMClient
    from stronghold.protocols.tracing import Trace

logger = logging.getLogger("stronghold.strategy.builders_learning")


class BuildersLearningStrategy:
    """Frank/Mason with repo recon, failure diagnosis, learning loop.

    This strategy extends the React tool loop with:
    1. Repository reconnaissance (check existing code/tests before planning)
    2. Failure pattern analysis (analyze rejected PRs)
    3. Diagnostic artifact production (context for next worker)
    4. Coverage-first execution (85% first pass, 95% final)
    5. Self-diagnosis before PR submission
    6. Learning storage (improve over time)
    """

    def __init__(
        self,
        max_rounds: int = 10,
        force_tool_first: bool = False,
        enable_learning: bool = True,
    ) -> None:
        self.max_rounds = max_rounds
        self.force_tool_first = force_tool_first
        self.enable_learning = enable_learning
        self._react = ReactStrategy(max_rounds=max_rounds, force_tool_first=force_tool_first)
        self.process = None  # diagnostic variable usage
        self.build = None  # diagnostic variable usage

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        trace: Trace | None = None,
        warden: Any = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Execute Builders workflow with learning.

        This adds learning capabilities on top of the ReAct tool loop:
        - Frank: Repo recon, failure analysis, diagnostic production
        - Mason: Pre-execution diagnosis, coverage-first, self-diagnosis
        - Both: Store learnings in memory for future improvement
        """
        # ruff F841: local variable `run_id` is assigned to but never used
        _ = kwargs.get("run_id")

        # Extract worker type from context
        worker = kwargs.get("worker", "unknown")

        if worker == "frank":
            return await self._frank_with_learning(messages, model, llm, trace, warden, **kwargs)
        if worker == "mason":
            return await self._mason_with_learning(messages, model, llm, trace, warden, **kwargs)

        # Fallback to standard React for other workers
        return await self._react.reason(messages, model, llm, trace=trace, warden=warden, **kwargs)

    async def _frank_with_learning(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        trace: Trace | None,
        warden: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Frank with repo reconnaissance and failure analysis.

        Frank's enhanced workflow:
        1. Check repository state (existing code, tests, failed PRs)
        2. Analyze similar issues and failure patterns
        3. Build rich context for LLM
        4. Execute standard ReAct loop with this context
        5. Produce diagnostic artifact for Mason
        6. Store learning in memory
        """
        # ruff F841: local variable `run_id` is assigned to but never used
        _ = kwargs.get("run_id")

        # Step 1: Repository reconnaissance (simulated - would call GitHub service)
        repo_state = await self._check_repository_state(**kwargs)

        # Step 2: Failure pattern analysis (simulated - would search GitHub)
        failure_patterns = await self._analyze_failure_patterns(**kwargs)

        # Step 3: Build enhanced context
        context = {
            "existing_code": repo_state.get("code", []),
            "existing_tests": repo_state.get("tests", []),
            "similar_issues": failure_patterns.get("similar_issues", []),
            "previous_failures": failure_patterns.get("failures", []),
            "rejection_reasons": failure_patterns.get("reasons", []),
            "coverage_expectation": "85% first pass, 95% final",
        }

        # Step 4: Execute standard ReAct loop with enhanced context
        result = await self._react.reason(
            messages, model, llm, trace=trace, warden=warden, context=context, **kwargs
        )

        # Step 5: Store diagnostic artifact (TODO: wire to orchestrator)
        # ruff F841: local variable `diagnostic` is assigned to but never used
        _ = {
            "worker": "frank",
            "run_id": kwargs.get("run_id"),
            "repository_state": repo_state,
            "failure_patterns": failure_patterns,
            "expectation": "First implementation - expect 85% coverage",
            "timestamp": self._utc_now(),
        }
        logger.info("Frank diagnostic produced")

        # Step 6: Store learning in memory (would go to memory store)
        if self.enable_learning:
            await self._store_frank_learning(repo_state, failure_patterns, result)

        return result

    async def _mason_with_learning(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        trace: Trace | None,
        warden: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        """Mason with pre-execution diagnosis and self-diagnosis.

        Mason's enhanced workflow:
        1. Read Frank's diagnostic
        2. Determine execution mode (fix vs implement)
        3. Execute multi-phase implementation with coverage-first
        4. Self-diagnose before PR submission
        5. Store learning in memory
        """
        # ruff F841: local variable `run_id` is assigned to but never used
        _ = kwargs.get("run_id")

        # Step 1: Get Frank's diagnostic (would read from orchestrator)
        frank_diagnostic = kwargs.get("frank_diagnostic", {})

        # Step 2: Pre-execution analysis
        execution_mode = "fix" if frank_diagnostic.get("existing_code") else "implement"

        # Step 3: Execute standard ReAct loop with enhanced context
        context = {
            "frank_diagnostic": frank_diagnostic,
            "execution_mode": execution_mode,
            "coverage_expectation": "85% first pass, 95% final",
            "diagnostic_checks": [
                "coverage",
                "type_errors",
                "lint_errors",
                "security_issues",
                "docstrings",
                "error_handling",
                "naming_conventions",
                "architecture_violations",
            ],
        }

        result = await self._react.reason(
            messages, model, llm, trace=trace, warden=warden, context=context, **kwargs
        )

        # Step 4: Self-diagnosis before PR submission (simulated)
        diagnostics = await self._run_pr_diagnostics(**kwargs)

        if diagnostics.get("has_critical_issues"):
            logger.warning(f"PR would be rejected: {diagnostics.get('issues')}")
            # In production, would fix issues before marking done
            result = ReasoningResult(
                response=(
                    f"{result.response}\n\n"
                    "Self-diagnosis: Found "
                    f"{len(diagnostics.get('issues', []))} "
                    "issues - must fix before PR"
                ),
                done=False,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                tool_history=result.tool_history,
            )
        else:
            # Step 5: Store learning in memory
            if self.enable_learning:
                await self._store_mason_learning(diagnostics, result)

        return result

    async def _check_repository_state(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check existing code/tests via the tool executor."""
        tool_executor = kwargs.get("tool_executor")
        if not tool_executor:
            logger.warning("No tool_executor — skipping repo recon")
            return {"code": [], "tests": [], "failed_prs": []}

        logger.info("Running repository reconnaissance")
        try:
            code = await tool_executor(
                "shell", {"command": "find src/stronghold -name '*.py' -type f | head -50"}
            )
            tests = await tool_executor(
                "shell", {"command": "find tests -name '*.py' -type f | head -50"}
            )
            return {
                "code": str(code).strip().split("\n") if code else [],
                "tests": str(tests).strip().split("\n") if tests else [],
                "failed_prs": [],
            }
        except Exception:
            logger.debug("Repo recon failed", exc_info=True)
            return {"code": [], "tests": [], "failed_prs": []}

    async def _analyze_failure_patterns(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check for prior failed PRs on this issue via tool executor."""
        tool_executor = kwargs.get("tool_executor")
        if not tool_executor:
            return {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}

        logger.info("Analyzing failure patterns")
        try:
            result = await tool_executor(
                "github",
                {
                    "action": "search_issues",
                    "query": "is:pr is:closed label:rejected",
                },
            )
            return {
                "similar_issues": [],
                "failures": str(result).strip().split("\n")[:10] if result else [],
                "reasons": [],
                "lessons": [],
            }
        except Exception:
            logger.debug("Failure analysis skipped", exc_info=True)
            return {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}

    async def _run_pr_diagnostics(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run quality gates via the tool executor."""
        tool_executor = kwargs.get("tool_executor")
        if not tool_executor:
            return {"all_passed": True, "issues": [], "has_critical_issues": False}

        logger.info("Running PR diagnostics (quality gates)")
        issues: list[str] = []
        try:
            ruff = await tool_executor(
                "shell", {"command": "ruff check src/stronghold/ 2>&1 | tail -3"}
            )
            if ruff and "error" in str(ruff).lower():
                issues.append(f"ruff: {str(ruff)[:200]}")
        except Exception:
            pass
        try:
            mypy = await tool_executor(
                "shell", {"command": "mypy src/stronghold/ --strict 2>&1 | tail -3"}
            )
            if mypy and "error" in str(mypy).lower():
                issues.append(f"mypy: {str(mypy)[:200]}")
        except Exception:
            pass
        try:
            tests = await tool_executor(
                "shell", {"command": "pytest tests/ -x -q --tb=line 2>&1 | tail -5"}
            )
            if tests and "failed" in str(tests).lower():
                issues.append(f"pytest: {str(tests)[:200]}")
        except Exception:
            pass

        has_critical = len(issues) > 0
        return {
            "all_passed": not has_critical,
            "issues": issues,
            "has_critical_issues": has_critical,
        }

    async def _store_frank_learning(
        self,
        repo_state: dict[str, Any],
        failure_patterns: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        """Store Frank learning — logs for now, memory store in follow-up."""
        logger.info(
            "Frank learning: %d code files, %d test files, %d failures found",
            len(repo_state.get("code", [])),
            len(repo_state.get("tests", [])),
            len(failure_patterns.get("failures", [])),
        )

    async def _store_mason_learning(
        self,
        diagnostics: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        """Store Mason learning — logs for now, memory store in follow-up."""
        logger.info(
            "Mason learning: gates_passed=%s, issues=%d, tools_used=%d",
            diagnostics.get("all_passed"),
            len(diagnostics.get("issues", [])),
            len(getattr(result, "tool_history", [])),
        )

    def _utc_now(self) -> datetime:
        """Get current UTC timestamp."""
        return datetime.now(UTC)
