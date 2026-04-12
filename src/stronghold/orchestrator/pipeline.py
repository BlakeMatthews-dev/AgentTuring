"""Builder pipeline — chained agent execution for issue-to-merge flow.

The pipeline defines ordered stages that an issue flows through.
Each stage is an agent with a specific role. The output of one stage
becomes context for the next. If a stage fails, the pipeline halts
and reports which stage broke.

Default pipeline (configurable):
  1. quartermaster  — decompose epic into atomic issues (skip if already atomic)
  2. archie          — scaffold protocols, fakes, file structure
  3. mason          — TDD: write tests, then implementation
  4. auditor        — review PR, post violation comments
  5. gatekeeper     — final lint/format/merge-readiness check
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger("stronghold.orchestrator.pipeline")


class StageStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class PipelineStage:
    """A single stage in the builder pipeline."""

    name: str
    agent_name: str
    prompt_template: str
    status: StageStatus = StageStatus.PENDING
    result: dict[str, Any] | None = None
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    skip_if: str = ""  # condition to skip (e.g., "atomic" skips quartermaster)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "agent_name": self.agent_name,
            "status": self.status.value,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass
class PipelineRun:
    """A complete pipeline execution for one issue."""

    id: str
    issue_number: int
    title: str
    repo: str
    stages: list[PipelineStage] = field(default_factory=list)
    current_stage: int = 0
    status: str = "pending"
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "issue_number": self.issue_number,
            "title": self.title,
            "repo": self.repo,
            "status": self.status,
            "current_stage": self.current_stage,
            "stages": [s.to_dict() for s in self.stages],
            "created_at": self.created_at.isoformat(),
        }


# ── Default pipeline stages ─────────────────────────────────────────

BUILDER_PIPELINE = [
    PipelineStage(
        name="decompose",
        agent_name="quartermaster",
        skip_if="atomic",
        prompt_template=(
            "Decompose this epic into atomic, implementable sub-issues. "
            "Each sub-issue must have:\n"
            "- A clear title\n"
            "- Acceptance criteria (testable)\n"
            "- File paths that will be touched\n"
            "- Estimated complexity (S/M/L)\n\n"
            "Epic: {title}\n"
            "Issue: https://github.com/{repo}/issues/{issue_number}\n\n"
            "Output a numbered list of sub-issues with details."
        ),
    ),
    PipelineStage(
        name="scaffold",
        agent_name="archie",
        prompt_template=(
            "Read issue #{issue_number}: {title}\n\n"
            "Create the scaffolding for this implementation:\n"
            "1. Define any new protocols in src/stronghold/protocols/\n"
            "2. Add fake implementations to tests/fakes.py\n"
            "3. Create empty module files with docstrings\n"
            "4. Update ARCHITECTURE.md if adding new components\n\n"
            "Previous stage output:\n{prev_output}\n\n"
            "DO NOT write implementation code. Only structure."
        ),
    ),
    PipelineStage(
        name="implement",
        agent_name="mason",
        prompt_template=(
            "Implement issue #{issue_number}: {title}\n\n"
            "Repository: https://github.com/{repo}\n\n"
            "Follow your TDD pipeline:\n"
            "1. Write failing tests based on acceptance criteria\n"
            "2. Implement minimum code to pass tests\n"
            "3. Run quality gates: pytest, ruff, mypy, bandit\n"
            "4. Create a PR when all gates pass\n\n"
            "Scaffold from previous stage:\n{prev_output}\n\n"
            "Create a focused PR with your changes."
        ),
    ),
    PipelineStage(
        name="review",
        agent_name="auditor",
        prompt_template=(
            "Review the PR created for issue #{issue_number}: {title}\n\n"
            "Check for:\n"
            "- Test coverage and quality\n"
            "- Security issues (injection, XSS, SSRF)\n"
            "- Multi-tenant isolation (org_id on all queries)\n"
            "- Protocol compliance (DI, no direct imports)\n"
            "- Code quality (naming, complexity, duplication)\n\n"
            "Previous stage output:\n{prev_output}\n\n"
            "Post your review as PR comments with ViolationCategory tags."
        ),
    ),
    PipelineStage(
        name="cleanup",
        agent_name="gatekeeper",
        skip_if="review_clean",
        prompt_template=(
            "Final cleanup for issue #{issue_number}: {title}\n\n"
            "The auditor found these issues:\n{prev_output}\n\n"
            "Fix all violations:\n"
            "1. Run ruff check --fix && ruff format\n"
            "2. Fix any mypy --strict errors\n"
            "3. Ensure all tests pass\n"
            "4. Push fixes to the existing PR branch\n\n"
            "Do NOT create a new PR. Push to the existing branch."
        ),
    ),
]


class BuilderPipeline:
    """Executes the full issue-to-merge pipeline.

    Usage:
        pipeline = BuilderPipeline(orchestrator_engine)
        run = await pipeline.execute(
            issue_number=42, title="Add caching", repo="Agent-StrongHold/stronghold",
        )
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._runs: dict[str, PipelineRun] = {}

    async def execute(
        self,
        *,
        issue_number: int,
        title: str,
        repo: str = "Agent-StrongHold/stronghold",
        skip_decompose: bool = True,
    ) -> PipelineRun:
        """Run the full pipeline for an issue."""
        import copy

        run_id = f"pipeline-{issue_number}"
        stages = [copy.deepcopy(s) for s in BUILDER_PIPELINE]
        run = PipelineRun(
            id=run_id,
            issue_number=issue_number,
            title=title,
            repo=repo,
            stages=stages,
        )
        self._runs[run_id] = run
        run.status = "running"

        prev_output = ""
        for i, stage in enumerate(stages):
            run.current_stage = i

            # Skip conditions
            if stage.skip_if == "atomic" and skip_decompose:
                stage.status = StageStatus.SKIPPED
                logger.info("Pipeline %s: skipping %s (atomic issue)", run_id, stage.name)
                continue

            _clean_signals = ("no violations", "lgtm", "approved", "all checks pass", "clean")
            if stage.skip_if == "review_clean" and any(
                s in prev_output.lower() for s in _clean_signals
            ):
                stage.status = StageStatus.SKIPPED
                logger.info("Pipeline %s: skipping %s (review clean)", run_id, stage.name)
                continue

            # Check agent exists (use engine's public accessor, not internal state)
            if not self._engine.has_agent(stage.agent_name):
                stage.status = StageStatus.SKIPPED
                logger.warning(
                    "Pipeline %s: skipping %s (agent '%s' not loaded)",
                    run_id,
                    stage.name,
                    stage.agent_name,
                )
                prev_output = f"[skipped: agent {stage.agent_name} not available]"
                continue

            # Build prompt from template
            prompt = stage.prompt_template.format(
                issue_number=issue_number,
                title=title,
                repo=repo,
                prev_output=prev_output[:2000],
            )

            # Dispatch through orchestrator engine
            stage.status = StageStatus.RUNNING
            stage.started_at = datetime.now(UTC)
            logger.info("Pipeline %s: starting %s (agent=%s)", run_id, stage.name, stage.agent_name)

            work_id = f"{run_id}-{stage.name}"
            self._engine.dispatch(
                work_id=work_id,
                agent_name=stage.agent_name,
                messages=[{"role": "user", "content": prompt}],
                trigger="pipeline",
                priority_tier="P5",
                intent_hint="code_gen",
                metadata={
                    "issue_number": issue_number,
                    "pipeline_run": run_id,
                    "stage": stage.name,
                },
            )

            # Wait for completion with exponential backoff (not 1s polling)
            import asyncio

            _poll_interval = 1.0
            _elapsed = 0.0
            _stage_timeout = 600.0  # 10 minutes max per stage
            while _elapsed < _stage_timeout:
                current = self._engine.get(work_id)
                if current and current.status.value in ("completed", "failed", "cancelled"):
                    break
                await asyncio.sleep(_poll_interval)
                _elapsed += _poll_interval
                _poll_interval = min(_poll_interval * 1.5, 10.0)  # back off to 10s max

            current = self._engine.get(work_id)
            if current is None:
                stage.status = StageStatus.FAILED
                stage.error = "Work item lost"
                stage.completed_at = datetime.now(UTC)
                run.status = f"failed at {stage.name}"
                logger.error("Pipeline %s: %s FAILED: work item lost", run_id, stage.name)
                break
            if current.status.value == "failed":
                stage.status = StageStatus.FAILED
                stage.error = current.error
                stage.completed_at = datetime.now(UTC)
                run.status = f"failed at {stage.name}"
                logger.error("Pipeline %s: %s FAILED: %s", run_id, stage.name, stage.error)
                break
            if _elapsed >= _stage_timeout:
                # Timed out — cancel the work item and fail the stage
                self._engine.cancel(work_id)
                stage.status = StageStatus.FAILED
                stage.error = f"Stage timed out after {_stage_timeout:.0f}s"
                stage.completed_at = datetime.now(UTC)
                run.status = f"failed at {stage.name}"
                logger.error("Pipeline %s: %s TIMED OUT", run_id, stage.name)
                break

            stage.status = StageStatus.COMPLETED
            stage.result = current.result
            stage.completed_at = datetime.now(UTC)

            # Extract text output for next stage
            if current.result:
                choices = current.result.get("choices", [])
                if choices:
                    prev_output = choices[0].get("message", {}).get("content", "")
                else:
                    prev_output = str(current.result.get("content", ""))
            else:
                prev_output = ""

            logger.info("Pipeline %s: %s completed", run_id, stage.name)

        if run.status == "running":
            run.status = "completed"
        return run

    def get_run(self, run_id: str) -> PipelineRun | None:
        return self._runs.get(run_id)

    def list_runs(self) -> list[dict[str, object]]:
        return [r.to_dict() for r in self._runs.values()]
