"""Builders strategy with learning loop and repository reconnaissance."""

from __future__ import annotations

import logging
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
        # Extract worker type from context
        worker = kwargs.get("worker", "unknown")

        if worker == "frank":
            return await self._frank_with_learning(messages, model, llm, trace, warden, **kwargs)
        elif worker == "mason":
            return await self._mason_with_learning(messages, model, llm, trace, warden, **kwargs)
        else:
            # Fallback to standard React for other workers
            return await self._react.reason(
                messages, model, llm, trace=trace, warden=warden, **kwargs
            )

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
        # Extract run_id from kwargs (don't re-pass)
        run_id = kwargs.get("run_id", "unknown")

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
        _diagnostic = {  # noqa: F841
            "worker": "frank",
            "run_id": run_id,
            "repository_state": repo_state,
            "failure_patterns": failure_patterns,
            "expectation": "First implementation - expect 85% coverage",
            "timestamp": self._utc_now(),
        }

        # Step 6: Store learning in memory (would go to memory store)
        if self.enable_learning:
            await self._store_frank_learning(run_id, repo_state, failure_patterns, result)

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
        # Extract run_id from kwargs (don't re-pass)
        run_id = kwargs.get("run_id", "unknown")

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
                    f"Self-diagnosis: Found "
                    f"{len(diagnostics.get('issues', []))} "
                    f"issues - must fix before PR"
                ),
                done=False,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                tool_history=result.tool_history,
            )
        else:
            # Step 5: Store learning in memory
            if self.enable_learning:
                await self._store_mason_learning(run_id, diagnostics, result)

        return result

    async def _check_repository_state(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Check existing code/tests in repository.

        In production, this would call GitHubService to:
        - List files in the repo
        - List test files
        - Check for failed PRs related to this issue
        """
        # Simulated - in production would call GitHub service
        logger.info(f"Checking repository state for run {run_id}")
        return {
            "code": [],  # Would be list of files
            "tests": [],  # Would be list of test files
            "failed_prs": [],  # Would be list of rejected PRs
        }

    async def _analyze_failure_patterns(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Analyze previous failures on similar issues.

        In production, this would:
        - Search GitHub for similar issues
        - List PRs for those issues
        - Analyze rejection comments for patterns
        - Extract lessons learned
        """
        # Simulated - in production would search GitHub
        logger.info(f"Analyzing failure patterns for run {run_id}")
        return {
            "similar_issues": [],  # Would be list of similar issues
            "failures": [],  # Would be list of failure patterns
            "reasons": [],  # Would be list of rejection reasons
            "lessons": [],  # Would be list of lessons learned
        }

    async def _run_pr_diagnostics(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Run diagnostic checks before PR submission.

        Checks:
        1. Coverage >= 85% (first pass) or >= 95% (final)
        2. Type errors (mypy --strict)
        3. Lint errors (ruff)
        4. Security issues (bandit)
        5. Docstrings on all functions
        6. Error handling present
        7. Naming conventions followed
        8. Architecture violations none
        """
        # Simulated - in production would run actual diagnostic tools
        logger.info(f"Running PR diagnostics for run {run_id}")
        return {
            "all_passed": True,  # Would be based on actual checks
            "issues": [],  # Would be list of failed checks
            "has_critical_issues": False,
        }

    async def _store_frank_learning(
        self,
        run_id: str,
        repo_state: dict[str, Any],
        failure_patterns: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        """Store Frank learning in memory.

        In production, this would store to MemoryStore:
        - Repository state
        - Failure patterns discovered
        - What worked/didn't work
        - Timestamp for trending
        """
        logger.info(f"Storing Frank learning for run {run_id}")
        # In production: await self.memory.store("frank_reconnaissance", {...})

    async def _store_mason_learning(
        self,
        run_id: str,
        diagnostics: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        """Store Mason learning in memory.

        In production, this would store to MemoryStore:
        - Diagnostic results
        - Coverage achieved
        - Issues found/fixed
        - Timestamp for trending
        """
        logger.info(f"Storing Mason learning for run {run_id}")
        # In production: await self.memory.store("mason_failures", {...})

    def _utc_now(self):
        """Get current UTC timestamp."""
        from datetime import UTC, datetime

        return datetime.now(UTC)
