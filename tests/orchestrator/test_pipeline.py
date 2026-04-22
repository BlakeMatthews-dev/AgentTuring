"""Tests for BuilderPipeline, PipelineStage, PipelineRun."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

from stronghold.orchestrator.engine import WorkStatus
from stronghold.orchestrator.pipeline import (
    BUILDER_PIPELINE,
    BuilderPipeline,
    PipelineRun,
    PipelineStage,
    StageStatus,
)


# ── Helpers ──────────────────────────────────────────────────────────


class FakeWorkItem:
    """Lightweight stand-in for engine WorkItem results."""

    def __init__(
        self,
        status: WorkStatus = WorkStatus.COMPLETED,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> None:
        self.status = status
        self.result = result
        self.error = error


class FakeContainer:
    """Minimal container with a configurable agent registry."""

    def __init__(self, agent_names: list[str] | None = None) -> None:
        names = agent_names or ["quartermaster", "archie", "mason", "auditor", "gatekeeper"]
        self.agents: dict[str, object] = {n: object() for n in names}


class FakeEngine:
    """Fake OrchestratorEngine that records dispatch calls and returns
    pre-configured WorkItem results, resolving immediately (no real async wait).
    """

    def __init__(
        self,
        container: FakeContainer | None = None,
        results: dict[str, FakeWorkItem] | None = None,
        default_result: FakeWorkItem | None = None,
    ) -> None:
        self._container = container or FakeContainer()
        self._results = results or {}
        self._default = default_result or FakeWorkItem(
            status=WorkStatus.COMPLETED,
            result={
                "choices": [{"message": {"content": "stage output"}}],
            },
        )
        self.dispatched: list[dict[str, Any]] = []
        self.has_agent = lambda name: name in self._container.agents
        self._cancelled: list[str] = []

    def dispatch(self, **kwargs: Any) -> None:
        self.dispatched.append(kwargs)

    def get(self, work_id: str) -> FakeWorkItem | None:
        return self._results.get(work_id, self._default)

    def cancel(self, work_id: str) -> bool:
        self._cancelled.append(work_id)
        return True


# ── PipelineStage tests ─────────────────────────────────────────────


class TestPipelineStage:
    def test_defaults(self) -> None:
        stage = PipelineStage(name="test", agent_name="mason", prompt_template="do stuff")
        assert stage.status == StageStatus.PENDING
        assert stage.result is None
        assert stage.error == ""
        assert stage.skip_if == ""

    def test_to_dict_pending(self) -> None:
        stage = PipelineStage(name="s1", agent_name="a1", prompt_template="p")
        d = stage.to_dict()
        assert d["name"] == "s1"
        assert d["agent_name"] == "a1"
        assert d["status"] == "pending"
        assert d["started_at"] is None
        assert d["completed_at"] is None

    def test_to_dict_with_timestamps(self) -> None:
        now = datetime.now(UTC)
        stage = PipelineStage(
            name="s2",
            agent_name="a2",
            prompt_template="p",
            status=StageStatus.COMPLETED,
            started_at=now,
            completed_at=now,
        )
        d = stage.to_dict()
        assert d["status"] == "completed"
        assert d["started_at"] == now.isoformat()
        assert d["completed_at"] == now.isoformat()


# ── PipelineRun tests ────────────────────────────────────────────────


class TestPipelineRun:
    def test_defaults(self) -> None:
        run = PipelineRun(id="r1", issue_number=1, title="Test", repo="o/r")
        assert run.current_stage == 0
        assert run.status == "pending"
        assert run.stages == []
        # created_at defaults to a real UTC-aware timestamp, not None.
        assert run.created_at is not None
        assert run.created_at.tzinfo is not None
        # Must be close to "now" (within a wide 60-second window to avoid flakiness).
        now = datetime.now(UTC)
        delta_seconds = abs((now - run.created_at).total_seconds())
        assert delta_seconds < 60, f"created_at drift too large: {delta_seconds}s"

    def test_to_dict_empty_stages(self) -> None:
        run = PipelineRun(id="r2", issue_number=2, title="T", repo="o/r")
        d = run.to_dict()
        assert d["id"] == "r2"
        assert d["issue_number"] == 2
        assert d["stages"] == []

    def test_to_dict_with_stages(self) -> None:
        stage = PipelineStage(name="s", agent_name="a", prompt_template="p")
        run = PipelineRun(id="r3", issue_number=3, title="T", repo="o/r", stages=[stage])
        d = run.to_dict()
        assert len(d["stages"]) == 1
        assert d["stages"][0]["name"] == "s"


# ── BuilderPipeline tests ───────────────────────────────────────────


class TestBuilderPipeline:
    async def test_successful_run_all_stages(self) -> None:
        """All agents loaded, no skip conditions -- every stage completes."""
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42,
                title="Add caching",
                skip_decompose=False,
            )

        assert run.status == "completed"
        assert run.id == "pipeline-42"
        assert len(engine.dispatched) == 5
        for stage in run.stages:
            assert stage.status == StageStatus.COMPLETED

    async def test_skip_decompose_when_atomic(self) -> None:
        """skip_decompose=True skips the 'decompose' stage (skip_if='atomic')."""
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=10,
                title="Small fix",
                skip_decompose=True,
            )

        assert run.status == "completed"
        decompose_stage = run.stages[0]
        assert decompose_stage.name == "decompose"
        assert decompose_stage.status == StageStatus.SKIPPED
        assert len(engine.dispatched) == 4
        dispatched_stages = [d["metadata"]["stage"] for d in engine.dispatched]
        assert "decompose" not in dispatched_stages

    async def test_skip_cleanup_when_review_clean(self) -> None:
        """If the review stage output says 'no violations', cleanup is skipped."""
        review_result = FakeWorkItem(
            status=WorkStatus.COMPLETED,
            result={
                "choices": [{"message": {"content": "No violations found in this PR."}}],
            },
        )

        def smart_get(work_id: str) -> FakeWorkItem:
            if "review" in work_id:
                return review_result
            return FakeWorkItem(
                status=WorkStatus.COMPLETED,
                result={"choices": [{"message": {"content": "stage output"}}]},
            )

        engine = FakeEngine()
        engine.get = smart_get  # type: ignore[assignment]
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=7,
                title="Refactor",
                skip_decompose=True,
            )

        assert run.status == "completed"
        cleanup_stage = run.stages[4]
        assert cleanup_stage.name == "cleanup"
        assert cleanup_stage.status == StageStatus.SKIPPED

    async def test_agent_not_loaded_skips_stage(self) -> None:
        """If an agent isn't in the container, the stage is skipped."""
        container = FakeContainer(agent_names=["mason", "auditor"])
        engine = FakeEngine(container=container)
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=5,
                title="Test missing agents",
                skip_decompose=True,
            )

        assert run.status == "completed"
        scaffold_stage = run.stages[1]
        assert scaffold_stage.name == "scaffold"
        assert scaffold_stage.status == StageStatus.SKIPPED

        cleanup_stage = run.stages[4]
        assert cleanup_stage.name == "cleanup"
        assert cleanup_stage.status == StageStatus.SKIPPED

    async def test_failed_stage_halts_pipeline(self) -> None:
        """When a stage fails, the pipeline halts and reports the failure."""
        failed_item = FakeWorkItem(
            status=WorkStatus.FAILED,
            error="compilation error",
        )

        def fail_on_implement(work_id: str) -> FakeWorkItem:
            if "implement" in work_id:
                return failed_item
            return FakeWorkItem(
                status=WorkStatus.COMPLETED,
                result={"choices": [{"message": {"content": "ok"}}]},
            )

        engine = FakeEngine()
        engine.get = fail_on_implement  # type: ignore[assignment]
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=99,
                title="Broken build",
                skip_decompose=True,
            )

        assert "failed" in run.status
        assert "implement" in run.status

        implement_stage = run.stages[2]
        assert implement_stage.status == StageStatus.FAILED
        assert implement_stage.error == "compilation error"

        review_stage = run.stages[3]
        assert review_stage.status == StageStatus.PENDING

    async def test_work_item_lost_is_failure(self) -> None:
        """If engine.get returns None, treat as failure with 'Work item lost'."""

        def return_none(work_id: str) -> None:
            return None

        engine = FakeEngine()
        engine.get = return_none  # type: ignore[assignment]
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=50,
                title="Lost work",
                skip_decompose=True,
            )

        assert "failed" in run.status
        scaffold_stage = run.stages[1]
        assert scaffold_stage.status == StageStatus.FAILED
        assert scaffold_stage.error == "Work item lost"

    def test_get_run(self) -> None:
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)
        assert pipeline.get_run("nonexistent") is None

    def test_list_runs_empty(self) -> None:
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)
        assert pipeline.list_runs() == []

    async def test_get_run_after_execute(self) -> None:
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(issue_number=1, title="T", skip_decompose=True)
        assert pipeline.get_run(run.id) is run

    async def test_list_runs_after_execute(self) -> None:
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)
        with patch("asyncio.sleep", return_value=None):
            await pipeline.execute(issue_number=1, title="T1", skip_decompose=True)
            await pipeline.execute(issue_number=2, title="T2", skip_decompose=True)
        runs = pipeline.list_runs()
        assert len(runs) == 2

    async def test_dispatch_includes_correct_metadata(self) -> None:
        """Verify metadata passed to engine.dispatch is correct."""
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)
        with patch("asyncio.sleep", return_value=None):
            await pipeline.execute(issue_number=77, title="Meta test", skip_decompose=True)

        first = engine.dispatched[0]
        assert first["agent_name"] == "archie"
        assert first["trigger"] == "pipeline"
        assert first["priority_tier"] == "P5"
        assert first["intent_hint"] == "code_gen"
        assert first["metadata"]["issue_number"] == 77
        assert first["metadata"]["stage"] == "scaffold"

    async def test_prev_output_from_result_content_fallback(self) -> None:
        """When result has no 'choices', falls back to result['content']."""
        content_item = FakeWorkItem(
            status=WorkStatus.COMPLETED,
            result={"content": "fallback content"},
        )

        engine = FakeEngine(default_result=content_item)
        pipeline = BuilderPipeline(engine)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(issue_number=11, title="Fallback", skip_decompose=True)

        assert run.status == "completed"


class TestBuilderPipelineDefault:
    def test_default_pipeline_has_five_stages(self) -> None:
        assert len(BUILDER_PIPELINE) == 5

    def test_stage_names(self) -> None:
        names = [s.name for s in BUILDER_PIPELINE]
        assert names == ["decompose", "scaffold", "implement", "review", "cleanup"]

    def test_decompose_skips_on_atomic(self) -> None:
        assert BUILDER_PIPELINE[0].skip_if == "atomic"

    def test_cleanup_skips_on_review_clean(self) -> None:
        assert BUILDER_PIPELINE[4].skip_if == "review_clean"


# ── Spec-driven pipeline tests ────────────────────────────────────


class TestBuilderPipelineWithSpec:
    """Tests for spec-aware pipeline execution."""

    def _make_spec(self) -> "Spec":
        from stronghold.types.spec import Invariant, InvariantKind, Spec

        return Spec(
            issue_number=42,
            title="Add caching",
            protocols_touched=("LLMClient",),
            invariants=(
                Invariant(
                    name="cache_hit",
                    description="Cache returns stored value",
                    kind=InvariantKind.POSTCONDITION,
                    expression="cache.get(k) == v",
                    protocol="LLMClient",
                ),
            ),
            acceptance_criteria=("Cache hit returns stored response",),
            files_touched=("src/stronghold/api/litellm_client.py",),
        )

    async def test_spec_stored_in_run_context(self) -> None:
        """When a spec is provided, it's stored in run.context['spec']."""
        from tests.fakes import FakeSpecStore, FakeSpecVerifier

        engine = FakeEngine()
        store = FakeSpecStore()
        verifier = FakeSpecVerifier()
        spec = self._make_spec()
        await store.save(spec)

        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=True
            )

        assert run.context.get("spec") is not None
        assert run.context["spec"]["issue_number"] == 42

    async def test_verifier_called_per_stage(self) -> None:
        """Verifier is called after each completed stage."""
        from tests.fakes import FakeSpecStore, FakeSpecVerifier

        engine = FakeEngine()
        store = FakeSpecStore()
        verifier = FakeSpecVerifier(default_pass=True)
        spec = self._make_spec()
        await store.save(spec)

        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=True
            )

        assert run.status == "completed"
        verified_stages = [s for _, s in verifier.verify_calls]
        assert "scaffold" in verified_stages
        assert "implement" in verified_stages

    async def test_verification_failure_halts_pipeline(self) -> None:
        """If verifier fails on a stage, the pipeline halts."""
        from stronghold.types.spec import VerificationResult
        from tests.fakes import FakeSpecStore, FakeSpecVerifier

        engine = FakeEngine()
        store = FakeSpecStore()
        verifier = FakeSpecVerifier(default_pass=True)

        verifier.set_result(
            42,
            "implement",
            VerificationResult(
                spec_issue_number=42,
                stage="implement",
                passed=False,
                failures=("invariant 'cache_hit' violated",),
                coverage_pct=0.0,
            ),
        )

        spec = self._make_spec()
        await store.save(spec)

        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=True
            )

        assert "failed" in run.status
        assert "implement" in run.status

    async def test_no_spec_no_verification(self) -> None:
        """Pipeline works normally without spec_store/spec_verifier."""
        engine = FakeEngine()
        pipeline = BuilderPipeline(engine)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=99, title="No spec", skip_decompose=True
            )

        assert run.status == "completed"
        assert "spec" not in run.context

    async def test_spec_not_found_emits_and_runs(self) -> None:
        """If spec_store has no spec, pipeline emits one and runs with verification."""
        from tests.fakes import FakeSpecStore, FakeSpecVerifier

        engine = FakeEngine()
        store = FakeSpecStore()
        verifier = FakeSpecVerifier()

        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=999, title="Missing spec", skip_decompose=True
            )

        assert run.status == "completed"
        emitted = await store.get(999)
        assert emitted is not None
        assert emitted.title == "Missing spec"

    async def test_verification_results_stored_in_context(self) -> None:
        """Verification results are stored in run.context['verifications']."""
        from tests.fakes import FakeSpecStore, FakeSpecVerifier

        engine = FakeEngine()
        store = FakeSpecStore()
        verifier = FakeSpecVerifier(default_pass=True)
        spec = self._make_spec()
        await store.save(spec)

        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)
        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=True
            )

        verifications = run.context.get("verifications", [])
        assert len(verifications) > 0
        assert all(v["passed"] for v in verifications)
