"""Tests for end-to-end spec wiring through the pipeline.

Spec: specs/phase1-pipeline-wiring.yaml
Tests that Quartermaster emits specs and Archie enriches them.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from stronghold.orchestrator.engine import WorkStatus
from stronghold.orchestrator.pipeline import BuilderPipeline
from stronghold.types.spec import Invariant, InvariantKind, Spec, SpecStatus
from tests.fakes import FakeSpecStore, FakeSpecVerifier


class _FakeWorkItem:
    def __init__(self, content: str = "stage output") -> None:
        self.status = WorkStatus.COMPLETED
        self.result: dict[str, Any] = {
            "choices": [{"message": {"content": content}}],
        }
        self.error = ""


class _FakeEngine:
    def __init__(self, agent_names: list[str] | None = None) -> None:
        names = agent_names or [
            "quartermaster", "archie", "mason", "auditor", "gatekeeper",
        ]
        self._agents = set(names)
        self.dispatched: list[dict[str, Any]] = []
        self.has_agent = lambda name: name in self._agents
        self._cancelled: list[str] = []

    def dispatch(self, **kwargs: Any) -> None:
        self.dispatched.append(kwargs)

    def get(self, work_id: str) -> _FakeWorkItem:
        return _FakeWorkItem()

    def cancel(self, work_id: str) -> bool:
        self._cancelled.append(work_id)
        return True


# ── Spec 1006: Quartermaster emits spec ────────────────────────────


class TestQuartermasterSpecEmission:
    async def test_spec_emitted_after_decompose_skip(self) -> None:
        """When skip_decompose=True, spec is emitted from issue metadata."""
        store = FakeSpecStore()
        verifier = FakeSpecVerifier()
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=True
            )

        assert run.status == "completed"
        spec = await store.get(42)
        assert spec is not None
        assert spec.issue_number == 42
        assert spec.title == "Add caching"
        assert spec.status == SpecStatus.ACTIVE

    async def test_spec_emitted_after_decompose_runs(self) -> None:
        """When decompose runs, spec is emitted with stage output as body."""
        store = FakeSpecStore()
        verifier = FakeSpecVerifier()
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=False
            )

        assert run.status == "completed"
        spec = await store.get(42)
        assert spec is not None

    async def test_no_store_no_emission(self) -> None:
        """Without SpecStore, pipeline runs normally."""
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="No store", skip_decompose=True
            )

        assert run.status == "completed"

    async def test_spec_matches_issue(self) -> None:
        """Emitted spec has correct issue_number and title."""
        store = FakeSpecStore()
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=FakeSpecVerifier())

        with patch("asyncio.sleep", return_value=None):
            await pipeline.execute(issue_number=77, title="Fix auth bug", skip_decompose=True)

        spec = await store.get(77)
        assert spec is not None
        assert spec.issue_number == 77
        assert spec.title == "Fix auth bug"


# ── Spec 1007: Archie enriches spec with property tests ───────────


class TestArchieSpecEnrichment:
    async def test_spec_enriched_after_scaffold(self) -> None:
        """After scaffold stage, spec has property_tests populated."""
        store = FakeSpecStore()
        verifier = FakeSpecVerifier()
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)

        # Pre-seed a spec with invariants
        spec = Spec(
            issue_number=42,
            title="Add caching",
            invariants=(
                Invariant(
                    name="cache_hit",
                    description="Cache returns stored value",
                    kind=InvariantKind.POSTCONDITION,
                    expression="True",
                ),
            ),
            status=SpecStatus.ACTIVE,
        )
        await store.save(spec)

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=True
            )

        assert run.status == "completed"
        updated = await store.get(42)
        assert updated is not None
        assert len(updated.property_tests) == 1
        assert updated.uncovered_invariants == ()

    async def test_no_spec_scaffold_runs_normally(self) -> None:
        """If no spec exists, scaffold runs without enrichment."""
        store = FakeSpecStore()
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=FakeSpecVerifier())

        with patch("asyncio.sleep", return_value=None):
            run = await pipeline.execute(
                issue_number=999, title="No spec", skip_decompose=True
            )

        assert run.status == "completed"

    async def test_spec_summary_updated_after_enrichment(self) -> None:
        """Spec summary in prompts reflects enriched spec."""
        store = FakeSpecStore()
        verifier = FakeSpecVerifier()
        engine = _FakeEngine()
        pipeline = BuilderPipeline(engine, spec_store=store, spec_verifier=verifier)

        spec = Spec(
            issue_number=42,
            title="Add caching",
            invariants=(
                Invariant(
                    name="cache_hit",
                    description="Cache returns stored value",
                    kind=InvariantKind.POSTCONDITION,
                    expression="True",
                ),
            ),
            acceptance_criteria=("Cache hit returns stored response",),
            status=SpecStatus.ACTIVE,
        )
        await store.save(spec)

        with patch("asyncio.sleep", return_value=None):
            await pipeline.execute(
                issue_number=42, title="Add caching", skip_decompose=True
            )

        # Mason's prompt (implement stage) should contain spec summary
        implement_dispatch = [
            d for d in engine.dispatched if d["metadata"]["stage"] == "implement"
        ]
        assert len(implement_dispatch) == 1
        prompt = implement_dispatch[0]["messages"][0]["content"]
        assert "cache_hit" in prompt
