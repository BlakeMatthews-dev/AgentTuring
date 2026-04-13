"""Tests for the BuilderPipeline orchestration flow."""

from __future__ import annotations

from typing import Any

from stronghold.orchestrator.engine import OrchestratorEngine
from stronghold.orchestrator.pipeline import (
    BuilderPipeline,
    PipelineRun,
    PipelineStage,
    StageStatus,
)

# -- Fakes for pipeline tests --------------------------------------------


class FakeAgentResponse:
    def __init__(self, content: str = "done") -> None:
        self.content = content
        self.tool_history: list[dict[str, Any]] = []


class FakeAgent:
    """Fake agent that records handle() calls and returns canned content."""

    def __init__(self, response: str = "done", fail: bool = False) -> None:
        self._response = response
        self._fail = fail
        self.calls: list[dict[str, Any]] = []

    async def handle(
        self,
        messages: list[dict[str, Any]],
        auth: Any,
        **kwargs: Any,
    ) -> FakeAgentResponse:
        self.calls.append({"messages": messages})
        if self._fail:
            raise RuntimeError("agent execution failed")
        return FakeAgentResponse(self._response)


class FakeReactor:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def emit(self, event: Any) -> None:
        self.events.append(event)


class FakeContainer:
    """Container stub with configurable agents for pipeline tests."""

    def __init__(
        self,
        agent_names: list[str] | None = None,
        response: str = "done",
        fail: bool = False,
    ) -> None:
        names = agent_names or [
            "quartermaster",
            "frank",
            "mason",
            "auditor",
            "gatekeeper",
        ]
        self.agents: dict[str, FakeAgent] = {name: FakeAgent(response, fail) for name in names}
        self.reactor = FakeReactor()


def _make_engine(
    container: FakeContainer | None = None,
    max_concurrent: int = 3,
) -> OrchestratorEngine:
    c = container or FakeContainer()
    return OrchestratorEngine(c, max_concurrent=max_concurrent)


# -- PipelineStage dataclass tests ----------------------------------------


class TestPipelineStage:
    def test_defaults(self) -> None:
        stage = PipelineStage(
            name="decompose",
            agent_name="quartermaster",
            prompt_template="do it",
        )
        assert stage.status == StageStatus.PENDING
        assert stage.result is None
        assert stage.error == ""
        assert stage.started_at is None
        assert stage.completed_at is None
        assert stage.skip_if == ""

    def test_to_dict_pending(self) -> None:
        stage = PipelineStage(
            name="scaffold",
            agent_name="frank",
            prompt_template="scaffold it",
        )
        d = stage.to_dict()
        assert d["name"] == "scaffold"
        assert d["agent_name"] == "frank"
        assert d["status"] == "pending"
        assert d["error"] == ""
        assert d["started_at"] is None
        assert d["completed_at"] is None

    def test_to_dict_completed_has_timestamps(self) -> None:
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        stage = PipelineStage(
            name="implement",
            agent_name="mason",
            prompt_template="build it",
            status=StageStatus.COMPLETED,
            started_at=now,
            completed_at=now,
        )
        d = stage.to_dict()
        assert d["status"] == "completed"
        assert d["started_at"] == now.isoformat()
        assert d["completed_at"] == now.isoformat()

    def test_to_dict_failed_includes_error(self) -> None:
        stage = PipelineStage(
            name="review",
            agent_name="auditor",
            prompt_template="review it",
            status=StageStatus.FAILED,
            error="timeout",
        )
        d = stage.to_dict()
        assert d["status"] == "failed"
        assert d["error"] == "timeout"


# -- PipelineRun dataclass tests ------------------------------------------


class TestPipelineRun:
    def test_defaults(self) -> None:
        run = PipelineRun(
            id="pipeline-1",
            issue_number=1,
            title="test",
            repo="org/repo",
        )
        assert run.stages == []
        assert run.current_stage == 0
        assert run.status == "pending"
        assert run.context == {}
        assert run.created_at is not None

    def test_to_dict_empty_stages(self) -> None:
        run = PipelineRun(
            id="pipeline-2",
            issue_number=2,
            title="add caching",
            repo="org/repo",
        )
        d = run.to_dict()
        assert d["id"] == "pipeline-2"
        assert d["issue_number"] == 2
        assert d["title"] == "add caching"
        assert d["repo"] == "org/repo"
        assert d["status"] == "pending"
        assert d["current_stage"] == 0
        assert d["stages"] == []
        assert "created_at" in d

    def test_to_dict_with_stages(self) -> None:
        stage = PipelineStage(
            name="implement",
            agent_name="mason",
            prompt_template="build",
            status=StageStatus.COMPLETED,
        )
        run = PipelineRun(
            id="pipeline-3",
            issue_number=3,
            title="fix bug",
            repo="org/repo",
            stages=[stage],
        )
        d = run.to_dict()
        assert len(d["stages"]) == 1
        assert d["stages"][0]["name"] == "implement"
        assert d["stages"][0]["status"] == "completed"


# -- BuilderPipeline.__init__ ---------------------------------------------


class TestBuilderPipelineInit:
    def test_init_stores_engine(self) -> None:
        engine = _make_engine()
        pipeline = BuilderPipeline(engine)
        assert pipeline._engine is engine

    def test_init_runs_dict_empty(self) -> None:
        engine = _make_engine()
        pipeline = BuilderPipeline(engine)
        assert pipeline._runs == {}
        assert pipeline.list_runs() == []


# -- BuilderPipeline.execute() --------------------------------------------


class TestBuilderPipelineExecute:
    async def test_execute_full_pipeline_completes(self) -> None:
        """All 5 agents loaded, skip_decompose=True skips decompose."""
        container = FakeContainer(response="stage output")
        engine = _make_engine(container, max_concurrent=3)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=42,
                title="Add caching",
                repo="org/repo",
                skip_decompose=True,
            )
            assert run.status == "completed"
            assert run.id == "pipeline-42"
            # decompose should be SKIPPED (atomic + skip_decompose=True)
            assert run.stages[0].status == StageStatus.SKIPPED
            assert run.stages[0].name == "decompose"
            # scaffold, implement, review should be COMPLETED
            for stage in run.stages[1:4]:
                assert stage.status == StageStatus.COMPLETED, f"{stage.name} should be completed"
        finally:
            await engine.stop()

    async def test_skip_decompose_when_atomic(self) -> None:
        """skip_if='atomic' AND skip_decompose=True -> SKIPPED."""
        container = FakeContainer(response="ok")
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=10,
                title="Small fix",
                skip_decompose=True,
            )
            decompose = run.stages[0]
            assert decompose.name == "decompose"
            assert decompose.status == StageStatus.SKIPPED
        finally:
            await engine.stop()

    async def test_decompose_runs_when_not_skipped(self) -> None:
        """skip_decompose=False means decompose stage actually executes."""
        container = FakeContainer(response="sub-issues listed")
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=11,
                title="Big epic",
                skip_decompose=False,
            )
            decompose = run.stages[0]
            assert decompose.name == "decompose"
            assert decompose.status == StageStatus.COMPLETED
        finally:
            await engine.stop()

    async def test_cleanup_skipped_when_review_clean(self) -> None:
        """skip_if='review_clean' AND 'no violations' in prev -> SKIPPED."""
        container = FakeContainer()
        # The auditor (review stage) must return "no violations" in output
        container.agents["auditor"] = FakeAgent(response="Review complete: No violations found.")
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=20,
                title="Clean code",
                skip_decompose=True,
            )
            cleanup = run.stages[4]
            assert cleanup.name == "cleanup"
            assert cleanup.status == StageStatus.SKIPPED
        finally:
            await engine.stop()

    async def test_cleanup_runs_when_violations_found(self) -> None:
        """Cleanup runs when the review output has violations."""
        container = FakeContainer()
        container.agents["auditor"] = FakeAgent(
            response="Found 3 violations: missing org_id filter"
        )
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=21,
                title="Buggy code",
                skip_decompose=True,
            )
            cleanup = run.stages[4]
            assert cleanup.name == "cleanup"
            assert cleanup.status == StageStatus.COMPLETED
        finally:
            await engine.stop()

    async def test_agent_not_loaded_skips_stage(self) -> None:
        """If agent_name not in container.agents, stage is SKIPPED."""
        # Only load quartermaster and mason
        container = FakeContainer(agent_names=["quartermaster", "mason"])
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=30,
                title="Partial agents",
                skip_decompose=True,
            )
            # scaffold (frank) should be skipped -- agent not loaded
            scaffold = run.stages[1]
            assert scaffold.name == "scaffold"
            assert scaffold.status == StageStatus.SKIPPED
            # implement (mason) should run
            implement = run.stages[2]
            assert implement.name == "implement"
            assert implement.status == StageStatus.COMPLETED
            # review (auditor) and cleanup (gatekeeper) should be skipped
            assert run.stages[3].status == StageStatus.SKIPPED
        finally:
            await engine.stop()

    async def test_stage_status_transitions(self) -> None:
        """Completed stages have start and end timestamps."""
        container = FakeContainer(response="output")
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=40,
                title="Track status",
                skip_decompose=True,
            )
            scaffold = run.stages[1]
            assert scaffold.status == StageStatus.COMPLETED
            assert scaffold.started_at is not None
            assert scaffold.completed_at is not None
            assert scaffold.completed_at >= scaffold.started_at
        finally:
            await engine.stop()

    async def test_failed_stage_halts_pipeline(self) -> None:
        """When an agent fails, the pipeline stops at that stage."""
        container = FakeContainer()
        container.agents["mason"] = FakeAgent(fail=True)
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=50,
                title="Will fail",
                skip_decompose=True,
            )
            implement = run.stages[2]
            assert implement.name == "implement"
            assert implement.status == StageStatus.FAILED
            assert implement.error != ""
            assert "failed at implement" in run.status
            # Stages after implement should still be PENDING
            assert run.stages[3].status == StageStatus.PENDING
            assert run.stages[4].status == StageStatus.PENDING
        finally:
            await engine.stop()


# -- BuilderPipeline.get_run() / list_runs() ------------------------------


class TestBuilderPipelineRetrieval:
    async def test_get_run_returns_run_after_execute(self) -> None:
        container = FakeContainer(response="ok")
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            run = await pipeline.execute(
                issue_number=60,
                title="Retrievable",
                skip_decompose=True,
            )
            fetched = pipeline.get_run("pipeline-60")
            assert fetched is run
        finally:
            await engine.stop()

    async def test_get_run_returns_none_for_unknown(self) -> None:
        engine = _make_engine()
        pipeline = BuilderPipeline(engine)
        assert pipeline.get_run("nonexistent") is None

    async def test_list_runs_returns_all(self) -> None:
        container = FakeContainer(response="ok")
        engine = _make_engine(container)
        await engine.start()
        try:
            pipeline = BuilderPipeline(engine)
            await pipeline.execute(
                issue_number=70,
                title="First",
                skip_decompose=True,
            )
            await pipeline.execute(
                issue_number=71,
                title="Second",
                skip_decompose=True,
            )
            runs = pipeline.list_runs()
            assert len(runs) == 2
            ids = {r["id"] for r in runs}
            assert "pipeline-70" in ids
            assert "pipeline-71" in ids
        finally:
            await engine.stop()

    async def test_list_runs_empty_initially(self) -> None:
        engine = _make_engine()
        pipeline = BuilderPipeline(engine)
        assert pipeline.list_runs() == []
